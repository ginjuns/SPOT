"""POST /api/kakao/skill — 카카오톡 채널 챗봇 (카카오 i 오픈빌더의 스킬 서버).

오픈빌더가 사용자의 말을 이 주소로 보내 준다. 스킬은 5초 안에 답해야 해서,
블록에 "AI 챗봇 콜백"을 켜 두면 요청에 callbackUrl 이 같이 온다. 그때는 바로 "기다려 주세요"
(useCallback: true)로 답하고, 실제 처리(검색·AI)는 뒤에서 한 뒤 callbackUrl 로 한 번 보낸다 (5분 안, 한 번만).

카카오는 요청 서명을 주지 않으므로, 오픈빌더 스킬 설정의 "헤더값"에 비밀 문자열을 넣고 여기서 검사한다.
대화 글은 저장하지 않고, 로그에도 남기지 않는다. 처리는 모두 services/messenger.py 가 한다.
문서: https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide (2026-11-21 확인)
"""
import hmac
import logging
import threading
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app import config
from app.services import messenger

router = APIRouter(prefix="/api/kakao")
logger = logging.getLogger("benefit")

PLATFORM = "kakao"
SECRET_HEADER = "x-spot-secret"   # 오픈빌더 스킬 "헤더값 입력"의 Key (Value 에 비밀 문자열)
OUTPUT_LIMIT = 3                  # 응답 하나에 말풍선 3개까지
QUICK_LIMIT = 10                  # 바로가기 버튼 10개까지
CAROUSEL_LIMIT = 10               # 캐러셀 카드 10장까지
CARD_BUTTONS = 3                  # 카드 하나에 버튼 3개까지 (세로)
LABEL_LIMIT = 14                  # 버튼 이름 14자까지
TEXT_LIMIT = 1000                 # simpleText 글
CARD_TEXT_LIMIT = 400             # textCard 하나일 때 설명
CAROUSEL_TEXT_LIMIT = 128         # 캐러셀 안 textCard 설명
TITLE_LIMIT = 50
WAIT_TEXT = "잠시만 기다려 주세요. 찾아보고 있어요."
PICK_TEXT = "골라 주세요."
ERROR_TEXT = "잠시 문제가 생겼어요. 조금 뒤에 다시 해 주세요."
HOW_TO_ASK = "궁금한 것을 이 대화창에 적어 보내 주세요. 처음부터 다시 하려면 \"처음부터\"라고 적어 주세요."
RESET_WORDS = {"처음부터", "처음으로", "다시"}
HELP_WORDS = {"안내", "도움말", "시작", ""}

# 사용자에게 마지막으로 보여 준 버튼 이름 → 누름 코드 (30분). 버튼을 누르면 그 이름이 사용자 말로 오므로,
# 이름으로 코드를 찾는다. 버튼 이름은 우리가 만든 글이고, 사용자 대화 글은 아니다.
_buttons = {}
_buttons_lock = threading.Lock()


def _remember_buttons(user, replies, now):
    codes = {b["label"]: b["data"] for r in replies for row in r["buttons"] for b in row if "data" in b}
    key = messenger.user_key(PLATFORM, user)
    with _buttons_lock:
        for k in [k for k, v in _buttons.items() if v[1] <= now]:
            del _buttons[k]
        if codes:
            _buttons[key] = (codes, now + messenger.STATE_TTL)
        else:
            _buttons.pop(key, None)


def _code_for(user, text, now):
    with _buttons_lock:
        codes, expires = _buttons.get(messenger.user_key(PLATFORM, user), ({}, 0))
    return codes.get(text) if expires > now else None


# ---------- 공통 말 목록 → 카카오 응답 ----------

def _cut(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _message_button(b):
    """누르면 버튼 이름 전체가 사용자 말로 온다 (긴 예시 질문도 그대로 질문이 된다)."""
    return {"label": _cut(b["label"], LABEL_LIMIT), "action": "message", "messageText": b["label"],
            "extra": {"code": b["data"]}}


def _link_button(b):
    return {"label": _cut(b["label"], LABEL_LIMIT), "action": "webLink", "webLinkUrl": b["url"]}


def _text(text):
    return {"simpleText": {"text": _cut(text, TEXT_LIMIT)}}


def _link_card(text, links, in_carousel):
    """링크 버튼이 붙은 말 → textCard. 첫 줄은 제목으로 쓴다 (정책 카드의 이름)."""
    title, _, rest = text.partition("\n")
    card = {"title": _cut(title, TITLE_LIMIT), "buttons": [_link_button(b) for b in links[:CARD_BUTTONS]]}
    if rest.strip():
        card["description"] = _cut(rest.strip(), CAROUSEL_TEXT_LIMIT if in_carousel else CARD_TEXT_LIMIT)
    return card


def _carousel(cards):
    return {"carousel": {"type": "textCard", "items": cards[:CAROUSEL_LIMIT]}}


def to_response(replies):
    """공통 말 목록 → 카카오 스킬 응답 (version 2.0).

    - 링크 버튼이 붙은 말(정책 카드)이 이어지면 캐러셀 하나로 묶는다.
    - 고르는 버튼이 10개 이하면 바로가기 버튼으로, 많으면 카드(3개씩) 캐러셀로, 남는 것은 바로가기로 보낸다.
    - 정책 카드 끝의 "최종 확인" 문구는 카드 밖 글로 뺀다 (캐러셀 설명은 128자까지라 잘릴 수 있다).
    """
    outputs, quick, cards, tail = [], [], [], []

    def flush():
        if len(cards) == 1:
            outputs.append({"textCard": _link_card(*cards[0], in_carousel=False)})
        elif cards:
            outputs.append(_carousel([_link_card(t, l, in_carousel=True) for t, l in cards]))
        cards.clear()

    for reply in replies:
        text = reply["text"]
        flat = [b for row in reply["buttons"] for b in row]
        links = [b for b in flat if "url" in b]
        choices = [b for b in flat if "data" in b]
        if text.endswith("\n\n" + messenger.CONFIRM_TEXT):
            text = text[: -len(messenger.CONFIRM_TEXT) - 2]
            tail.append(messenger.CONFIRM_TEXT)
        if links and not choices:
            cards.append((text, links))
            continue
        flush()
        if not choices:
            outputs.append(_text(text))
        elif len(choices) <= QUICK_LIMIT and not quick:
            outputs.append(_text(text))
            quick = choices
        else:
            outputs.append(_text(text))
            room = CAROUSEL_LIMIT * CARD_BUTTONS
            groups = [choices[i:i + CARD_BUTTONS] for i in range(0, min(len(choices), room), CARD_BUTTONS)]
            outputs.append(_carousel([{"description": PICK_TEXT, "buttons": [_message_button(b) for b in g]}
                                      for g in groups]))
            quick = choices[room:room + QUICK_LIMIT]
    flush()
    outputs += [_text(t) for t in tail]
    # 말풍선은 3개까지라서, 이어진 글 말풍선은 하나로 합친다.
    merged = []
    for o in outputs:
        if merged and "simpleText" in o and "simpleText" in merged[-1]:
            joined = merged[-1]["simpleText"]["text"] + "\n\n" + o["simpleText"]["text"]
            merged[-1] = _text(joined)
        else:
            merged.append(o)
    template = {"outputs": merged[:OUTPUT_LIMIT] or [_text(ERROR_TEXT)]}
    if quick:
        template["quickReplies"] = [_message_button(b) for b in quick]
    return {"version": "2.0", "template": template}


# ---------- 처리 ----------

def replies_for(body, now=None):
    """스킬 요청 하나 → 공통 말 목록."""
    now = now or time.time()
    user_request = body.get("userRequest") or {}
    user = (user_request.get("user") or {}).get("id")
    if not user or not isinstance(user, str):
        return [{"text": ERROR_TEXT, "buttons": []}]
    text = (user_request.get("utterance") or "").strip()
    extra = (body.get("action") or {}).get("clientExtra") or {}
    code = extra.get("code") if isinstance(extra, dict) else None
    code = code if isinstance(code, str) else _code_for(user, text, now)

    if code:
        replies = messenger.on_button(PLATFORM, user, code, now=now)
    elif text in RESET_WORDS:
        replies = messenger.on_button(PLATFORM, user, "r", now=now)
    elif text in HELP_WORDS:   # 빈 말 = 웰컴 블록 (대화창에 처음 들어옴)
        replies = messenger.start(PLATFORM, user, HOW_TO_ASK)
    else:
        replies = messenger.on_text(PLATFORM, user, text, now=now)
    _remember_buttons(user, replies, now)
    return replies


def answer(body):
    try:
        return to_response(replies_for(body))
    except Exception as e:   # 글 내용은 남기지 않는다.
        logger.error("kakao process %s", type(e).__name__)
        return to_response([{"text": ERROR_TEXT, "buttons": []}])


def post_callback(url, response):
    try:
        r = httpx.post(url, json=response, timeout=15)
        result = r.json() if r.status_code == 200 else {}
        if result.get("status") != "SUCCESS":
            logger.warning("kakao callback %s %s", r.status_code, result.get("status"))
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("kakao callback %s", type(e).__name__)


def run_callback(url, body):
    post_callback(url, answer(body))


@router.post("/skill")
async def skill(request: Request, background: BackgroundTasks):
    if not config.KAKAO_SKILL_SECRET:
        raise HTTPException(404, "찾으시는 화면이 없어요.")
    sent = request.headers.get(SECRET_HEADER)
    if sent is None or not hmac.compare_digest(sent.strip().encode(), config.KAKAO_SKILL_SECRET.strip().encode()):
        # 값은 남기지 않고, 헤더가 없었는지 달랐는지만 남긴다 (오픈빌더 설정을 고칠 때 쓴다).
        logger.warning("kakao 403 %s", "no-header" if sent is None else "wrong-secret")
        raise HTTPException(403, "허용되지 않은 요청이에요.")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "잘못된 요청이에요.")
    if not isinstance(body, dict):
        raise HTTPException(400, "잘못된 요청이에요.")
    logger.info("kakao skill")
    callback = (body.get("userRequest") or {}).get("callbackUrl")
    if isinstance(callback, str) and urlparse(callback).scheme == "https":
        background.add_task(run_callback, callback, body)
        return {"version": "2.0", "useCallback": True, "data": {"text": WAIT_TEXT}}
    # 콜백이 꺼진 블록: 바로 처리한다. AI 답변은 5초를 넘길 수 있으니 블록에 콜백을 켜 두어야 한다.
    return await run_in_threadpool(answer, body)

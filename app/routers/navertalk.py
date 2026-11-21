"""POST /api/navertalk/webhook/{비밀 문자열} — 네이버 톡톡 챗봇 (웹훅 + 보내기 API).

네이버 톡톡이 사용자의 글·버튼 누름을 이 주소로 보내 준다. 받자마자 200으로 답하고,
실제 처리(검색·AI)는 뒤에서 한 뒤 "보내기 API"로 답을 보낸다 (웹훅은 5초 안에 답해야 한다).
네이버 톡톡은 요청 서명을 주지 않으므로, 아무도 모르는 비밀 문자열을 주소 끝에 넣어 검사한다.
대화 글은 저장하지 않고, 로그에도 남기지 않는다. 처리는 모두 services/messenger.py 가 한다.
문서: https://github.com/navertalk/chatbot-api (2026-11-21 확인)
"""
import hmac
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app import config
from app.services import messenger

router = APIRouter(prefix="/api/navertalk")
logger = logging.getLogger("benefit")

PLATFORM = "navertalk"
SEND_API = "https://gw.talk.naver.com/chatbot/v1/event"
TEXT_LIMIT = 10000          # 글 메시지 최대 글자 수
DESCRIPTION_LIMIT = 1000    # 버튼이 붙은 메시지(compositeContent)의 글 최대 글자 수
BUTTONS_PER_MESSAGE = 10    # 메시지 하나에 붙일 수 있는 버튼 수
LABEL_LIMIT = 18            # 버튼 이름 최대 글자 수
MORE_TEXT = "이어서 골라 주세요."
PICK_TEXT = "아래에서 골라 주세요."
ONLY_TEXT = "글로 적어 주세요. 사진이나 소리는 아직 알아듣지 못해요."
HOW_TO_ASK = "궁금한 것을 이 대화창에 적어 보내 주세요. 처음부터 다시 하려면 \"처음부터\"라고 적어 주세요."
RESET_WORDS = {"처음부터", "처음으로", "다시"}
HELP_WORDS = {"안내", "도움말", "시작"}


class _HideSecret(logging.Filter):
    """접속 기록(uvicorn.access)에 주소의 비밀 문자열이 남지 않게 가린다."""

    def filter(self, record):
        secret = config.NAVERTALK_WEBHOOK_SECRET
        if secret and isinstance(record.args, tuple):
            record.args = tuple(a.replace(secret, "***") if isinstance(a, str) else a for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_HideSecret())


def call(payload):
    """보내기 API 호출. 실패해도 서버가 멈추지 않게 로그(결과 코드나 오류 종류)만 남긴다."""
    try:
        r = httpx.post(SEND_API, json=payload, timeout=15,
                       headers={"Authorization": config.NAVERTALK_AUTH_KEY})
        result = r.json() if r.status_code == 200 else {}
        if not result.get("success"):
            logger.warning("navertalk send %s %s", r.status_code, result.get("resultCode"))
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("navertalk send %s", type(e).__name__)


def _label(text):
    return text if len(text) <= LABEL_LIMIT else text[:LABEL_LIMIT - 1] + "…"


def to_button(b):
    if "url" in b:
        return {"type": "LINK", "data": {"title": _label(b["label"]), "url": b["url"], "mobileUrl": b["url"]}}
    return {"type": "TEXT", "data": {"title": _label(b["label"]), "code": b["data"]}}


def to_events(user, reply):
    """공통 말 하나 → 네이버 톡톡 보낼 것 목록.

    버튼은 메시지 하나에 10개까지라서, 시·도(17개)·시·군·구(최대 32개)처럼 많으면 여러 메시지로 나눈다.
    버튼 이름은 18자까지라서, 긴 이름(예시 질문)은 글 안에 전부 적고 버튼에는 앞부분만 쓴다.
    """
    text = reply["text"]
    buttons = [b for row in reply["buttons"] for b in row]
    if not buttons:
        return [{"event": "send", "user": user, "textContent": {"text": text[:TEXT_LIMIT]}}]
    long = [b["label"] for b in buttons if len(b["label"]) > LABEL_LIMIT]
    if long:
        text += "\n\n" + "\n".join(f"- {label}" for label in long)
    events = []
    if len(text) > DESCRIPTION_LIMIT:
        events.append({"event": "send", "user": user, "textContent": {"text": text[:TEXT_LIMIT]}})
        text = PICK_TEXT
    for i in range(0, len(buttons), BUTTONS_PER_MESSAGE):
        chunk = buttons[i:i + BUTTONS_PER_MESSAGE]
        events.append({"event": "send", "user": user, "compositeContent": {"compositeList": [
            {"description": text if i == 0 else MORE_TEXT, "buttonList": [to_button(b) for b in chunk]}]}})
    return events


def send(user, replies):
    for reply in replies:
        for event in to_events(user, reply):
            call(event)


def typing(user):
    call({"event": "action", "user": user, "options": {"action": "typingOn"}})


def process(event):
    """네이버 톡톡 이벤트 하나 처리 (뒤에서 실행)."""
    kind = event.get("event")
    user = event.get("user")
    if not user or not isinstance(user, str):
        return
    if kind == "open":   # 사용자가 대화창에 들어왔다
        send(user, messenger.start(PLATFORM, user, HOW_TO_ASK))
        return
    if kind != "send":
        return           # leave(나감), friend(친구 추가), echo(우리가 보낸 것의 되돌림) 등은 답하지 않는다
    content = event.get("textContent")
    if not isinstance(content, dict):
        send(user, [{"text": ONLY_TEXT, "buttons": []}])
        return
    code = content.get("code")
    if content.get("inputType") == "button" and code:   # 우리가 보낸 버튼을 눌렀다
        typing(user)
        send(user, messenger.on_button(PLATFORM, user, code))
        return
    text = (content.get("text") or "").strip()
    if text in RESET_WORDS:
        replies = messenger.on_button(PLATFORM, user, "r")
    elif text in HELP_WORDS:
        replies = messenger.start(PLATFORM, user, HOW_TO_ASK)
    elif not text:
        replies = [{"text": ONLY_TEXT, "buttons": []}]
    else:
        typing(user)
        replies = messenger.on_text(PLATFORM, user, text)
    send(user, replies)


def run(event):
    try:
        process(event)
    except Exception as e:   # 뒤에서 난 오류. 글 내용은 남기지 않는다.
        logger.error("navertalk process %s", type(e).__name__)


@router.post("/webhook/{secret}")
async def webhook(secret: str, request: Request, background: BackgroundTasks):
    if not (config.NAVERTALK_AUTH_KEY and config.NAVERTALK_WEBHOOK_SECRET):
        raise HTTPException(404, "찾으시는 화면이 없어요.")
    if not hmac.compare_digest(secret.encode(), config.NAVERTALK_WEBHOOK_SECRET.encode()):
        raise HTTPException(403, "허용되지 않은 요청이에요.")
    try:
        event = await request.json()
    except ValueError:
        raise HTTPException(400, "잘못된 요청이에요.")
    if isinstance(event, dict):
        background.add_task(run, event)
    logger.info("navertalk event")
    return Response(status_code=200)   # 본문 없이 200: 답은 보내기 API로 따로 보낸다

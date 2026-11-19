"""메신저(텔레그램·디스코드, 나중에 네이버 톡톡·카카오톡) 공통 처리.

플랫폼 연결 파일은 사용자가 보낸 글이나 누른 버튼을 여기로 넘기고,
돌려받은 "말 목록"을 자기 플랫폼 형식으로 바꿔 보내기만 한다.

말 하나 = {"text": 글, "buttons": [[버튼, ...], ...]}  (buttons 는 줄 단위, 없으면 빈 목록)
버튼 하나 = {"label": 이름, "data": 누름 코드} 또는 {"label": 이름, "url": 주소}

누름 코드는 짧게 쓴다 (텔레그램 callback_data 는 64바이트까지).
  a:65_74 / a:-   나이대 고르기 / 건너뛰기
  s:11    / s:-   시·도 고르기 / 지역 건너뛰기
  g:11680 / g:-   시·군·구 고르기 / 시·군·구 건너뛰기 (시·도만으로 찾는다)
  e:0             예시 질문
  r               처음부터

대화 글은 저장하지 않는다. 사용자별로 "정해진 조건"만 메모리에 30분 동안 기억한다.
"""
import csv
import datetime
import hashlib
import json
import secrets
import threading
import time
from urllib.parse import urlencode

from pydantic import ValidationError

from app import config
from app.models import ChatRequest
from app.services import chat_core

STATE_TTL = 30 * 60   # 조건을 기억하는 시간 (초)

OPTIONS = json.loads((config.DATA_DIR / "options.json").read_text(encoding="utf-8"))
AGE_LABELS = {o["value"]: o["label"] for o in OPTIONS["age_group"]}


def _read_regions():
    """data/regions.csv (DB의 region 테이블과 같은 내용) → 시·도 목록, 시·도별 시·군·구 목록."""
    sido, sigungu = {}, {}
    with open(config.DATA_DIR / "regions.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["sigungu"]:
                sigungu.setdefault(row["code"][:2], []).append((row["code"], row["sigungu"]))
            else:
                sido[row["code"]] = row["sido"]
    sido = dict(sorted(sido.items(), key=lambda item: item[1]))
    for items in sigungu.values():
        items.sort(key=lambda item: item[1])
    return sido, sigungu


SIDO, SIGUNGU = _read_regions()

EXAMPLES = [
    "허리가 아파서 병원에 가려는데 지원받을 수 있는 게 있나요?",
    "혼자 사는데 겨울 난방비가 걱정이에요",
    "아이를 낳았는데 받을 수 있는 지원금이 있나요?",
]
GREETING = (
    "안녕하세요, SPOT이에요.\n"
    "지금 겪고 계신 상황을 평소 말투로 적어 주시면, 확인해 볼 만한 나라·지자체 지원을 찾아 드려요.\n\n"
    "이름이나 전화번호는 적지 않으셔도 돼요. 대화는 이 메신저 회사 서버에 남을 수 있어요.\n\n"
    "이렇게 물어보셔도 돼요:"
)
RESET_TEXT = "처음부터 다시 할게요. 궁금한 점을 적어 주세요."
EXPIRED_TEXT = "시간이 조금 지나서 앞의 내용을 잊었어요. 궁금한 점을 다시 적어 주세요."
EMPTY_TEXT = "궁금한 점을 글로 적어 주세요."
ASK_AGE_TEXT = "나이대를 골라 주세요."
ASK_SIDO_TEXT = "사시는 시·도를 골라 주세요."
ASK_SIGUNGU_TEXT = "{sido}의 어느 시·군·구에 사세요?"
CONFIRM_TEXT = "자격은 신청하는 곳에서 최종 확인해 주세요."
DAILY_LIMIT_TEXT = "오늘은 메신저로 받을 수 있는 질문을 다 썼어요. 웹에서는 직접 찾아보실 수 있어요."
SKIP_LABEL = "잘 모르겠어요 / 건너뛰기"
# 카드에 신청 기간을 보여 주지 않는 값 (웹 카드와 같은 규칙, web/js/api.js)
PLAIN_PERIODS = {"상시신청", "접수기관 별 상이", "연중"}

_lock = threading.Lock()
_salt = secrets.token_bytes(16)
_states = {}          # 사용자 키 → {"conditions", "asked", "pending", "expires"}
_daily = {}           # (날짜, 플랫폼) → 오늘 질문 수


def user_key(platform, user_id):
    """플랫폼 사용자 ID 원문은 남기지 않는다. 실행마다 새로 만드는 임의 값과 섞어 해시한 것만 쓴다."""
    return hashlib.sha256(_salt + f"{platform}:{user_id}".encode()).hexdigest()[:16]


def reset():
    """테스트용."""
    with _lock:
        _states.clear()
        _daily.clear()


# ---------- 조건 기억 ----------

def _load(key, now):
    with _lock:
        for k in [k for k, s in _states.items() if s["expires"] <= now]:   # 오래된 것은 지운다
            del _states[k]
        state = _states.get(key)
        return None if state is None else {**state, "conditions": dict(state["conditions"])}


def _save(key, state, now):
    with _lock:
        _states[key] = {**state, "expires": now + STATE_TTL}


def _forget(key):
    with _lock:
        _states.pop(key, None)


def _count_question(platform, today):
    """플랫폼마다 하루 질문 수 상한 (MESSENGER_DAILY_LIMIT). 넘으면 False."""
    with _lock:
        for k in [k for k in _daily if k[0] != today]:
            del _daily[k]
        count = _daily.get((today, platform), 0)
        if count >= config.MESSENGER_DAILY_LIMIT:
            return False
        _daily[(today, platform)] = count + 1
        return True


# ---------- 말 만들기 ----------

def _say(text, buttons=None):
    return {"text": text, "buttons": buttons or []}


def _rows(buttons, per_row):
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _web(path, params=None):
    """웹 주소. PUBLIC_BASE_URL 이 비어 있으면 None (링크 버튼을 만들지 않는다)."""
    base = config.PUBLIC_BASE_URL.rstrip("/")
    if not base:
        return None
    query = urlencode({k: v for k, v in (params or {}).items() if v})
    return f"{base}/{path}" + (f"?{query}" if query else "")


def _link_row(*pairs):
    row = [{"label": label, "url": url} for label, url in pairs if url]
    return [row] if row else []


def _ask_age():
    buttons = [{"label": label, "data": f"a:{value}"} for value, label in AGE_LABELS.items()]
    return _say(ASK_AGE_TEXT, _rows(buttons, 2) + [[{"label": SKIP_LABEL, "data": "a:-"}]])


def _ask_sido():
    buttons = [{"label": name, "data": f"s:{code}"} for code, name in SIDO.items()]
    return _say(ASK_SIDO_TEXT, _rows(buttons, 3) + [[{"label": SKIP_LABEL, "data": "s:-"}]])


def _ask_sigungu(sido_code):
    buttons = [{"label": name, "data": f"g:{code}"} for code, name in SIGUNGU[sido_code]]
    return _say(ASK_SIGUNGU_TEXT.format(sido=SIDO[sido_code]),
                _rows(buttons, 3) + [[{"label": SKIP_LABEL, "data": "g:-"}]])


def _ask(item):
    return _ask_age() if item == "age_group" else _ask_sido()


def policy_text(number, policy):
    """정책 하나를 글로. 내용은 DB 값 그대로이고, AI가 쓴 것은 한 줄 요약(one_line)뿐이다."""
    lines = [f"{number}. {policy['name']}"]
    if policy.get("agency"):
        lines.append(policy["agency"])
    if policy.get("one_line"):
        lines.append(policy["one_line"])
    if policy.get("has_income_rule"):
        lines.append("※ 소득 기준 있음")
    period = (policy.get("apply_period") or "").strip()
    if period and len(period) <= 30 and period not in PLAIN_PERIODS:
        lines.append(f"신청 기간: {period}")
    if policy.get("collected_at"):
        lines.append(f"자료 기준일: {policy['collected_at']}")
    return "\n".join(lines)


def _result(response):
    policies = response["policies"][:5]
    replies = [_say(response["text"])]
    for i, p in enumerate(policies, 1):
        text = policy_text(i, p)
        if i == len(policies):
            text += "\n\n" + CONFIRM_TEXT
        buttons = _link_row(("자세히 보기", _web("policy.html", {"id": p["id"]})), ("원문 보기", p.get("url")))
        replies.append(_say(text, buttons))
    return replies


def _search_link(conditions):
    """AI 답변이 안 될 때 이어서 쓸 웹 직접 찾기 주소."""
    conditions = conditions or {}
    return _web("search.html", {"result": "1", "age_group": conditions.get("age_group"),
                                "region_code": conditions.get("region_code")})


# ---------- 처리 ----------

def _run(key, state, message, now):
    """chat_core.handle 을 부르고 결과를 말 목록으로 바꾼다. 대화 글(history)은 넘기지 않는다."""
    try:
        req = ChatRequest(message=message, conditions=state["conditions"], asked=state["asked"])
    except ValidationError:
        _forget(key)
        return [_say(EXPIRED_TEXT)]
    response = chat_core.handle(req, key)
    kind = response["type"]
    if response.get("conditions"):
        state["conditions"] = {k: v for k, v in response["conditions"].items() if v is not None}

    if kind == "error":
        return [_say(response["text"])]
    if kind == "ask":
        state["asked"] = True
        state["pending"] = list(response["ask"])
        _save(key, state, now)
        return [_say(response["text"]), _ask(state["pending"][0])]
    _save(key, {**state, "pending": []}, now)
    if kind == "result":
        return _result(response)
    if kind == "fallback":
        return [_say(response["text"], _link_row(("직접 찾아보기", _search_link(response.get("conditions")))))]
    return [_say(response["text"])]   # none


def start(platform, user_id):
    """/start 같은 처음 인사. 그 사용자의 조건을 지운다."""
    _forget(user_key(platform, user_id))
    examples = [[{"label": text, "data": f"e:{i}"}] for i, text in enumerate(EXAMPLES)]
    return [_say(GREETING, examples)]


def on_text(platform, user_id, text, now=None, today=None):
    """사용자가 보낸 글 = 질문."""
    now = now or time.time()
    today = today or datetime.date.today()
    text = (text or "").strip()
    if not text:
        return [_say(EMPTY_TEXT)]
    if not _count_question(platform, today):
        return [_say(DAILY_LIMIT_TEXT, _link_row(("웹에서 찾아보기", _web(""))))]
    key = user_key(platform, user_id)
    # 앞에서 고른 조건(나이대·지역)과 "되물었음" 표시는 30분 동안 다음 질문에도 쓴다 (웹 채팅과 같다).
    state = _load(key, now) or {"conditions": {}, "asked": False, "pending": []}
    return _run(key, state, text, now)


def on_button(platform, user_id, data, now=None, today=None):
    """사용자가 누른 버튼."""
    now = now or time.time()
    key = user_key(platform, user_id)
    kind, _, value = (data or "").partition(":")

    if kind == "r":
        _forget(key)
        return [_say(RESET_TEXT)]
    if kind == "e" and value.isdigit() and int(value) < len(EXAMPLES):
        return on_text(platform, user_id, EXAMPLES[int(value)], now=now, today=today)

    state = _load(key, now)
    if not state or not state["pending"]:
        return [_say(EXPIRED_TEXT)]
    item = state["pending"][0]
    cond = state["conditions"]

    if item == "age_group" and kind == "a" and (value == "-" or value in AGE_LABELS):
        if value != "-":
            cond["age_group"] = value
    elif item == "region" and kind == "s" and value == "-":
        pass
    elif item == "region" and kind == "s" and value in SIDO:
        if value in SIGUNGU:
            cond["region_code"] = value   # 시·군·구를 건너뛰면 시·도로 찾는다
            _save(key, state, now)
            return [_ask_sigungu(value)]
        cond["region_code"] = value       # 세종·제주처럼 시·군·구가 없는 곳
    elif item == "region" and kind == "g" and value == "-" and cond.get("region_code") in SIGUNGU:
        pass
    elif (item == "region" and kind == "g" and cond.get("region_code") in SIGUNGU
          and value in dict(SIGUNGU[cond["region_code"]])):
        cond["region_code"] = value
    else:
        return [_say(EXPIRED_TEXT)]   # 지금 묻는 것과 맞지 않는 버튼 (예전 메시지의 버튼 등)

    state["pending"] = state["pending"][1:]
    if state["pending"]:
        _save(key, state, now)
        return [_ask(state["pending"][0])]
    # 다 골랐다: 질문 분석 없이 바로 검색한다.
    return _run(key, state, "", now)

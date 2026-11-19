"""POST /api/discord/interactions — 디스코드 봇 (Interactions Endpoint, HTTP 방식).

슬래시 명령 봇이다: /물어보기 질문:<글>, /처음부터.
디스코드는 3초 안에 첫 응답을 받아야 하므로, 바로 "생각 중"(나중에 답함)으로 응답하고
검색·AI 처리는 뒤에서 한 뒤 웹훅 주소로 답을 채운다 (토큰은 15분 유효).
답은 본인에게만 보이게(ephemeral) 보낸다. 대화 글은 저장하지 않고 로그에도 남기지 않는다.
처리는 모두 services/messenger.py 가 한다.
"""
import json
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from app import config
from app.services import messenger

router = APIRouter(prefix="/api/discord")
logger = logging.getLogger("benefit")
logging.getLogger("httpx").setLevel(logging.WARNING)   # 요청 주소(웹훅 토큰 포함)를 로그에 남기지 않는다

PLATFORM = "discord"
API = "https://discord.com/api/v10"
ASK_COMMAND = "물어보기"      # 한글 이름 등록 확인 (2026-11-19)
RESET_COMMAND = "처음부터"
HELP_COMMAND = "안내"          # 처음 인사, 개인정보 안내, 예시 질문
HOW_TO_ASK = "디스코드에서는 /물어보기 를 적고, 질문 칸에 궁금한 것을 적어 보내 주세요."
QUESTION_OPTION = "질문"
EPHEMERAL = 64                # 본인에게만 보이는 메시지
TEXT_LIMIT = 2000
MAX_BUTTONS = 5               # 줄 하나에 버튼 5개, 메시지 하나에 줄 5개
MENU_LIMIT = 25               # 선택 메뉴 하나에 항목 25개

# 상호작용 종류와 응답 종류 (디스코드 문서의 숫자)
PING, COMMAND, COMPONENT = 1, 2, 3
PONG, MESSAGE, DEFERRED_MESSAGE, DEFERRED_UPDATE = 1, 4, 5, 6


def verify(body, signature, timestamp):
    """디스코드가 보낸 요청인지 서명을 검사한다 (Ed25519, 타임스탬프 + 본문)."""
    try:
        VerifyKey(bytes.fromhex(config.DISCORD_PUBLIC_KEY)).verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError):
        return False


# ---------- 공통 말 → 디스코드 메시지 ----------

def _menu_rows(text, choices):
    """버튼이 많으면(나이대, 시·도, 시·군·구) 선택 메뉴로. 25개가 넘으면 메뉴를 나눈다."""
    rows = []
    for i in range(0, len(choices), MENU_LIMIT):
        part = choices[i:i + MENU_LIMIT]
        placeholder = text if len(choices) <= MENU_LIMIT else f"{text} ({i // MENU_LIMIT + 1})"
        rows.append({"type": 1, "components": [{
            "type": 3, "custom_id": f"menu:{i // MENU_LIMIT}", "placeholder": placeholder[:150],
            "options": [{"label": b["label"][:100], "value": b["data"]} for b in part],
        }]})
    return rows


def to_message(reply):
    """공통 말 하나 → 디스코드 메시지 (글 + 버튼 줄 또는 선택 메뉴)."""
    def button(b):
        if "url" in b:
            return {"type": 2, "style": 5, "label": b["label"][:80], "url": b["url"]}
        return {"type": 2, "style": 1, "label": b["label"][:80], "custom_id": b["data"]}

    choices = [b for row in reply["buttons"] for b in row if "data" in b]
    if len(choices) > MAX_BUTTONS:
        link_rows = [[b for b in row if "url" in b] for row in reply["buttons"]]
        rows = _menu_rows(reply["text"].split("\n")[0], choices)
        rows += [{"type": 1, "components": [button(b) for b in row[:MAX_BUTTONS]]} for row in link_rows if row]
    else:
        rows = [{"type": 1, "components": [button(b) for b in row[:MAX_BUTTONS]]} for row in reply["buttons"] if row]
    return {"content": reply["text"][:TEXT_LIMIT], "flags": EPHEMERAL, "components": rows[:5]}


# ---------- 디스코드로 보내기 ----------

def _webhook(token):
    return f"{API}/webhooks/{config.DISCORD_APPLICATION_ID}/{token}"


def call(method, url, payload):
    """디스코드 호출. 실패해도 서버가 멈추지 않게 로그(상태 코드 또는 오류 종류)만 남긴다."""
    try:
        r = httpx.request(method, url, json=payload, timeout=15,
                          headers={"User-Agent": "DiscordBot (https://github.com, 1.0)"})
        if r.status_code >= 300:
            logger.warning("discord %s %s", method, r.status_code)
    except httpx.HTTPError as e:
        logger.warning("discord %s %s", method, type(e).__name__)


def send(token, replies, edit_first):
    """첫 말은 "생각 중" 메시지를 고쳐서 채우고(edit_first), 나머지는 이어서 보낸다."""
    for i, reply in enumerate(replies):
        message = to_message(reply)
        if i == 0 and edit_first:
            call("PATCH", f"{_webhook(token)}/messages/@original", message)
        else:
            call("POST", _webhook(token), message)


def _user_id(interaction):
    return (interaction.get("member", {}).get("user") or interaction.get("user") or {}).get("id")


def process(interaction):
    """뒤에서 실행: 명령이나 버튼·메뉴 누름을 처리하고 답을 보낸다."""
    token, user_id = interaction["token"], _user_id(interaction)
    data = interaction.get("data", {})
    if interaction["type"] == COMMAND:
        question = next((o.get("value") for o in data.get("options", []) if o.get("name") == QUESTION_OPTION), "")
        replies = messenger.on_text(PLATFORM, user_id, str(question or ""))
        send(token, replies, edit_first=True)
        return
    # 버튼·메뉴: 누른 메시지의 버튼은 지우고(예전 버튼을 다시 누르는 일을 줄인다), 답은 새 메시지로 보낸다.
    call("PATCH", f"{_webhook(token)}/messages/@original", {"components": []})
    choice = (data.get("values") or [data.get("custom_id", "")])[0]
    send(token, messenger.on_button(PLATFORM, user_id, choice), edit_first=False)


def run(interaction):
    try:
        process(interaction)
    except Exception as e:   # 뒤에서 난 오류. 글 내용은 남기지 않는다.
        logger.error("discord process %s", type(e).__name__)


@router.post("/interactions")
async def interactions(request: Request, background: BackgroundTasks):
    if not (config.DISCORD_APPLICATION_ID and config.DISCORD_PUBLIC_KEY):
        raise HTTPException(404, "찾으시는 화면이 없어요.")
    body = await request.body()
    if not verify(body, request.headers.get("x-signature-ed25519", ""),
                  request.headers.get("x-signature-timestamp", "")):
        raise HTTPException(401, "허용되지 않은 요청이에요.")
    try:
        interaction = json.loads(body)
    except ValueError:
        raise HTTPException(400, "잘못된 요청이에요.")

    kind = interaction.get("type")
    logger.info("discord interaction %s", kind)
    if kind == PING:
        return {"type": PONG}
    if kind == COMMAND:
        name = interaction.get("data", {}).get("name")
        user_id = _user_id(interaction)
        if name == RESET_COMMAND:   # AI를 쓰지 않으므로 바로 답한다
            reply = messenger.on_button(PLATFORM, user_id, "r")[0]
            return {"type": MESSAGE, "data": to_message(reply)}
        if name != ASK_COMMAND:     # /안내 (그 밖의 이름도 인사로)
            return {"type": MESSAGE, "data": to_message(messenger.start(PLATFORM, user_id, HOW_TO_ASK)[0])}
        background.add_task(run, interaction)
        return {"type": DEFERRED_MESSAGE, "data": {"flags": EPHEMERAL}}
    if kind == COMPONENT:
        background.add_task(run, interaction)
        return {"type": DEFERRED_UPDATE}
    return {"type": PONG}

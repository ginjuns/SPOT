"""POST /api/telegram/webhook — 텔레그램 봇 (웹훅 방식).

텔레그램이 사용자의 글·버튼 누름을 이 주소로 보내 준다. 받자마자 200으로 답하고,
실제 처리(검색·AI)는 뒤에서 한 뒤 sendMessage 로 답을 보낸다.
대화 글은 저장하지 않고, 로그에도 남기지 않는다. 처리는 모두 services/messenger.py 가 한다.
"""
import collections
import hmac
import logging
import threading

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app import config
from app.services import messenger

router = APIRouter(prefix="/api/telegram")
logger = logging.getLogger("benefit")
# httpx 는 요청 주소를 INFO 로그로 남기는데, 텔레그램 주소에는 봇 토큰이 들어 있다.
logging.getLogger("httpx").setLevel(logging.WARNING)

PLATFORM = "telegram"
API = "https://api.telegram.org/bot{token}/{method}"
TEXT_LIMIT = 4096                 # 텔레그램 메시지 한 개의 최대 글자 수
ONLY_TEXT = "글로 적어 주세요. 사진이나 소리는 아직 알아듣지 못해요."

# 잠든 서버가 깨어날 때 텔레그램이 같은 것을 다시 보낼 수 있다. 최근 번호만 기억해 두 번 답하지 않는다.
_seen = collections.deque(maxlen=500)
_seen_lock = threading.Lock()


def _first_time(update_id):
    with _seen_lock:
        if update_id in _seen:
            return False
        _seen.append(update_id)
        return True


def call(method, payload):
    """텔레그램 Bot API 호출. 실패해도 서버가 멈추지 않게 로그(방법 이름과 오류 종류)만 남긴다."""
    try:
        r = httpx.post(API.format(token=config.TELEGRAM_BOT_TOKEN, method=method), json=payload, timeout=15)
        if r.status_code != 200:
            logger.warning("telegram %s %s", method, r.status_code)
    except httpx.HTTPError as e:
        logger.warning("telegram %s %s", method, type(e).__name__)


def to_keyboard(buttons):
    """공통 버튼 목록 → 텔레그램 인라인 키보드."""
    rows = [
        [{"text": b["label"], "url": b["url"]} if "url" in b else {"text": b["label"], "callback_data": b["data"]}
         for b in row]
        for row in buttons
    ]
    return {"inline_keyboard": rows}


def send(chat_id, replies):
    for reply in replies:
        payload = {"chat_id": chat_id, "text": reply["text"][:TEXT_LIMIT], "disable_web_page_preview": True}
        if reply["buttons"]:
            payload["reply_markup"] = to_keyboard(reply["buttons"])
        call("sendMessage", payload)


def process(update):
    """텔레그램 업데이트 하나 처리 (뒤에서 실행)."""
    if "callback_query" in update:
        query = update["callback_query"]
        call("answerCallbackQuery", {"callback_query_id": query["id"]})   # 버튼의 "기다리는 중" 표시를 끈다
        message = query.get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        if chat_id is None or message.get("chat", {}).get("type") != "private":
            return
        # 누른 버튼 줄은 지운다 (예전 버튼을 다시 누르는 일을 줄인다)
        call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message.get("message_id"),
                                        "reply_markup": {"inline_keyboard": []}})
        call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        send(chat_id, messenger.on_button(PLATFORM, query["from"]["id"], query.get("data", "")))
        return

    message = update.get("message")
    if not message or message.get("chat", {}).get("type") != "private":
        return   # 개인 대화만 받는다 (단체방에서는 답하지 않는다)
    chat_id = message["chat"]["id"]
    user_id = message.get("from", {}).get("id", chat_id)
    text = (message.get("text") or "").strip()
    if not text:
        send(chat_id, [{"text": ONLY_TEXT, "buttons": []}])
        return
    command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    if command in ("/start", "/help"):
        replies = messenger.start(PLATFORM, user_id)
    elif command == "/reset":
        replies = messenger.on_button(PLATFORM, user_id, "r")
    else:
        call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        replies = messenger.on_text(PLATFORM, user_id, text)
    send(chat_id, replies)


def run(update):
    try:
        process(update)
    except Exception as e:   # 뒤에서 난 오류. 글 내용은 남기지 않는다.
        logger.error("telegram process %s", type(e).__name__)


@router.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(404, "찾으시는 화면이 없어요.")
    sent = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not hmac.compare_digest(sent.encode(), config.TELEGRAM_WEBHOOK_SECRET.encode()):
        raise HTTPException(403, "허용되지 않은 요청이에요.")
    try:
        update = await request.json()
    except ValueError:
        raise HTTPException(400, "잘못된 요청이에요.")
    update_id = update.get("update_id") if isinstance(update, dict) else None
    if update_id is not None and _first_time(update_id):
        background.add_task(run, update)
    logger.info("telegram update")
    return {"ok": True}

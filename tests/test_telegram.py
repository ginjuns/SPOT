"""텔레그램 웹훅 테스트. 텔레그램 API 호출과 messenger 는 가짜로 바꾼다."""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.routers import telegram
from app.services import messenger

client = TestClient(app)
SECRET = "test-secret"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


def text_update(update_id, text, chat_type="private"):
    return {"update_id": update_id,
            "message": {"message_id": 5, "from": {"id": 42}, "chat": {"id": 42, "type": chat_type}, "text": text}}


@pytest.fixture
def fake(monkeypatch):
    calls = {"api": [], "messenger": []}
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(telegram, "call", lambda method, payload: calls["api"].append((method, payload)))
    reply = [{"text": "답", "buttons": [[{"label": "75세 이상", "data": "a:75plus"}],
                                       [{"label": "자세히 보기", "url": "https://spot.example/p"}]]}]
    for name in ("start", "on_text", "on_button"):
        monkeypatch.setattr(messenger, name,
                            lambda *args, _n=name, **kw: calls["messenger"].append((_n, args)) or reply)
    telegram._seen.clear()
    yield calls


def sent(calls):
    return [p for m, p in calls["api"] if m == "sendMessage"]


def test_404_when_not_configured(fake, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    assert client.post("/api/telegram/webhook", json=text_update(1, "hi"), headers=HEADERS).status_code == 404


def test_403_when_secret_is_wrong(fake):
    r = client.post("/api/telegram/webhook", json=text_update(1, "병원비"),
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    assert r.status_code == 403 and fake["messenger"] == []
    assert client.post("/api/telegram/webhook", json=text_update(1, "병원비")).status_code == 403


def test_text_becomes_question_and_reply_is_sent(fake):
    r = client.post("/api/telegram/webhook", json=text_update(1, "병원비 지원이 있나요?"), headers=HEADERS)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert fake["messenger"] == [("on_text", ("telegram", 42, "병원비 지원이 있나요?"))]
    (payload,) = sent(fake)
    assert payload["chat_id"] == 42 and payload["text"] == "답"
    assert payload["reply_markup"] == {"inline_keyboard": [
        [{"text": "75세 이상", "callback_data": "a:75plus"}],
        [{"text": "자세히 보기", "url": "https://spot.example/p"}]]}


def test_commands(fake):
    client.post("/api/telegram/webhook", json=text_update(1, "/start"), headers=HEADERS)
    client.post("/api/telegram/webhook", json=text_update(2, "/reset@spot_benefit_bot"), headers=HEADERS)
    assert fake["messenger"] == [("start", ("telegram", 42)), ("on_button", ("telegram", 42, "r"))]


def test_button_press(fake):
    update = {"update_id": 3, "callback_query": {
        "id": "cb1", "from": {"id": 42}, "data": "a:75plus",
        "message": {"message_id": 9, "chat": {"id": 42, "type": "private"}}}}
    client.post("/api/telegram/webhook", json=update, headers=HEADERS)
    methods = [m for m, _ in fake["api"]]
    assert methods[0] == "answerCallbackQuery" and "editMessageReplyMarkup" in methods
    assert fake["messenger"] == [("on_button", ("telegram", 42, "a:75plus"))]
    assert len(sent(fake)) == 1


def test_same_update_is_handled_once(fake):
    for _ in range(2):
        assert client.post("/api/telegram/webhook", json=text_update(7, "병원비"), headers=HEADERS).status_code == 200
    assert len(fake["messenger"]) == 1


def test_group_chats_are_ignored(fake):
    client.post("/api/telegram/webhook", json=text_update(1, "병원비", chat_type="group"), headers=HEADERS)
    assert fake["messenger"] == [] and fake["api"] == []


def test_non_text_message_gets_hint(fake):
    update = text_update(1, "")
    del update["message"]["text"]
    update["message"]["photo"] = [{"file_id": "x"}]
    client.post("/api/telegram/webhook", json=update, headers=HEADERS)
    assert fake["messenger"] == [] and sent(fake)[0]["text"] == telegram.ONLY_TEXT


def test_error_in_background_does_not_break(fake, monkeypatch):
    monkeypatch.setattr(messenger, "on_text", lambda *a, **k: 1 / 0)
    r = client.post("/api/telegram/webhook", json=text_update(1, "병원비"), headers=HEADERS)
    assert r.status_code == 200

"""네이버 톡톡 웹훅 테스트. 보내기 API 호출과 messenger 는 가짜로 바꾼다."""
import logging

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.routers import navertalk
from app.services import messenger

client = TestClient(app)
SECRET = "test-secret"
URL = f"/api/navertalk/webhook/{SECRET}"


def text_event(text, code=None):
    content = {"text": text, "inputType": "button" if code else "typing"}
    if code:
        content["code"] = code
    return {"event": "send", "user": "u-42", "textContent": content}


@pytest.fixture
def fake(monkeypatch):
    calls = {"api": [], "messenger": []}
    monkeypatch.setattr(config, "NAVERTALK_AUTH_KEY", "auth-key")
    monkeypatch.setattr(config, "NAVERTALK_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(navertalk, "call", lambda payload: calls["api"].append(payload))
    reply = [{"text": "답", "buttons": [[{"label": "75세 이상", "data": "a:75plus"}],
                                       [{"label": "자세히 보기", "url": "https://spot.example/p"}]]}]
    for name in ("start", "on_text", "on_button"):
        monkeypatch.setattr(messenger, name,
                            lambda *args, _n=name, **kw: calls["messenger"].append((_n, args)) or reply)
    yield calls


def sent(calls):
    return [p for p in calls["api"] if p["event"] == "send"]


def test_404_when_not_configured(fake, monkeypatch):
    monkeypatch.setattr(config, "NAVERTALK_AUTH_KEY", "")
    assert client.post(URL, json=text_event("hi")).status_code == 404


def test_403_when_secret_is_wrong(fake):
    r = client.post("/api/navertalk/webhook/wrong", json=text_event("병원비"))
    assert r.status_code == 403 and fake["messenger"] == []


def test_text_becomes_question_and_reply_is_sent(fake):
    r = client.post(URL, json=text_event("병원비 지원이 있나요?"))
    assert r.status_code == 200 and r.content == b""
    assert fake["messenger"] == [("on_text", ("navertalk", "u-42", "병원비 지원이 있나요?"))]
    assert fake["api"][0] == {"event": "action", "user": "u-42", "options": {"action": "typingOn"}}
    (payload,) = sent(fake)
    assert payload["user"] == "u-42"
    assert payload["compositeContent"]["compositeList"] == [{"description": "답", "buttonList": [
        {"type": "TEXT", "data": {"title": "75세 이상", "code": "a:75plus"}},
        {"type": "LINK", "data": {"title": "자세히 보기", "url": "https://spot.example/p",
                                  "mobileUrl": "https://spot.example/p"}}]}]


def test_button_press(fake):
    client.post(URL, json=text_event("75세 이상", code="a:75plus"))
    assert fake["messenger"] == [("on_button", ("navertalk", "u-42", "a:75plus"))]


def test_open_greets_and_words(fake):
    client.post(URL, json={"event": "open", "user": "u-42", "options": {"inflow": "none"}})
    client.post(URL, json=text_event("처음부터"))
    client.post(URL, json=text_event("안내"))
    assert fake["messenger"] == [("start", ("navertalk", "u-42", navertalk.HOW_TO_ASK)),
                                 ("on_button", ("navertalk", "u-42", "r")),
                                 ("start", ("navertalk", "u-42", navertalk.HOW_TO_ASK))]


def test_other_events_are_ignored(fake):
    for event in ({"event": "leave", "user": "u-42"}, {"event": "friend", "user": "u-42", "options": {"set": "on"}},
                  {"event": "echo", "echoedEvent": "send", "user": "u-42", "textContent": {"text": "답"}}):
        assert client.post(URL, json=event).status_code == 200
    assert fake["messenger"] == [] and fake["api"] == []


def test_image_gets_hint(fake):
    client.post(URL, json={"event": "send", "user": "u-42", "imageContent": {"imageUrl": "https://x/y.png"}})
    assert fake["messenger"] == [] and sent(fake)[0]["textContent"]["text"] == navertalk.ONLY_TEXT


def test_error_in_background_does_not_break(fake, monkeypatch):
    monkeypatch.setattr(messenger, "on_text", lambda *a, **k: 1 / 0)
    assert client.post(URL, json=text_event("병원비")).status_code == 200


def test_many_buttons_are_split_and_long_labels_listed():
    buttons = [[{"label": f"곳{i}", "data": f"s:{i}"}] for i in range(17)]
    events = navertalk.to_events("u", {"text": "시·도를 골라 주세요.", "buttons": buttons})
    lists = [e["compositeContent"]["compositeList"][0] for e in events]
    assert [len(c["buttonList"]) for c in lists] == [10, 7]
    assert lists[1]["description"] == navertalk.MORE_TEXT

    long = "허리가 아파서 병원에 가려는데 지원받을 수 있는 게 있나요?"
    (event,) = navertalk.to_events("u", {"text": "예시:", "buttons": [[{"label": long, "data": "e:0"}]]})
    card = event["compositeContent"]["compositeList"][0]
    assert long in card["description"]
    assert len(card["buttonList"][0]["data"]["title"]) <= navertalk.LABEL_LIMIT


def test_real_messenger_replies_fit_limits():
    """실제 공통 처리의 인사·시·도 묻기가 네이버 톡톡 제한 안에 들어가는지."""
    messenger.reset()
    for reply in messenger.start("navertalk", "u", navertalk.HOW_TO_ASK) + [messenger._ask_sido()]:
        for event in navertalk.to_events("u", reply):
            for card in event.get("compositeContent", {}).get("compositeList", []):
                assert len(card["description"]) <= navertalk.DESCRIPTION_LIMIT
                assert len(card["buttonList"]) <= navertalk.BUTTONS_PER_MESSAGE
                assert all(len(b["data"]["title"]) <= navertalk.LABEL_LIMIT for b in card["buttonList"])


def test_secret_is_hidden_in_access_log(monkeypatch):
    monkeypatch.setattr(config, "NAVERTALK_WEBHOOK_SECRET", SECRET)
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4", "POST", URL, "1.1", 200), None)
    navertalk._HideSecret().filter(record)
    assert SECRET not in record.getMessage()

"""카카오 스킬 서버 테스트. 콜백 보내기와 messenger 는 필요할 때 가짜로 바꾼다."""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.routers import kakao
from app.services import messenger

client = TestClient(app)
SECRET = "test-secret"
HEADERS = {"X-Spot-Secret": SECRET}


def body(text, user="u-42", callback=None, extra=None):
    request = {"utterance": text, "user": {"id": user, "type": "botUserKey"}}
    if callback:
        request["callbackUrl"] = callback
    return {"userRequest": request, "action": {"params": {}, "clientExtra": extra or {}}}


@pytest.fixture
def fake(monkeypatch):
    calls = {"messenger": [], "callback": []}
    monkeypatch.setattr(config, "KAKAO_SKILL_SECRET", SECRET)
    monkeypatch.setattr(kakao, "post_callback", lambda url, response: calls["callback"].append((url, response)))
    reply = [{"text": "답", "buttons": [[{"label": "75세 이상", "data": "a:75plus"}]]}]
    for name in ("start", "on_text", "on_button"):
        monkeypatch.setattr(messenger, name,
                            lambda *args, _n=name, **kw: calls["messenger"].append((_n, args)) or reply)
    kakao._buttons.clear()
    yield calls


def test_404_and_403(fake, monkeypatch):
    assert client.post("/api/kakao/skill", json=body("hi")).status_code == 403
    assert client.post("/api/kakao/skill", json=body("hi"), headers={"X-Spot-Secret": "x"}).status_code == 403
    monkeypatch.setattr(config, "KAKAO_SKILL_SECRET", "")
    assert client.post("/api/kakao/skill", json=body("hi"), headers=HEADERS).status_code == 404
    assert fake["messenger"] == []


def test_without_callback_answers_directly(fake):
    r = client.post("/api/kakao/skill", json=body("병원비 지원이 있나요?"), headers=HEADERS)
    assert r.status_code == 200
    assert fake["messenger"] == [("on_text", ("kakao", "u-42", "병원비 지원이 있나요?"))]
    data = r.json()
    assert data["version"] == "2.0"
    assert data["template"]["outputs"] == [{"simpleText": {"text": "답"}}]
    assert data["template"]["quickReplies"] == [
        {"label": "75세 이상", "action": "message", "messageText": "75세 이상", "extra": {"code": "a:75plus"}}]


def test_with_callback_waits_then_sends_once(fake):
    url = "https://bot-api.kakao.com/callback/abc"
    r = client.post("/api/kakao/skill", json=body("병원비", callback=url), headers=HEADERS)
    assert r.json() == {"version": "2.0", "useCallback": True, "data": {"text": kakao.WAIT_TEXT}}
    (sent_url, response), = fake["callback"]
    assert sent_url == url and response["template"]["outputs"] == [{"simpleText": {"text": "답"}}]


def test_button_press_by_extra_or_by_label(fake):
    client.post("/api/kakao/skill", json=body("병원비"), headers=HEADERS)          # 버튼 "75세 이상"을 보여 줌
    client.post("/api/kakao/skill", json=body("75세 이상"), headers=HEADERS)      # clientExtra 없이 이름만 옴
    client.post("/api/kakao/skill", json=body("아무 말", extra={"code": "s:11"}), headers=HEADERS)
    assert fake["messenger"][1:] == [("on_button", ("kakao", "u-42", "a:75plus")),
                                     ("on_button", ("kakao", "u-42", "s:11"))]


def test_welcome_and_words(fake):
    for text in ("", "처음부터", "안내"):
        client.post("/api/kakao/skill", json=body(text), headers=HEADERS)
    names = [(n, a[2] if n == "on_button" else None) for n, a in fake["messenger"]]
    assert names == [("start", None), ("on_button", "r"), ("start", None)]


def test_error_still_answers(fake, monkeypatch):
    monkeypatch.setattr(messenger, "on_text", lambda *a, **k: 1 / 0)
    r = client.post("/api/kakao/skill", json=body("병원비"), headers=HEADERS)
    assert r.json()["template"]["outputs"] == [{"simpleText": {"text": kakao.ERROR_TEXT}}]


# ---------- 실제 공통 처리의 말이 카카오 제한 안에 드는지 ----------

def check_limits(response):
    template = response["template"]
    assert 1 <= len(template["outputs"]) <= kakao.OUTPUT_LIMIT
    assert len(template.get("quickReplies", [])) <= kakao.QUICK_LIMIT
    buttons = list(template.get("quickReplies", []))
    for o in template["outputs"]:
        if "simpleText" in o:
            assert len(o["simpleText"]["text"]) <= kakao.TEXT_LIMIT
        cards = o["carousel"]["items"] if "carousel" in o else [o["textCard"]] if "textCard" in o else []
        assert len(cards) <= kakao.CAROUSEL_LIMIT
        for card in cards:
            assert len(card.get("title", "")) <= kakao.TITLE_LIMIT
            limit = kakao.CAROUSEL_TEXT_LIMIT if "carousel" in o else kakao.CARD_TEXT_LIMIT
            assert len(card.get("description", "")) <= limit
            assert len(card["buttons"]) <= kakao.CARD_BUTTONS
            buttons += card["buttons"]
    assert all(len(b["label"]) <= kakao.LABEL_LIMIT for b in buttons)
    return buttons


def test_real_asks_fit_and_keep_every_choice():
    messenger.reset()
    for reply in (messenger.start("kakao", "u", kakao.HOW_TO_ASK)[0], messenger._ask_age(), messenger._ask_sido(),
                  messenger._ask_sigungu(max(messenger.SIGUNGU, key=lambda c: len(messenger.SIGUNGU[c])))):
        buttons = check_limits(kakao.to_response([{"text": "앞 안내", "buttons": []}, reply]))
        codes = sorted(b["extra"]["code"] for b in buttons)
        assert codes == sorted(b["data"] for row in reply["buttons"] for b in row)


def test_policy_results_become_one_carousel(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://spot.example")
    policy = {"id": "SVC1", "name": "어르신 병원비 지원", "agency": "보건복지부", "one_line": "병원비 일부를 돌려줘요" * 10,
              "url": "https://www.gov.kr/x", "collected_at": "2026-11-14"}
    replies = messenger._result({"text": "찾아봤어요.", "policies": [policy] * 5})
    response = kakao.to_response(replies)
    check_limits(response)
    outputs = response["template"]["outputs"]
    assert [list(o) for o in outputs] == [["simpleText"], ["carousel"], ["simpleText"]]
    assert len(outputs[1]["carousel"]["items"]) == 5
    assert outputs[1]["carousel"]["items"][0]["title"] == "1. 어르신 병원비 지원"
    assert outputs[2]["simpleText"]["text"] == messenger.CONFIRM_TEXT

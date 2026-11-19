"""디스코드 상호작용 테스트. 테스트용 서명 키를 새로 만들어 서명하고, 디스코드 호출과 messenger 는 가짜로 바꾼다."""
import json

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from app import config
from app.main import app
from app.routers import discord
from app.services import messenger

client = TestClient(app)
KEY = SigningKey.generate()


def post(payload, sign_with=KEY, timestamp="1700000000"):
    body = json.dumps(payload).encode()
    signature = sign_with.sign(timestamp.encode() + body).signature.hex()
    return client.post("/api/discord/interactions", content=body, headers={
        "X-Signature-Ed25519": signature, "X-Signature-Timestamp": timestamp, "Content-Type": "application/json"})


def command(name, question=None):
    data = {"name": name}
    if question is not None:
        data["options"] = [{"name": discord.QUESTION_OPTION, "type": 3, "value": question}]
    return {"type": 2, "token": "tok", "member": {"user": {"id": "77"}}, "data": data}


@pytest.fixture
def fake(monkeypatch):
    calls = {"api": [], "messenger": []}
    monkeypatch.setattr(config, "DISCORD_APPLICATION_ID", "123")
    monkeypatch.setattr(config, "DISCORD_PUBLIC_KEY", KEY.verify_key.encode().hex())
    monkeypatch.setattr(discord, "call", lambda method, url, payload: calls["api"].append((method, url, payload)))
    calls["reply"] = [{"text": "답", "buttons": []}]
    for name in ("start", "on_text", "on_button"):
        monkeypatch.setattr(messenger, name,
                            lambda *args, _n=name, **kw: calls["messenger"].append((_n, args)) or calls["reply"])
    yield calls


def test_404_when_not_configured(fake, monkeypatch):
    monkeypatch.setattr(config, "DISCORD_PUBLIC_KEY", "")
    assert post({"type": 1}).status_code == 404


def test_401_when_signature_is_wrong(fake):
    assert post({"type": 1}, sign_with=SigningKey.generate()).status_code == 401
    r = client.post("/api/discord/interactions", content=b'{"type":1}', headers={
        "X-Signature-Ed25519": "zz", "X-Signature-Timestamp": "1"})
    assert r.status_code == 401
    # 서명한 뒤 본문을 바꾸면 거부한다
    body = b'{"type": 1}'
    sig = KEY.sign(b"1" + body).signature.hex()
    r = client.post("/api/discord/interactions", content=b'{"type": 2}', headers={
        "X-Signature-Ed25519": sig, "X-Signature-Timestamp": "1"})
    assert r.status_code == 401


def test_ping(fake):
    assert post({"type": 1}).json() == {"type": 1}


def test_ask_command_defers_then_fills_answer(fake):
    fake["reply"] = [{"text": "찾았어요.", "buttons": []},
                     {"text": "1. 정책", "buttons": [[{"label": "자세히 보기", "url": "https://spot.example/p"}]]}]
    r = post(command(discord.ASK_COMMAND, "병원비 지원이 있나요?")).json()
    assert r == {"type": 5, "data": {"flags": 64}}   # 먼저 "생각 중", 본인에게만
    assert fake["messenger"] == [("on_text", ("discord", "77", "병원비 지원이 있나요?"))]
    (m1, u1, p1), (m2, u2, p2) = fake["api"]
    assert m1 == "PATCH" and u1.endswith("/webhooks/123/tok/messages/@original") and p1["content"] == "찾았어요."
    assert m2 == "POST" and u2.endswith("/webhooks/123/tok") and p2["flags"] == 64
    assert p2["components"] == [{"type": 1, "components": [
        {"type": 2, "style": 5, "label": "자세히 보기", "url": "https://spot.example/p"}]}]


def test_reset_and_help_answer_at_once(fake):
    r = post(command(discord.RESET_COMMAND)).json()
    assert r["type"] == 4 and fake["messenger"][-1] == ("on_button", ("discord", "77", "r"))
    r = post(command(discord.HELP_COMMAND)).json()
    assert r["type"] == 4 and fake["messenger"][-1][0] == "start"
    assert fake["api"] == []


def test_menu_choice(fake):
    r = post({"type": 3, "token": "tok", "user": {"id": "77"},
              "data": {"component_type": 3, "custom_id": "menu:0", "values": ["a:75plus"]}}).json()
    assert r == {"type": 6}
    assert fake["messenger"] == [("on_button", ("discord", "77", "a:75plus"))]
    assert fake["api"][0][0] == "PATCH" and fake["api"][0][2] == {"components": []}   # 누른 메뉴는 지운다
    assert fake["api"][1][0] == "POST"


def test_button_press(fake):
    post({"type": 3, "token": "tok", "user": {"id": "77"}, "data": {"component_type": 2, "custom_id": "e:1"}})
    assert fake["messenger"] == [("on_button", ("discord", "77", "e:1"))]


def test_few_choices_become_buttons():
    m = discord.to_message({"text": "인사", "buttons": [[{"label": "예시1", "data": "e:0"}], [{"label": "예시2", "data": "e:1"}]]})
    assert [row["components"][0]["custom_id"] for row in m["components"]] == ["e:0", "e:1"]


def test_many_choices_become_menus_split_by_25():
    """시·군·구가 25개를 넘는 시·도는 메뉴를 둘로 나눈다 (디스코드 메뉴 한도 25개)."""
    sido = max(messenger.SIGUNGU, key=lambda c: len(messenger.SIGUNGU[c]))
    m = discord.to_message(messenger._ask_sigungu(sido))
    menus = [row["components"][0] for row in m["components"]]
    assert len(messenger.SIGUNGU[sido]) + 1 > 25 and len(menus) == 2
    assert all(c["type"] == 3 and len(c["options"]) <= 25 for c in menus)
    values = [o["value"] for c in menus for o in c["options"]]
    assert values[-1] == "g:-" and len(values) == len(messenger.SIGUNGU[sido]) + 1
    assert len({c["custom_id"] for c in menus}) == 2


def test_all_ask_steps_fit_discord_limits():
    replies = [messenger._ask_age(), messenger._ask_sido()] + [messenger._ask_sigungu(c) for c in messenger.SIGUNGU]
    replies += messenger.start("discord", 1)
    for reply in replies:
        m = discord.to_message(reply)
        assert len(m["components"]) <= 5 and len(m["content"]) <= 2000
        for row in m["components"]:
            assert len(row["components"]) <= 5
            for c in row["components"]:
                assert len(c.get("label", "")) <= 80


def test_greeting_explains_how_to_ask():
    text = messenger.start("discord", 1, discord.HOW_TO_ASK)[0]["text"]
    assert "/물어보기" in text and text.index("/물어보기") < text.index("이렇게 물어보셔도")


def test_error_in_background_does_not_break(fake, monkeypatch):
    monkeypatch.setattr(messenger, "on_text", lambda *a, **k: 1 / 0)
    assert post(command(discord.ASK_COMMAND, "병원비")).status_code == 200

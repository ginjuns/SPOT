"""메신저 공통 처리 테스트. chat_core.handle 은 가짜로 바꿔서 DB·Groq 없이 돈다."""
import datetime

import pytest

from app import config
from app.services import chat_core, messenger

CARD = {
    "id": "SVC1", "name": "재난적 의료비 지원", "agency": "보건복지부", "one_line": "AI가 쓴 한 줄 요약",
    "has_income_rule": True, "url": "https://example.com/1", "apply_period": "매년 1월",
    "collected_at": datetime.date(2026, 11, 13),
}
SEARCH_TEXT = "병원비 의료비 지원"


@pytest.fixture
def fake(monkeypatch):
    calls = {"reqs": [], "responses": []}

    def fake_handle(req, key):
        calls["reqs"].append((req, key))
        if calls["responses"]:
            return calls["responses"].pop(0)
        cond = {**req.conditions.model_dump(), "search_text": req.conditions.search_text or SEARCH_TEXT}
        missing = [n for n, k in (("age_group", "age_group"), ("region", "region_code")) if not cond.get(k)]
        if missing and not req.asked:
            return {"type": "ask", "text": "몇 가지만 여쭤볼게요.", "ask": missing, "conditions": cond}
        return {"type": "result", "text": "찾았어요.", "policies": [CARD], "conditions": cond}

    monkeypatch.setattr(chat_core, "handle", fake_handle)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://spot.example")
    messenger.reset()
    yield calls
    messenger.reset()


def datas(reply):
    return [b.get("data") for row in reply["buttons"] for b in row]


def test_start_greets_with_privacy_notice_and_examples(fake):
    replies = messenger.start("telegram", 1)
    assert "전화번호는 적지 않으셔도 돼요" in replies[0]["text"]
    assert datas(replies[0]) == ["e:0", "e:1", "e:2"]


def test_full_ask_flow_age_then_sido_then_sigungu(fake):
    replies = messenger.on_text("telegram", 1, "병원비 지원이 있나요?")
    assert replies[0]["text"] == "몇 가지만 여쭤볼게요."
    assert datas(replies[1])[:6] == ["a:u19", "a:19_34", "a:35_49", "a:50_64", "a:65_74", "a:75plus"]
    assert datas(replies[1])[-1] == "a:-"

    sido_ask = messenger.on_button("telegram", 1, "a:75plus")[0]
    assert "s:11" in datas(sido_ask) and datas(sido_ask)[-1] == "s:-"

    sigungu_ask = messenger.on_button("telegram", 1, "s:11")[0]
    assert "강원특별자치도" in sigungu_ask["text"] and "g:11101" in datas(sigungu_ask)

    replies = messenger.on_button("telegram", 1, "g:11101")
    req, _ = fake["reqs"][-1]
    # 다 고르면 질문 글 없이(분석 건너뛰기), 되물었음 표시와 함께 다시 부른다
    assert req.message == "" and req.asked is True and req.history == []
    assert req.conditions.age_group == "75plus" and req.conditions.region_code == "11101"
    assert req.conditions.search_text == SEARCH_TEXT
    assert replies[0]["text"] == "찾았어요." and replies[1]["text"].startswith("1. 재난적 의료비 지원")


def test_skip_everything_searches_without_conditions(fake):
    messenger.on_text("telegram", 1, "병원비")
    messenger.on_button("telegram", 1, "a:-")
    messenger.on_button("telegram", 1, "s:-")
    req, _ = fake["reqs"][-1]
    assert req.asked is True and req.conditions.age_group is None and req.conditions.region_code is None


def test_skipping_sigungu_uses_sido(fake):
    messenger.on_text("telegram", 1, "병원비")
    messenger.on_button("telegram", 1, "a:-")
    messenger.on_button("telegram", 1, "s:11")
    messenger.on_button("telegram", 1, "g:-")
    assert fake["reqs"][-1][0].conditions.region_code == "11"


def test_asks_only_missing_items(fake):
    fake["responses"].append({"type": "ask", "text": "지역만요.", "ask": ["region"],
                              "conditions": {"age_group": "65_74", "search_text": SEARCH_TEXT}})
    replies = messenger.on_text("telegram", 1, "70살인데 병원비")
    assert datas(replies[1])[0].startswith("s:")
    assert messenger.on_button("telegram", 1, "a:75plus")[0]["text"] == messenger.EXPIRED_TEXT


def test_conditions_carry_over_to_next_question(fake):
    messenger.on_text("telegram", 1, "병원비")
    messenger.on_button("telegram", 1, "a:75plus")
    messenger.on_button("telegram", 1, "s:11")
    messenger.on_button("telegram", 1, "g:11101")
    messenger.on_text("telegram", 1, "난방비는요?")
    req, _ = fake["reqs"][-1]
    assert req.message == "난방비는요?" and req.asked is True and req.conditions.region_code == "11101"


def test_conditions_expire_after_30_minutes(fake):
    messenger.on_text("telegram", 1, "병원비", now=1000)
    assert messenger.on_button("telegram", 1, "a:75plus", now=1000 + messenger.STATE_TTL + 1)[0]["text"] \
        == messenger.EXPIRED_TEXT
    messenger.on_text("telegram", 1, "병원비", now=1000 + messenger.STATE_TTL + 2)
    assert fake["reqs"][-1][0].asked is False


def test_reset_and_start_forget_conditions(fake):
    messenger.on_text("telegram", 1, "병원비")
    assert messenger.on_button("telegram", 1, "r")[0]["text"] == messenger.RESET_TEXT
    assert messenger.on_button("telegram", 1, "a:75plus")[0]["text"] == messenger.EXPIRED_TEXT
    messenger.on_text("telegram", 1, "병원비")
    messenger.start("telegram", 1)
    assert messenger.on_button("telegram", 1, "a:75plus")[0]["text"] == messenger.EXPIRED_TEXT


def test_users_and_platforms_are_separate(fake):
    messenger.on_text("telegram", 1, "병원비")
    assert messenger.on_button("telegram", 2, "a:75plus")[0]["text"] == messenger.EXPIRED_TEXT
    assert messenger.on_button("discord", 1, "a:75plus")[0]["text"] == messenger.EXPIRED_TEXT
    assert messenger.user_key("telegram", 1) != messenger.user_key("discord", 1)
    assert len(messenger.user_key("telegram", 1)) == 16


def test_bad_button_values_are_ignored(fake):
    messenger.on_text("telegram", 1, "병원비")
    for data in ["a:100살", "s:99", "g:11101", "zzz", "", "e:9"]:
        assert messenger.on_button("telegram", 1, data)[0]["text"] == messenger.EXPIRED_TEXT
    assert messenger.on_button("telegram", 1, "a:75plus")[0]["text"] == messenger.ASK_SIDO_TEXT


def test_example_button_asks_that_question(fake):
    messenger.on_button("telegram", 1, "e:1")
    assert fake["reqs"][-1][0].message == messenger.EXAMPLES[1]


def test_policy_card_text_and_links(fake):
    replies = messenger._result({"text": "찾았어요.", "policies": [CARD, {**CARD, "id": "SVC2", "url": None}]})
    first, second = replies[1], replies[2]
    assert first["text"] == ("1. 재난적 의료비 지원\n보건복지부\nAI가 쓴 한 줄 요약\n※ 소득 기준 있음\n"
                             "신청 기간: 매년 1월\n자료 기준일: 2026-11-13")
    assert first["buttons"] == [[{"label": "자세히 보기", "url": "https://spot.example/policy.html?id=SVC1"},
                                 {"label": "원문 보기", "url": "https://example.com/1"}]]
    assert [b["label"] for b in second["buttons"][0]] == ["자세히 보기"]   # 원문 주소가 없으면 버튼을 뺀다
    assert "신청하는 곳에서 최종 확인" in second["text"] and "최종 확인" not in first["text"]


def test_card_hides_plain_apply_period():
    text = messenger.policy_text(1, {**CARD, "apply_period": "상시신청", "has_income_rule": False})
    assert "신청 기간" not in text and "소득 기준" not in text


def test_at_most_five_policies(fake):
    replies = messenger._result({"text": "찾았어요.", "policies": [{**CARD, "id": f"S{i}"} for i in range(8)]})
    assert len(replies) == 6


def test_fallback_links_to_web_search(fake):
    fake["responses"].append({"type": "fallback", "text": "지금은 AI 답변이 어려워요.",
                              "conditions": {"age_group": "75plus", "region_code": "11101"}})
    reply = messenger.on_text("telegram", 1, "병원비")[0]
    assert reply["buttons"][0][0]["url"] == \
        "https://spot.example/search.html?result=1&age_group=75plus&region_code=11101"


def test_error_and_none_are_plain_text(fake):
    fake["responses"] += [{"type": "error", "text": "조금만 짧게 말씀해 주세요."},
                          {"type": "none", "text": "찾지 못했어요. 129", "conditions": {}}]
    assert messenger.on_text("telegram", 1, "가" * 301) == [{"text": "조금만 짧게 말씀해 주세요.", "buttons": []}]
    assert messenger.on_text("telegram", 1, "저녁 메뉴")[0]["buttons"] == []


def test_empty_text_is_not_sent(fake):
    assert messenger.on_text("telegram", 1, "   ")[0]["text"] == messenger.EMPTY_TEXT
    assert fake["reqs"] == []


def test_messenger_daily_limit(fake, monkeypatch):
    monkeypatch.setattr(config, "MESSENGER_DAILY_LIMIT", 2)
    today = datetime.date(2026, 11, 19)
    for user in (1, 2):
        messenger.on_text("telegram", user, "병원비", today=today)
    reply = messenger.on_text("telegram", 3, "병원비", today=today)[0]
    assert reply["text"] == messenger.DAILY_LIMIT_TEXT and reply["buttons"][0][0]["url"] == "https://spot.example/"
    assert len(fake["reqs"]) == 2                                  # 한도를 넘으면 AI를 부르지 않는다
    assert messenger.on_text("discord", 3, "병원비", today=today)[0]["text"] != messenger.DAILY_LIMIT_TEXT
    assert messenger.on_text("telegram", 3, "병원비", today=today + datetime.timedelta(days=1))[0]["text"] \
        != messenger.DAILY_LIMIT_TEXT                              # 날짜가 바뀌면 처음부터


def test_button_recall_is_not_counted(fake, monkeypatch):
    monkeypatch.setattr(config, "MESSENGER_DAILY_LIMIT", 1)
    messenger.on_text("telegram", 1, "병원비")
    messenger.on_button("telegram", 1, "a:-")
    assert messenger.on_button("telegram", 1, "s:-")[0]["text"] == "찾았어요."


def test_no_links_without_public_base_url(fake, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    replies = messenger._result({"text": "찾았어요.", "policies": [{**CARD, "url": None}]})
    assert replies[1]["buttons"] == []


def test_every_button_fits_telegram_callback_limit():
    ask_buttons = [messenger._ask_age(), messenger._ask_sido()] + [messenger._ask_sigungu(c) for c in messenger.SIGUNGU]
    for reply in ask_buttons:
        for d in datas(reply):
            assert len(d.encode()) <= 64

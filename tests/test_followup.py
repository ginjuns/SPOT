"""보여 드린 정책을 이어서 묻는 질문 테스트. DB·Groq 없이 돈다."""
import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import analyzer, answerer, chat_core, faq, followup, messenger, rate_limit, retriever

client = TestClient(app)

ROWS = [
    {"id": "P1", "name": "기초연금", "how_to_apply": "주민센터 방문 또는 복지로 온라인 신청",
     "apply_place": "주민센터", "apply_period": "만 65세 생일 1개월 전부터", "documents": "- 신분증\n - 통장 사본",
     "contact": "보건복지상담센터/129||국민연금공단/1355"},
    {"id": "P2", "name": "노인일자리 및 사회활동 지원", "how_to_apply": "시니어클럽 방문", "apply_place": "시니어클럽",
     "apply_period": "매년 1월", "documents": None, "contact": "한국노인인력개발원/1544-3388"},
]


@pytest.fixture
def fake_db(monkeypatch):
    seen = []

    def fake_query(sql, params):
        seen.append(params)
        return [dict(r) for r in ROWS if r["id"] in params["ids"]]

    monkeypatch.setattr(followup.db, "query", fake_query)
    return seen


def test_asked_fields():
    assert followup.asked_fields("서류는 뭐가 필요해요?") == ["documents"]
    assert followup.asked_fields("어디서 신청해요?") == ["apply"]
    assert followup.asked_fields("언제까지 신청해야 돼요? 전화번호도요") == ["period", "contact"]
    assert followup.asked_fields("어디서 신청하고 서류는 뭐예요") == ["documents", "apply"]
    assert followup.asked_fields("허리가 아파요") == []
    assert followup.asked_fields("전화요금 지원 있나요") == []   # 통신요금 질문은 문의처를 묻는 말이 아니다


def test_pick_policies():
    rows = [{"id": "P1", "name": "기초연금"}, {"id": "P2", "name": "노인일자리 및 사회활동 지원"}]
    assert followup.pick_policies("기초연금 서류는요?", rows) == rows[:1]          # 이름이 나왔다
    assert followup.pick_policies("노인일자리는 어디서 신청해요", rows) == rows[1:]   # 이름 조각이 나왔다
    assert followup.pick_policies("2번 서류 알려 주세요", rows) == rows[1:]
    assert followup.pick_policies("첫 번째 건 어디서 신청해요", rows) == rows[:1]
    assert followup.pick_policies("서류는 뭐가 필요해요?", rows) == rows             # 짧은 글은 모두
    assert followup.pick_policies("그거 신청하려면 우리 동네 어디로 가야 하나요", rows) == rows   # 가리키는 말
    # 다른 것을 묻는 긴 글은 이어서 묻는 질문이 아니다
    assert followup.pick_policies("장애인 콜택시는 어디서 신청해요?", rows) is None
    # 다른 주제 낱말이 있으면 짧아도 새 질문이다. 이름·번호로 가리키면 이어서 묻는 질문이다.
    assert followup.pick_policies("근로장려금 언제 신청해요", rows, other_topic=True) is None
    assert followup.pick_policies("기초연금 신청은 어디서 해요", rows, other_topic=True) == rows[:1]


def test_other_topic_question_goes_to_search(fake_db):
    assert followup.answer("근로장려금 언제 신청해요", ["P1", "P2"]) is None
    assert followup.answer("기초연금 신청은 어디서 해요", ["P1", "P2"])["policies"] == [{"id": "P1", "name": "기초연금"}]


def test_answer_uses_db_values_only(fake_db):
    r = followup.answer("서류랑 문의처 알려 주세요", ["P2", "P1"])
    assert r["type"] == "info" and [p["id"] for p in r["policies"]] == ["P2", "P1"]   # 카드 순서 그대로
    assert "■ 노인일자리 및 사회활동 지원\n준비할 서류: 자료에 적혀 있지 않아요" in r["text"]
    assert "준비할 서류: - 신분증\n- 통장 사본" in r["text"]
    assert "문의처: 보건복지상담센터/129, 국민연금공단/1355" in r["text"]
    assert "최종 확인" in r["text"]


def test_answer_is_none_when_not_a_follow_up(fake_db):
    assert followup.answer("허리가 아파요", ["P1"]) is None
    assert followup.answer("서류는요?", []) is None
    assert fake_db == []   # 묻는 말이 없으면 DB도 보지 않는다


@pytest.fixture
def no_ai(monkeypatch, fake_db):
    calls = []
    monkeypatch.setattr(analyzer, "analyze", lambda *a, **k: calls.append("analyze") or {})
    monkeypatch.setattr(answerer, "answer", lambda *a, **k: calls.append("answer"))
    monkeypatch.setattr(retriever, "search_semantic", lambda *a, **k: calls.append("search") or [])
    rate_limit.reset()
    yield calls
    rate_limit.reset()


def test_chat_answers_follow_up_without_ai(no_ai):
    r = client.post("/api/chat", json={"message": "어디서 신청해요?", "shown": ["P1"],
                                       "conditions": {"age_group": "75plus"}}).json()
    assert r["type"] == "info" and "신청하는 곳: 주민센터" in r["text"]
    assert r["conditions"]["age_group"] == "75plus"   # 조건은 그대로 돌려준다
    assert no_ai == []


def test_chat_without_shown_is_a_new_question(no_ai, monkeypatch):
    monkeypatch.setattr(faq, "pick", lambda message: None)
    r = client.post("/api/chat", json={"message": "어디서 신청해요?"}).json()
    assert r["type"] == "ask" and no_ai == ["analyze"]


def test_bad_shown_id_is_rejected(no_ai):
    r = client.post("/api/chat", json={"message": "서류요", "shown": ["'; DROP TABLE policy"]})
    assert r.status_code == 400


def test_messenger_remembers_shown_ids(monkeypatch):
    reqs = []
    card = {"id": "P1", "name": "기초연금", "agency": "보건복지부", "one_line": "", "has_income_rule": True,
            "url": "https://example.com", "collected_at": datetime.date(2026, 11, 13)}
    responses = [
        {"type": "result", "text": "찾았어요.", "policies": [card], "conditions": {"age_group": "75plus"}},
        {"type": "info", "text": "■ 기초연금\n준비할 서류: 신분증", "policies": [{"id": "P1", "name": "기초연금"}],
         "conditions": {"age_group": "75plus"}},
    ]
    monkeypatch.setattr(chat_core, "handle", lambda req, key: reqs.append(req) or responses.pop(0))
    monkeypatch.setattr(messenger.config, "PUBLIC_BASE_URL", "https://spot.example")
    messenger.reset()
    messenger.on_text("telegram", 1, "기초연금")
    replies = messenger.on_text("telegram", 1, "서류는요?")
    assert reqs[1].shown == ["P1"]
    assert replies[0]["text"].startswith("■ 기초연금")
    assert replies[0]["buttons"] == [[{"label": "자세히 보기", "url": "https://spot.example/policy.html?id=P1"}]]
    messenger.reset()

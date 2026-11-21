"""자주 묻는 질문(키워드)으로 AI 없이 답하기 테스트. DB·Groq 없이 돈다."""
import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import analyzer, answerer, faq, rate_limit, retriever

client = TestClient(app)

CARD = {"id": "P1", "name": "통합문화이용권(문화누리카드)", "agency": "문화체육관광부", "one_line": "문화 관람 지원",
        "has_income_rule": True, "url": "https://example.com", "apply_period": "상시신청",
        "collected_at": datetime.date(2026, 11, 13)}


def test_every_example_question_matches_its_own_topic():
    """faq.json 의 예시 질문은 모두 자기 주제 하나로만 걸린다 (겹치면 AI로 넘어가 버린다)."""
    for t in faq.TOPICS:
        for q in t["questions"]:
            topic = faq.match(q)
            assert topic and topic["id"] == t["id"], (t["id"], q, faq.matched_topics(q))


def test_topic_fields_are_valid():
    ids = [t["id"] for t in faq.TOPICS]
    assert len(ids) == len(set(ids))
    for t in faq.TOPICS:
        assert t["need"] in analyzer.NEEDS and t["keys"] and t["names"] and t["questions"]
        assert t.get("level", 1) in (0, 1, 2)


def test_matching_rules():
    assert faq.match("독감주사 무료인가요")["id"] == "flu_vaccine"      # 띄어쓰기는 무시한다
    assert faq.match("무릎 수술비 지원")["id"] == "knee_surgery"        # 넓은 주제(병원비)보다 좁은 주제
    assert faq.match("문화재 관람 무료인가요?")["id"] == "heritage"      # "문화재" 안의 "화재"에 걸리지 않는다
    assert faq.match("75살이고 서울 살아요") is None                     # 조건만 말한 글은 AI로
    assert faq.match("보청기랑 휠체어 둘 다 필요해요") is None           # 두 주제가 같은 단계로 걸리면 AI로


@pytest.fixture
def fake(monkeypatch):
    calls = {"analyze": [], "answer": [], "faq": []}
    monkeypatch.setattr(analyzer, "analyze", lambda *a, **k: calls["analyze"].append(a) or {})
    monkeypatch.setattr(answerer, "answer", lambda *a, **k: calls["answer"].append(a) or {"text": "", "picks": []})
    monkeypatch.setattr(retriever, "search_semantic", lambda *a, **k: [])
    monkeypatch.setattr(faq, "policies", lambda topic, cond: calls["faq"].append((topic["id"], dict(cond))) or
                        calls.get("cards", [CARD]))
    rate_limit.reset()
    yield calls
    rate_limit.reset()


def test_faq_question_is_answered_without_ai(fake):
    r = client.post("/api/chat", json={"message": "영화 한 편 보고 싶은데 돈이 없어요", "asked": True}).json()
    assert r["type"] == "result" and r["via"] == "faq"
    assert r["policies"][0]["name"] == "통합문화이용권(문화누리카드)"
    assert "최종 확인" in r["text"] and r["conditions"]["faq"] == "culture_card"
    assert fake["analyze"] == [] and fake["answer"] == []   # AI를 한 번도 부르지 않았다


def test_faq_asks_then_uses_buttons_without_ai(fake):
    r = client.post("/api/chat", json={"message": "보청기 지원이 있나요?"}).json()
    assert r["type"] == "ask" and r["ask"] == ["age_group", "region"]
    cond = {**r["conditions"], "age_group": "75plus", "region_code": "11109"}
    r = client.post("/api/chat", json={"message": "", "asked": True, "conditions": cond}).json()
    assert r["type"] == "result" and r["via"] == "faq"
    assert fake["faq"][-1] == ("hearing_aid", {**cond})
    assert fake["analyze"] == [] and fake["answer"] == []


def test_age_and_region_in_text_are_used(fake):
    r = client.post("/api/chat", json={"message": "75살인데 임플란트 비용이 걱정이에요"}).json()
    assert r["type"] == "ask" and r["ask"] == ["region"] and r["conditions"]["age_group"] == "75plus"


def test_no_matching_policy_falls_back_to_ai(fake):
    fake["cards"] = []
    r = client.post("/api/chat", json={"message": "대상포진 주사 지원", "asked": True}).json()
    assert r["type"] == "none" and len(fake["answer"]) == 0   # 의미 검색 후보도 없어서 AI까지 가지 않았다
    assert "via" not in r


def test_new_ai_question_clears_previous_topic(fake, monkeypatch):
    monkeypatch.setattr(analyzer, "analyze", lambda *a, **k: {
        "need": "기타", "age_group": None, "gender": None, "region_code": None, "household": None,
        "search_text": "무언가", "has_terms": True})
    r = client.post("/api/chat", json={"message": "다른 걸 물어볼게요", "asked": True,
                                       "conditions": {"faq": "culture_card"}}).json()
    assert r["conditions"]["faq"] is None

"""/api/chat 흐름 테스트. DB·Groq·임베딩 모델 없이 돈다 (분석과 검색은 가짜로 바꾼다)."""
import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import analyzer, retriever

client = TestClient(app)  # with 를 쓰지 않으므로 DB 연결을 열지 않는다

ROW = {
    "id": "SVC1", "name": "재난적 의료비 지원", "agency": "보건복지부", "summary": "큰 병원비를 지원해요.",
    "target": "…", "content": "…", "has_income_rule": True, "url": "https://example.com",
    "collected_at": datetime.date(2026, 11, 13), "distance": 0.1,
}


def analysis(**over):
    base = {"need": "의료비", "age_group": None, "gender": None, "region_text": None,
            "region_code": None, "household": None, "search_text": "병원비 의료비 지원", "source": "llm"}
    return {**base, **over}


@pytest.fixture
def fake(monkeypatch):
    calls = {"analyze": [], "search": []}

    def fake_analyze(message, history=None):
        calls["analyze"].append((message, history))
        return calls.get("analysis") or analysis()

    def fake_search(search_text, **cond):
        calls["search"].append((search_text, cond))
        return calls.get("rows", [ROW])

    monkeypatch.setattr(analyzer, "analyze", fake_analyze)
    monkeypatch.setattr(retriever, "search_semantic", fake_search)
    return calls


def test_asks_when_age_and_region_are_missing(fake):
    r = client.post("/api/chat", json={"message": "병원비 지원이 있나요?"}).json()
    assert r["type"] == "ask" and r["ask"] == ["age_group", "region"]
    assert r["conditions"]["search_text"] == "병원비 의료비 지원" and r["conditions"]["need"] == "의료비"
    assert fake["search"] == []  # 되물을 때는 검색하지 않는다


def test_asks_only_for_what_is_missing(fake):
    fake["analysis"] = analysis(age_group="75plus")
    r = client.post("/api/chat", json={"message": "78살인데 병원비 지원이 있나요?"}).json()
    assert r["type"] == "ask" and r["ask"] == ["region"]


def test_button_call_skips_analysis_and_searches(fake):
    r = client.post("/api/chat", json={
        "message": "", "asked": True,
        "conditions": {"age_group": "75plus", "region_code": "18101", "need": "의료비",
                       "search_text": "병원비 의료비 지원"},
    }).json()
    assert fake["analyze"] == []  # LLM을 다시 부르지 않는다
    assert fake["search"] == [("병원비 의료비 지원", {"age_group": "75plus", "gender": None,
                                               "region_code": "18101", "household": None})]
    assert r["type"] == "result" and r["policies"][0]["id"] == "SVC1"
    assert r["policies"][0]["one_line"] == "큰 병원비를 지원해요."
    assert "distance" not in r["policies"][0] and "신청하는 곳에서 최종 확인" in r["text"]


def test_asks_at_most_once(fake):
    """건너뛰기를 눌러 조건이 여전히 없어도 다시 묻지 않고, 전국 정책만 찾는다."""
    r = client.post("/api/chat", json={
        "message": "", "asked": True, "conditions": {"search_text": "병원비 의료비 지원"},
    }).json()
    assert r["type"] == "result" and "지역을 알려 주시면" in r["text"]
    assert fake["search"][0][1]["region_code"] is None


def test_button_choice_wins_over_analysis(fake):
    fake["analysis"] = analysis(age_group="19_34", region_code="17")
    client.post("/api/chat", json={
        "message": "병원비 지원", "asked": True,
        "conditions": {"age_group": "75plus", "region_code": "18101"},
    })
    cond = fake["search"][0][1]
    assert cond["age_group"] == "75plus" and cond["region_code"] == "18101"


def test_follow_up_with_only_conditions_keeps_previous_search_text(fake):
    fake["analysis"] = analysis(need="기타", age_group="75plus", region_code="18", search_text="75살 서울")
    r = client.post("/api/chat", json={
        "message": "75살이고 서울 살아요", "asked": True,
        "conditions": {"need": "의료비", "search_text": "병원비 의료비 지원"},
    }).json()
    assert fake["search"][0][0] == "병원비 의료비 지원"
    assert r["conditions"]["need"] == "의료비" and r["conditions"]["age_group"] == "75plus"


def test_none_when_nothing_found(fake):
    fake["rows"] = []
    r = client.post("/api/chat", json={"message": "", "asked": True,
                                       "conditions": {"search_text": "아무거나"}}).json()
    assert r["type"] == "none" and "129" in r["text"]


def test_personal_info_is_masked_before_analysis(fake):
    r = client.post("/api/chat", json={
        "message": "제 번호는 010-1234-5678 이에요. 병원비 지원이 있나요?",
        "history": [{"role": "user", "text": "주민번호 900101-1234567"}],
    }).json()
    message, history = fake["analyze"][0]
    assert "010" not in message and "[가림]" in message
    assert "900101" not in history[0]["text"]
    assert "입력하지 않으셔도 돼요" in r["text"]


def test_only_last_six_history_items_are_used(fake):
    history = [{"role": "user", "text": f"말{i}"} for i in range(10)]
    client.post("/api/chat", json={"message": "병원비", "history": history})
    assert [h["text"] for h in fake["analyze"][0][1]] == [f"말{i}" for i in range(4, 10)]


def test_too_long_message(fake):
    r = client.post("/api/chat", json={"message": "가" * 301})
    assert r.status_code == 400 and r.json() == {"error": "조금만 짧게 말씀해 주세요."}


def test_empty_message_without_search_text(fake):
    r = client.post("/api/chat", json={"message": "  "})
    assert r.status_code == 400 and "error" in r.json()


def test_bad_condition_value_is_rejected(fake):
    r = client.post("/api/chat", json={"message": "병원비", "conditions": {"age_group": "100살"}})
    assert r.status_code == 400 and "error" in r.json()

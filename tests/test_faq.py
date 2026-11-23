"""자주 묻는 질문(키워드)으로 AI 없이 답하기 테스트. DB·Groq 없이 돈다."""
import datetime

import pytest
from fastapi.testclient import TestClient

from app import config
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
        assert t.get("level", 1) in (-1, 0, 1, 2)


def test_matching_rules():
    assert faq.match("독감주사 무료인가요")["id"] == "flu_vaccine"      # 띄어쓰기는 무시한다
    assert faq.match("무릎 수술비 지원")["id"] == "knee_surgery"        # 넓은 주제(병원비)보다 좁은 주제
    assert faq.match("문화재 관람 무료인가요?")["id"] == "heritage"      # "문화재" 안의 "화재"에 걸리지 않는다
    assert faq.match("75살이고 서울 살아요") is None                     # 조건만 말한 글은 AI로
    assert faq.match("보청기랑 휠체어 둘 다 필요해요") is None           # 두 주제가 같은 단계로 걸리면 AI로
    assert faq.match("아들이 취직을 못 해요 그리고 저도 아파요") is None  # 여러 가지를 이어서 물으면 AI로


def test_age_group_check():
    """이름·지원 대상 글에 나이 무리가 적혀 있으면 사용자 나이대와 맞을 때만 보여 준다 (75세에게 학교 급식비 X)."""
    school = {"name": "유·초·중·특수학교 친환경급식비 지원", "target": "도내 유ㆍ초ㆍ중ㆍ고ㆍ특수학교 전체 학생"}
    infertility = {"name": "난임 부부 심리상담", "target": "○ 난임 부부"}
    elder = {"name": "노인맞춤돌봄서비스", "target": "○ 65세 이상 기초연금수급자"}
    flu = {"name": "인플루엔자 국가예방접종 지원", "target": "○ 어린이 ... ○ 65세 이상 어르신"}
    kpass = {"name": "K-패스", "target": "만 19세 이상의 국민 - 청년층: 만19~34세"}
    plain = {"name": "에너지바우처", "target": "소득기준 및 세대원 특성 기준을 모두 충족하는 세대"}
    assert not faq.fits_age(school, "75plus", False)
    assert faq.fits_age(school, "75plus", True)          # 손주를 위한 질문이면 아이 대상 정책도 보여 준다
    assert not faq.fits_age(infertility, "75plus", False)
    assert faq.fits_age(infertility, "35_49", False)
    assert not faq.fits_age(elder, "19_34", False)
    assert faq.fits_age(flu, "75plus", False)            # 여러 무리가 같이 적혀 있으면 그중 하나만 맞아도 된다
    assert faq.fits_age(kpass, "35_49", False)           # "국민"(누구나)이 있으면 무리 검사를 하지 않는다
    assert faq.fits_age(plain, "u19", False)             # 무리가 적혀 있지 않으면 보여 준다
    assert faq.fits_age(school, None, False)             # 나이를 모르면 거르지 않는다
    assert faq.age_groups("대학생 기숙사", "") == {"youth"}   # "대학생"의 "학생"을 아이 무리로 보지 않는다


def test_age_groups_also_read_summary():
    """지원 대상 글 앞부분에 어린이만 있어도 요약에 어르신이 있으면 어르신에게 보인다 (독감 예방접종)."""
    flu = {"name": "인플루엔자 국가예방접종 지원", "summary": "어린이, 임신부, 어르신 등 대상으로 예방접종 지원",
           "target": "○ 어린이 인플루엔자 국가예방접종 지원 - 지원대상: 생후 6개월~14세 어린이 " + "가" * 80 + " ○ 어르신"}
    assert faq.fits_age(flu, "75plus", False)
    # "국민연금"의 "국민"처럼 요약에 있는 말로는 누구나 받는 정책으로 보지 않는다
    credit = {"name": "실업크레딧 지원", "summary": "구직급여 수급자의 국민연금 보험료 지원", "target": "18세 이상 청년"}
    assert not faq.fits_age(credit, "75plus", False)


def test_special_group_policies_go_last_unless_asked():
    params = {}
    assert "ILIKE" in faq.special_rank(params, "치과 치료비")          # 장애 이야기가 없으면 장애인 정책은 뒤로
    assert any(v == "%장애%" for v in params.values())
    params = {}
    faq.special_rank(params, "장애가 있는데 치과 치료비")
    assert not any(v == "%장애%" for v in params.values())               # 장애를 말했으면 미루지 않는다


@pytest.fixture
def fake(monkeypatch):
    calls = {"analyze": [], "answer": [], "faq": []}
    monkeypatch.setattr(analyzer, "analyze", lambda *a, **k: calls["analyze"].append(a) or {})
    monkeypatch.setattr(answerer, "answer", lambda *a, **k: calls["answer"].append(a) or {"text": "", "picks": []})
    monkeypatch.setattr(retriever, "search_semantic", lambda *a, **k: [])
    monkeypatch.setattr(faq, "policies", lambda topic, cond, message="": calls["faq"].append((topic["id"], dict(cond)))
                        or calls.get("cards", [CARD]))
    rate_limit.reset()
    yield calls
    rate_limit.reset()


def test_faq_question_is_answered_without_ai(fake):
    r = client.post("/api/chat", json={"message": "영화 한 편 보고 싶은데 돈이 없어요", "asked": True}).json()
    assert r["type"] == "result" and r["via"] == "faq"
    assert r["policies"][0]["name"] == "통합문화이용권(문화누리카드)"
    assert "최종 확인" in r["text"] and r["conditions"]["faq"] == "culture_card"
    assert fake["analyze"] == [] and fake["answer"] == []   # AI를 한 번도 부르지 않았다


def test_faq_miss_that_goes_to_ai_counts_as_question(fake, monkeypatch):
    """자주 묻는 질문인데 맞는 정책이 없어 AI로 넘어가면 질문 1번으로 센다 (Groq 한도 보호)."""
    monkeypatch.setattr(config, "DAILY_CHAT_LIMIT", 1)
    fake["cards"] = []
    body = {"message": "영화 한 편 보고 싶은데 돈이 없어요", "asked": True}
    assert client.post("/api/chat", json=body).json()["type"] == "none"
    r = client.post("/api/chat", json=body).json()
    assert r["type"] == "fallback" and "오늘 질문 횟수를 다 쓰셨어요" in r["text"]
    assert len(fake["answer"]) == 0   # 한도를 넘은 두 번째에는 AI까지 가지 않았다 (첫 번째는 후보가 없어 AI 전에 끝남)


def test_is_special():
    assert faq.is_special("장애인 치과치료비 지원", "치과 치료비")
    assert not faq.is_special("장애인 치과치료비 지원", "장애가 있어요 치과")
    assert not faq.is_special("어르신 틀니 지원", "치과 치료비")


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


def test_child_words_in_question_set_for_child(fake):
    client.post("/api/chat", json={"message": "손주가 태권도 다니는데 비용이 부담돼요", "asked": True,
                                   "conditions": {"age_group": "75plus"}})
    assert fake["faq"][-1][0] == "sports_voucher" and fake["faq"][-1][1]["for_child"] is True


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


def test_false_friend_word_does_not_match():
    """"제대로"의 "제대"는 군 제대가 아니다."""
    assert "veterans_job" not in faq.matched_topics("이가 다 빠져서 밥을 제대로 못 씹어요")

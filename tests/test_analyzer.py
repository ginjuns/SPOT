from app.services import analyzer, llm
from app.services.analyzer import (
    age_to_group, analyze_by_rules, build_user_prompt, decade_to_group, normalize, resolve_region,
)


def code(sido, sigungu=None):
    sido_codes, sigungu_codes = analyzer._regions()
    return sigungu_codes[(sido, sigungu)] if sigungu else sido_codes[sido]


def test_age_to_group_edges():
    assert [age_to_group(a) for a in (0, 18, 19, 34, 35, 49, 50, 64, 65, 74, 75, 120)] == [
        "u19", "u19", "19_34", "19_34", "35_49", "35_49", "50_64", "50_64", "65_74", "65_74",
        "75plus", "75plus",
    ]
    assert age_to_group(None) is None and age_to_group(300) is None


def test_decade_is_left_empty_when_it_spans_two_groups():
    assert decade_to_group(20) == "19_34"
    assert decade_to_group(80) == "75plus"
    # 70대는 65~74세와 75세 이상에 걸친다 → 정하지 않고 되묻는다
    assert decade_to_group(70) is None and decade_to_group(60) is None and decade_to_group(30) is None


def test_resolve_region():
    assert resolve_region("서울 강남구") == code("서울특별시", "강남구")
    assert resolve_region("강남") == code("서울특별시", "강남구")
    assert resolve_region("부산") == code("부산광역시")
    assert resolve_region("부산 강서구") == code("부산광역시", "강서구")
    assert resolve_region("경기 광주시") == code("경기도", "광주시")
    assert resolve_region("남양주") == code("경기도", "남양주시")
    assert resolve_region("전라남도 나주") == code("전남광주통합특별시", "나주시")
    # 여러 곳에 있는 이름은 시·도 없이는 정하지 않는다
    assert resolve_region("중구") is None and resolve_region("강서구") is None
    assert resolve_region(None) is None and resolve_region("우리 동네") is None


def test_resolve_region_strict_does_not_guess_from_ordinary_words():
    assert resolve_region("고령자 지원이 궁금해요", strict=True) is None
    assert resolve_region("요즘 경기가 안 좋아서 힘들어요", strict=True) is None
    assert resolve_region("강남구에 살아요", strict=True) == code("서울특별시", "강남구")


def test_normalize_drops_values_outside_the_allowed_set():
    out = normalize(
        {"need": "아무거나", "age": "78", "gender": "여", "region_text": " 서울  강남구 ",
         "household": "rich", "search_text": ""},
        "병원비 지원이 있나요",
    )
    assert out["need"] == "기타" and out["gender"] is None and out["household"] is None
    assert out["age_group"] == "75plus"
    assert out["region_text"] == "서울 강남구" and out["region_code"] == code("서울특별시", "강남구")
    assert out["search_text"] == "병원비 지원이 있나요"  # 비어 있으면 사용자 글을 쓴다


def test_normalize_does_not_fill_age_from_nothing():
    out = normalize({"need": "의료비", "age": None, "age_decade": 70, "search_text": "의료비 지원"}, "x")
    assert out["age_group"] is None and out["region_code"] is None


def test_rules():
    out = analyze_by_rules("강남구에 혼자 사는 78살인데 병원비가 걱정이에요")
    assert out["need"] == "의료비" and out["age_group"] == "75plus"
    assert out["household"] == "single" and out["region_code"] == code("서울특별시", "강남구")
    assert out["gender"] is None

    empty = analyze_by_rules("안녕하세요")
    assert empty["need"] == "기타" and empty["age_group"] is None and empty["region_code"] is None


def test_prompt_keeps_only_last_six_turns():
    history = [{"role": "user", "text": f"말{i}"} for i in range(10)]
    prompt = build_user_prompt("지금 질문", history)
    assert "말3" not in prompt and "말4" in prompt and "말9" in prompt
    assert prompt.endswith("<사용자 글>지금 질문</사용자 글>")


def test_analyze_falls_back_to_rules_when_llm_fails(monkeypatch):
    def broken(*args, **kwargs):
        raise llm.LLMError("rate_limit")

    monkeypatch.setattr(llm, "chat_json", broken)
    out = analyzer.analyze("월세가 부담돼요")
    assert out["source"] == "rules" and out["need"] == "주거"


def test_analyze_uses_llm_result(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {
        "need": "주거", "age": 27, "region_text": "부산", "search_text": "청년 월세 지원"})
    out = analyzer.analyze("부산 사는 27살인데 월세가 부담돼요")
    assert out["source"] == "llm" and out["age_group"] == "19_34"
    assert out["region_code"] == code("부산광역시")
    # 검색 문장은 다듬은 문장 뒤에 원래 질문을 붙인다
    assert out["search_text"] == "청년 월세 지원. 부산 사는 27살인데 월세가 부담돼요"


def test_with_question_does_not_repeat_the_same_text():
    assert analyzer.with_question("월세가 부담돼요", "월세가  부담돼요") == "월세가 부담돼요"
    assert analyzer.with_question(None, "월세가 부담돼요") == "월세가 부담돼요"

def test_expand_adds_policy_words_for_everyday_phrases():
    out = analyzer.expand("나이 들면 나라에서 매달 주는 돈이 있다던데")
    assert out.startswith("나이 들면 나라에서 매달 주는 돈이 있다던데 ") and "기초연금" in out
    both = analyzer.expand("은퇴하고 소일거리를 찾는데 난방비도 걱정이에요")
    assert "노인일자리" in both and "에너지바우처" in both
    # 해당하는 말이 없으면 그대로 둔다
    assert analyzer.expand("대학 등록금 장학금") == "대학 등록금 장학금"


def test_for_child_is_detected():
    assert analyze_by_rules("초등학생 아이를 봐줄 사람이 필요해요")["for_child"] is True
    assert analyze_by_rules("무릎이 아파서 수술을 해야 해요")["for_child"] is False
    assert normalize({"for_child": True}, "x")["for_child"] is True
    assert normalize({"for_child": "yes"}, "x")["for_child"] is False   # true 가 아니면 모두 False

def test_terms_from_llm_go_in_front_of_the_search_text(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {
        "need": "생활비", "search_text": "노인 생활비 지원", "terms": ["기초연금", " 노인 수당 ", 3, "가" * 30]})
    out = analyzer.analyze("나이 들면 매달 주는 돈이 있나요")
    assert out["search_text"] == "기초연금 노인 수당 " + "가" * 20 + " 노인 생활비 지원. 나이 들면 매달 주는 돈이 있나요"
    assert "terms" not in out   # 브라우저로 따로 보내지 않는다


def test_clean_terms():
    assert analyzer.clean_terms(None) == [] and analyzer.clean_terms("기초연금") == []
    assert analyzer.clean_terms(["a", "b", "c", "d", "e", "f"]) == ["a", "b", "c", "d", "e"]

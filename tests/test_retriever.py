import numpy as np

from app.services import retriever
from app.services.retriever import AGE_RANGES, build_filter, drop_far, one_line


def test_drop_far():
    rows = [{"id": "a", "distance": 0.10}, {"id": "b", "distance": 0.30}, {"id": "c", "distance": 0.31}]
    assert [r["id"] for r in drop_far(rows, 0.30)] == ["a", "b"]


def test_search_semantic_keeps_filter_and_drops_far(monkeypatch):
    """DB와 모델 없이: 조건 필터가 SQL에 들어가고, 먼 후보는 빠지는지 본다."""
    seen = {}

    def fake_query(sql, params):
        if "source IS NOT NULL" in sql:   # 민간 지원 몫 (따로 본다)
            return []
        seen["sql"], seen["params"] = sql, params
        return [{"id": "a", "distance": 0.1}, {"id": "b", "distance": 0.9}]

    monkeypatch.setattr(retriever.db, "query", fake_query)
    monkeypatch.setattr("app.services.embedder.embed_query", lambda text: np.zeros(384, dtype=np.float32))

    rows = retriever.search_semantic("병원비 지원", age_group="75plus", max_distance=0.5)
    assert [r["id"] for r in rows] == ["a"]
    # 지역을 모르면 전국 정책만 찾는다
    assert "region_code IS NULL" in seen["sql"] and "region_code =" not in seen["sql"]
    assert "embedding <=> %(query_vec)s" in seen["sql"]
    assert seen["params"]["age_lo"] == 75 and "LIMIT 20" in seen["sql"]   # 빠질 몫까지 넉넉히 가져온다


def _fake_semantic(monkeypatch, nation, local, private=()):
    """전체 검색은 nation + local 을 가까운 순으로, 지역만 찾는 검색은 local 을, 민간 검색은 private 를 돌려준다."""
    def fake_query(sql, params):
        if "source IS NOT NULL" in sql:
            return [dict(r) for r in private]
        rows = local if "region_code IS NOT NULL" in sql else sorted(nation + local, key=lambda r: r["distance"])
        return [dict(r) for r in rows]

    monkeypatch.setattr(retriever.db, "query", fake_query)
    monkeypatch.setattr("app.services.embedder.embed_query", lambda text: np.zeros(384, dtype=np.float32))


def test_local_policies_get_seats(monkeypatch):
    """사는 곳을 골랐으면 전국 정책이 아무리 가까워도 지역 정책을 3건까지 넣는다 (가장 먼 전국 정책이 빠진다)."""
    nation = [{"id": f"n{i}", "distance": 0.05 + i * 0.001, "region_code": None} for i in range(10)]
    local = [{"id": f"l{i}", "distance": 0.12 + i * 0.001, "region_code": "18101"} for i in range(4)]
    _fake_semantic(monkeypatch, nation, local)
    rows = retriever.search_semantic("병원비", region_code="18101")
    assert [r["id"] for r in rows] == ["n0", "n1", "n2", "n3", "n4", "l0", "l1", "l2"]
    # 지역을 모르면 그대로 가까운 순 (전국 정책만)
    _fake_semantic(monkeypatch, nation, [])
    assert [r["id"] for r in retriever.search_semantic("병원비")] == [f"n{i}" for i in range(8)]


def test_local_seats_skip_far_policies(monkeypatch):
    nation = [{"id": f"n{i}", "distance": 0.05, "region_code": None} for i in range(8)]
    local = [{"id": "l0", "distance": 0.12, "region_code": "18"}, {"id": "far", "distance": 0.4, "region_code": "18"}]
    _fake_semantic(monkeypatch, nation, local)
    ids = [r["id"] for r in retriever.search_semantic("병원비", region_code="18101")]
    assert "l0" in ids and "far" not in ids and len(ids) == 8


def test_keep_filters_before_cutting(monkeypatch):
    """keep 으로 빠진 자리는 다음 후보로 채운다."""
    nation = [{"id": f"n{i}", "distance": 0.05 + i * 0.001, "region_code": None} for i in range(10)]
    _fake_semantic(monkeypatch, nation, [])
    rows = retriever.search_semantic("병원비", keep=lambda r: r["id"] not in ("n0", "n1"))
    assert [r["id"] for r in rows] == [f"n{i}" for i in range(2, 10)]


def test_private_support_takes_at_most_two_seats(monkeypatch):
    """민간 지원·장학금이 아무리 가까워도 후보의 2자리까지만 (이름이 "장학금"뿐인 장학금이 국가장학금을 밀어냈다)."""
    nation = [{"id": f"n{i}", "distance": 0.10 + i * 0.001, "region_code": None} for i in range(10)]
    private = [{"id": f"p{i}", "distance": 0.08 + i * 0.001, "region_code": None, "source": "민간 장학금"}
               for i in range(10)]
    _fake_semantic(monkeypatch, nation, [], private)
    ids = [r["id"] for r in retriever.search_semantic("대학 등록금")]
    assert ids == ["p0", "p1"] + [f"n{i}" for i in range(6)]


def test_no_region_means_nationwide_only():
    where, params = build_filter()
    assert where == "region_code IS NULL"
    assert params == {}


def test_region_includes_nationwide_sido_sigungu():
    where, params = build_filter(region_code="12101")
    assert "region_code IS NULL" in where
    assert "LEFT(%(region)s, 2)" in where
    assert params == {"region": "12101"}


def test_age_group_becomes_range():
    where, params = build_filter(age_group="65_74", region_code="12")
    assert params["age_lo"] == 65 and params["age_hi"] == 74
    assert "age_min <= %(age_hi)s" in where and "age_max >= %(age_lo)s" in where


def test_null_conditions_are_left_out():
    where, params = build_filter(gender="F")
    assert "gender" in where and "household" not in where and "age_min" not in where
    assert params == {"gender": "F"}


def test_age_ranges_do_not_overlap():
    ranges = sorted(AGE_RANGES.values())
    for (_, hi), (lo, _) in zip(ranges, ranges[1:]):
        assert lo == hi + 1


def test_one_line():
    assert one_line(None) == ""
    assert one_line("○ 짧은 요약\n둘째 줄") == "짧은 요약"
    long = "가나다라 " * 30
    assert len(one_line(long)) <= 71 and one_line(long).endswith("…")

def _capture_queries(monkeypatch):
    """DB 없이 search_by_conditions 가 만든 SQL과 값을 받아 본다."""
    seen = []

    def fake_query(sql, params):
        seen.append((sql, dict(params)))
        return [{"n": 0, "org": 0}] if "count(*)" in sql else []

    monkeypatch.setattr(retriever.db, "query", fake_query)
    return seen


def test_search_by_category(monkeypatch):
    seen = _capture_queries(monkeypatch)
    retriever.search_by_conditions(category="보건·의료")
    sql, params = seen[0]
    assert "category = %(category)s" in sql and params["category"] == "보건·의료"
    # 낱말 없이 지역을 고르지 않으면 전과 같이 전국 정책만 찾는다
    assert "region_code IS NULL" in sql


def test_search_by_keyword(monkeypatch):
    seen = _capture_queries(monkeypatch)
    retriever.search_by_conditions(keyword="  기초연금   신청 ")
    count_sql, params = seen[0]
    list_sql, _ = seen[1]
    # 낱말마다 이름·요약·대상·내용에서 찾고, 모든 낱말이 들어 있어야 한다
    assert params["kw0"] == "%기초연금%" and params["kw1"] == "%신청%"
    assert "name ILIKE %(kw0)s OR summary ILIKE %(kw0)s" in count_sql
    assert "content ILIKE %(kw1)s" in count_sql
    # 지역을 고르지 않고 낱말로 찾으면 모든 지역에서 찾는다
    assert "region_code" not in count_sql
    # 이름이 낱말과 똑같은 정책 → 이름에 낱말이 있는 정책 → 전국 정책 순서로 보여 준다
    assert ("ORDER BY CASE WHEN name = %(kw_all)s THEN 0 "
            "WHEN name ILIKE %(kw0)s AND name ILIKE %(kw1)s THEN 1 ELSE 2 END, "
            "CASE WHEN region_code IS NULL THEN 0 ELSE 1 END, views DESC, name") in list_sql
    assert seen[1][1]["kw_all"] == "기초연금 신청"


def test_keyword_with_region_keeps_region_filter(monkeypatch):
    seen = _capture_queries(monkeypatch)
    retriever.search_by_conditions(region_code="18101", keyword="난방비", category="생활안정")
    sql, params = seen[0]
    assert "region_code = %(region)s" in sql and "category = %(category)s" in sql
    assert params["region"] == "18101" and params["kw0"] == "%난방비%"


def test_person_only_by_default(monkeypatch):
    """기본으로는 개인·가구가 받는 지원만 보여 주고, 뺀 건수를 알려 준다."""
    seen = []

    def fake_query(sql, params):
        seen.append(sql)
        return [{"n": 7, "org": 3}] if "count(*)" in sql else []

    monkeypatch.setattr(retriever.db, "query", fake_query)
    result = retriever.search_by_conditions(category="고용·창업")
    assert result["total"] == 7 and result["hidden_org"] == 3
    assert seen[1].count("AND for_person") == 1

    seen.clear()
    result = retriever.search_by_conditions(category="고용·창업", include_org=True)
    assert result["total"] == 10 and result["hidden_org"] == 0
    assert "AND for_person" not in seen[1]


def test_related_names_are_searched_in_name(monkeypatch):
    """비슷한 말: 낱말이 없어도 이름에 비슷한 말이 있는 정책을 함께 찾는다."""
    seen = _capture_queries(monkeypatch)
    result = retriever.search_by_conditions(keyword="난방비", related=["에너지바우처"])
    count_sql, params = seen[0]
    assert params["rel0"] == "%에너지바우처%"
    assert "OR name ILIKE %(rel0)s)" in count_sql
    assert "WHEN (name ILIKE %(kw0)s) OR name ILIKE %(rel0)s THEN 1 ELSE 2 END" in seen[1][0]
    assert result["related"] == ["에너지바우처"]
    # 낱말 없이 비슷한 말만 넘어오면 쓰지 않는다
    seen.clear()
    assert retriever.search_by_conditions(related=["에너지바우처"])["related"] == []
    assert "rel0" not in seen[0][1]


def test_keyword_terms_and_like_pattern():
    assert retriever.keyword_terms(None) == []
    assert retriever.keyword_terms("   ") == []
    assert len(retriever.keyword_terms("가 나 다 라 마 바 사")) == retriever.MAX_KEYWORDS
    # %, _ 는 "아무 글자"가 아니라 글자 그대로 찾는다
    assert retriever.like_pattern("50%_할인\\") == "%50\\%\\_할인\\\\%"


def test_for_child_keeps_child_policies_despite_parent_age():
    where, params = build_filter(age_group="35_49", for_child=True)
    assert "OR age_max <= 18" in where and params["age_lo"] == 35
    plain, _ = build_filter(age_group="35_49")
    assert "age_max <= 18" not in plain
    # 나이를 모르면 나이 조건 자체가 없으므로 달라지지 않는다
    assert build_filter(for_child=True) == build_filter()


def test_minor_group_leaves_out_adult_policies():
    """'18세 이하'를 고르면 시작 나이가 18세인 어른 정책은 나오지 않는다."""
    _, params = build_filter(age_group="u19")
    assert params["age_lo"] == 0 and params["age_hi"] == 17
    _, params = build_filter(age_group="19_34")
    assert params["age_hi"] == 34


def test_one_line_skips_bullets_and_empty_summary():
    assert one_line("ㅇ 공연 및 전시 기획사에서 기부한 티켓") == "공연 및 전시 기획사에서 기부한 티켓"
    assert one_line("상동") == ""
    card = retriever.to_card({"id": "a", "name": "n", "agency": "g", "summary": "상동", "content": "본인저축액에 정부 매칭",
                              "has_income_rule": False, "url": "", "collected_at": None})
    assert card["one_line"] == "본인저축액에 정부 매칭"

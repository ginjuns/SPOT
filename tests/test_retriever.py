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
        seen["sql"], seen["params"] = sql, params
        return [{"id": "a", "distance": 0.1}, {"id": "b", "distance": 0.9}]

    monkeypatch.setattr(retriever.db, "query", fake_query)
    monkeypatch.setattr("app.services.embedder.embed_query", lambda text: np.zeros(384, dtype=np.float32))

    rows = retriever.search_semantic("병원비 지원", age_group="75plus", max_distance=0.5)
    assert [r["id"] for r in rows] == ["a"]
    # 지역을 모르면 전국 정책만 찾는다
    assert "region_code IS NULL" in seen["sql"] and "region_code =" not in seen["sql"]
    assert "embedding <=> %(query_vec)s" in seen["sql"]
    assert seen["params"]["age_lo"] == 75 and seen["params"]["limit"] == 8


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

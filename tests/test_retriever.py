from app.services.retriever import AGE_RANGES, build_filter, one_line


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

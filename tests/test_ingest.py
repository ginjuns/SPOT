import json
from pathlib import Path

import ingest

CODES = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "condition_codes.json").read_text(encoding="utf-8")
)

REGIONS = [
    {"code": "11", "sido": "경기도", "sigungu": ""},
    {"code": "11101", "sido": "경기도", "sigungu": "고양시"},
    {"code": "11102", "sido": "경기도", "sigungu": "광주시"},
    {"code": "12", "sido": "부산광역시", "sigungu": ""},
    {"code": "12101", "sido": "부산광역시", "sigungu": "서구"},
    {"code": "12102", "sido": "부산광역시", "sigungu": "강서구"},
    {"code": "13", "sido": "서울특별시", "sigungu": ""},
    {"code": "13101", "sido": "서울특별시", "sigungu": "강서구"},
    {"code": "13102", "sido": "서울특별시", "sigungu": "구로구"},
]


def cond(**values):
    return values


def test_gender():
    assert ingest.map_conditions(cond(JA0101="Y", JA0102="Y"), "", CODES)["gender"] is None
    assert ingest.map_conditions(cond(JA0102="Y"), "", CODES)["gender"] == "F"
    assert ingest.map_conditions(cond(JA0101="Y"), "", CODES)["gender"] == "M"
    assert ingest.map_conditions(cond(), "", CODES)["gender"] is None


def test_age_no_limit_values_become_null():
    r = ingest.map_conditions(cond(JA0110=0, JA0111=120), "", CODES)
    assert r["age_min"] is None and r["age_max"] is None
    r = ingest.map_conditions(cond(JA0110=65, JA0111=120), "", CODES)
    assert r["age_min"] == 65 and r["age_max"] is None


def test_household():
    assert ingest.map_conditions(cond(JA0404="Y", JA0410="Y"), "", CODES)["household"] is None
    assert ingest.map_conditions(cond(), "", CODES)["household"] is None
    assert ingest.map_conditions(cond(JA0404="Y", JA0403="Y"), "", CODES)["household"] == [
        "single_parent", "single"
    ]


def test_income_rule():
    all_y = {c: "Y" for c in CODES["income"]["codes"]}
    assert ingest.map_conditions(all_y, "누구나", CODES)["has_income_rule"] is False
    assert ingest.map_conditions(all_y, "기준 중위소득 50% 이하", CODES)["has_income_rule"] is True
    assert ingest.map_conditions(cond(JA0201="Y"), "", CODES)["has_income_rule"] is True


def test_region_by_type():
    r = ingest.RegionResolver(REGIONS)
    assert r.resolve("보건복지부", "중앙행정기관") is None
    assert r.resolve("경기도", "광역시도") == "11"
    assert r.resolve("경기도 고양시", "시군구") == "11101"
    assert r.resolve("없는도 없는시", "시군구") == "UNKNOWN"
    assert r.resolve("부산광역시교육청", "교육청") == "12"


def test_region_from_name():
    r = ingest.RegionResolver(REGIONS)
    assert r.resolve("고양산업진흥원", "지방출자_출연기관") == "11101"
    assert r.resolve("구로문화재단", "지방출자_출연기관") == "13102"
    assert r.resolve("부산강서구장학회", "지방출자_출연기관") == "12102"
    assert r.resolve("부산서구장학회", "지방출자_출연기관") == "12101"
    # 이름만으로 알 수 없으면 전국으로 두지 않고 UNKNOWN
    assert r.resolve("광주시민장학회", "지방출자_출연기관") == "UNKNOWN"
    assert r.resolve("강서구시설관리공단", "지방공기업") == "UNKNOWN"
    assert r.resolve("재단법인세종문화회관", "지방출자_출연기관") == "UNKNOWN"

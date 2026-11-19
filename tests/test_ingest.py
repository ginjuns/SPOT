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


def test_for_person():
    assert ingest.for_person("개인") is True
    assert ingest.for_person("개인||법인/시설/단체") is True
    assert ingest.for_person("가구||소상공인") is True
    assert ingest.for_person("소상공인||법인/시설/단체") is False
    assert ingest.for_person("법인/시설/단체") is False
    assert ingest.for_person(None) is True      # 값이 없으면 숨기지 않는다


def test_age_from_text_only_when_sure():
    f = ingest.age_from_text
    assert f("56세 C형간염 확진검사비 지원", "국가건강검진(56세)에서 양성인 사람") == (56, 56)
    assert f("중장년 기술창업센터", "만 40세 이상 (예비) 창업자") == (40, None)
    assert f("학교밖청소년 직업역량강화 프로그램", "15세 이상 24세 이하 학교 밖 청소년") == (15, 24)
    assert f("장애인 활동지원(추가)", "○ 6세~65세미만 장애인중 추가지원이 필요한 자") == (6, 64)
    assert f("장애인 활동지원(추가)", "○ 6세이상 활동지원 수급자중 기능제한점수 330점(19세미만 266점) 이상") == (6, None)
    # 나이가 여러 대상 중 하나의 조건이거나 자녀의 나이면 뽑지 않는다
    assert f("국민건강보험료 지원", "○ 만65세 이상 노인세대, 장애인, 한부모, 국가유공자") == (None, None)
    assert f("다자녀 가족카드", "18세 이하 자녀 1명을 포함한 2명 이상의 자녀가 있는 가정") == (None, None)
    assert f("동행센터 방문건강관리", "○ 65세 이상 어르신 ○ 건강 취약계층 : 장애인, 한부모가구") == (None, None)
    assert f("찾아가는 세탁서비스", "기초생활보장 수급가구 중 65세이상노인") == (None, None)
    assert f("아무 정책", None) == (None, None)


def test_documents_drops_empty_markers():
    assert ingest.documents("해당없음") is None
    assert ingest.documents("해당 없음") is None
    assert ingest.documents(" - ") is None
    assert ingest.documents("구비서류 없음.") is None
    assert ingest.documents(None) is None
    assert ingest.documents("신분증, 주민등록등본") == "신분증, 주민등록등본"


def test_widen_age_when_other_age_groups_are_listed():
    f = ingest.widen_for_other_groups
    flu = "○ 어린이: 생후 6개월~14세 어린이 ○ 임신부 ○ 어르신: 65세 이상 어르신"
    assert f(None, 14, flu) == (None, None)            # 코드엔 어린이만 → 어르신도 보이게
    discount = "○ 65세 이상 경로우대자 ○ 만 18세 이하 청소년"
    assert f(65, None, discount) == (None, None)       # 코드엔 어르신만 → 아이 부모도 보이게
    mother = "임신 중이거나 2세 미만 영아를 둔 산모"
    assert f(18, 44, mother) == (18, 44)               # 자녀 나이일 뿐이면 그대로
    assert f(65, None, "65세 이상 어르신") == (65, None)
    assert f(19, 34, "19세 이상 34세 이하 청년") == (19, 34)

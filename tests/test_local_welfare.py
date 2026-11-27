"""정부24에 없는 지자체 복지 정리 (scripts/local_welfare.py) 테스트. 인터넷·DB 없이 돈다."""
import csv
from datetime import date

from scripts import ingest, local_welfare

TODAY = date(2026, 11, 27)


def resolver():
    with open(ingest.config.DATA_DIR / "regions.csv", encoding="utf-8", newline="") as f:
        return ingest.RegionResolver(list(csv.DictReader(f)))


def item(**kw):
    row = {"servId": "WLF00006646", "servNm": "부산광역시 남구 장애인가정 출산 및 양육지원 사업",
           "ctpvNm": "부산광역시", "sggNm": "남구", "lastModYmd": "20261127", "inqNum": "1185",
           "servDtlLink": "https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId=WLF00006646"}
    row.update(kw)
    return row


def detail(**kw):
    row = {"servNm": "부산광역시 남구 장애인가정 출산 및 양육지원 사업", "enfcBgngYmd": "20240701", "enfcEndYmd": "99991231",
           "bizChrDeptNm": "부산광역시 남구 주민복지국 주민복지과", "servDgst": "장애인가정의 안정적 출산과 양육환경 조성",
           "lifeNmArray": "청년, 중장년", "trgterIndvdlNmArray": "장애인", "intrsThemaNmArray": "서민금융",
           "sprtTrgtCn": "부 또는 모가 등록 장애인인 가정", "slctCritCn": "◯ 출산지원금 : 1년 전부터 거주◯ 양육지원금 : 36개월 이하",
           "alwServCn": "출산지원금 1회 1,000천원", "aplyMtdCn": "주소지 동 행정복지센터 방문 신청", "inqNum": "1185",
           "inqplCtadrList": [{"wlfareInfoReldNm": "남구청 장애인복지팀", "wlfareInfoReldCn": "051 607 4336"}]}
    row.update(kw)
    return row


def make(it=None, de=None):
    it = it or item()
    return local_welfare.rows([it], {it["servId"]: de or detail()}, resolver(), "2026-11-27",
                              ingest.age_from_text, TODAY)


def test_row():
    [row] = make()
    assert row["id"] == "WLF00006646" and row["source"] is None   # 지자체 지원이라 정부 지원과 같게 둔다
    assert row["agency"] == "부산광역시 남구" and row["region_code"] == resolver().sigungu[("부산광역시", "남구")]
    assert row["apply_period"] == "상시신청"
    assert row["contact"] == "남구청 장애인복지팀 051 607 4336"
    assert row["criteria"].startswith("○ 출산지원금") and "\n○ 양육지원금" in row["criteria"]
    assert row["url"].startswith("https://www.bokjiro.go.kr/")
    # "서민금융"은 거의 모든 정책에 붙어 있어서 분야로 쓰지 않고 이름으로 정한다
    assert row["category"] == "임신·출산"
    assert row["_rule_tags"] == (["middle", "youth"], ["disabled"], None)
    assert row["for_person"] and row["views"] == 1185


def test_ended_and_missing_detail_are_skipped():
    assert make(de=detail(enfcEndYmd="20251231")) == []
    assert local_welfare.rows([item()], {}, resolver(), "2026-11-27", ingest.age_from_text, TODAY) == []
    [row] = make(de=detail(enfcEndYmd="20261231"))
    assert row["apply_period"] == "2024-07-01 ~ 2026-12-31"


def test_region_falls_back_to_sido():
    r = resolver()
    # 교육청, 제주시처럼 시·군·구 표에 없는 이름은 시·도로 둔다
    assert local_welfare.region_of(item(ctpvNm="충청남도", sggNm="충청남도교육청"), r) == r.sido["충청남도"]
    assert local_welfare.region_of(item(ctpvNm="경기도", sggNm=""), r) == r.sido["경기도"]


def test_income_and_no_life_tags():
    [row] = make(de=detail(lifeNmArray="", trgterIndvdlNmArray="저소득, 장애인", sprtTrgtCn="기준 중위소득 50% 이하"))
    assert row["has_income_rule"]
    assert "_rule_tags" not in row   # 생애주기가 없으면 꼬리표 없이 둔다 (예전 낱말 나이 검사)


def test_same_policy_in_gov24_is_skipped():
    r = resolver()
    nam = r.sigungu[("부산광역시", "남구")]
    gov = [{"name": "출생축하용품 지원", "region_code": nam}, {"name": "보훈명예수당", "region_code": nam[:2]}]
    items = [item(servId="A", servNm="출생축하용품 지원사업"),          # 이름이 거의 같다
             item(servId="B", servNm="남구 국가유공자 보훈명예수당 지원"),  # 시·도 정책에 같은 이름이 있다
             item(servId="C", servNm="청년 자격증 응시료 지원"),           # 정부24에 없다
             item(servId="D", servNm="출생축하용품 지원", ctpvNm="서울특별시", sggNm="종로구")]  # 다른 지역
    assert [i["servId"] for i in local_welfare.new_items(items, r, gov)] == ["C", "D"]

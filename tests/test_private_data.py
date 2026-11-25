"""민간 복지 지원·장학금 정리 (scripts/private_data.py) 테스트. 인터넷·DB 없이 돈다."""
import csv
from datetime import date

from app.services import messenger, retriever
from scripts import ingest, private_data

TODAY = date(2026, 11, 25)


def resolver():
    with open(ingest.config.DATA_DIR / "regions.csv", encoding="utf-8", newline="") as f:
        return ingest.RegionResolver(list(csv.DictReader(f)))


def welfare(**kw):
    row = {"기관명": "삼성꿈장학재단", "사업명": "꿈장학", "사업시작일": "2013-01-01", "사업종료일": "2099-12-31",
           "사업목적": "", "지원대상": " 저소득층 가정의 청소년", "지원내용": " 중학생 180만원",
           "신청방법": " 인터넷 접수: http://www.sdream.or.kr - 공고: 매년 3~4월", "제출서류": "해당없음", "기타": "",
           "생애주기": "아동,청소년", "가구상황": "저소득", "관심주제": "교육"}
    row.update(kw)
    return row


def scholarship(**kw):
    row = {"운영기관명": "롯데장학재단", "상품명": "롯데장학생", "운영기관구분": "기타", "학자금유형구분": "성적우수",
           "대학구분": "4년제(5~6년제포함)", "학년구분": "대학3학기", "학과구분": "제한없음",
           "성적기준 상세내용": "○ 3.5 이상", "소득기준 상세내용": "해당없음", "지원내역 상세내용": "○ 등록금 전액",
           "특정자격 상세내용": "※ 기관확인필요", "지역거주여부 상세내용": "해당없음", "선발방법 상세내용": "서류",
           "선발인원 상세내용": "○ 10명", "자격제한 상세내용": "", "추천필요여부 상세내용": "해당없음",
           "제출서류 상세내용": "○ 신청서", "홈페이지 주소": "www.lottescholarship.or.kr",
           "모집시작일": "2026-03-02", "모집종료일": "2026-03-20"}
    row.update(kw)
    return row


def test_welfare_row():
    [row] = private_data.welfare_rows([welfare()], resolver(), "2026-11-25", TODAY)
    assert row["id"].startswith("PRV") and row["source"] == "민간 지원"
    assert row["category"] == "보육·교육"
    assert row["apply_period"] == "상시신청"            # 2099-12-31 은 기한 없는 사업
    assert row["url"] == "http://www.sdream.or.kr"
    assert row["documents"] is None                     # "해당없음"
    assert row["has_income_rule"] is True and row["region_code"] is None
    assert row["_rule_tags"][0] == ["child"]
    # 같은 기관·사업이면 다시 받아도 같은 ID
    assert private_data.welfare_rows([welfare()], resolver(), "x", TODAY)[0]["id"] == row["id"]


def test_welfare_drops_ended_and_finds_sido_only():
    rows = private_data.welfare_rows([
        welfare(사업명="끝난 사업", 사업종료일="2025-12-31"),
        welfare(기관명="경남은행사랑나눔재단", 사업명="청소년장학사업"),
        welfare(기관명="아산사회복지재단", 사업명="의료비"),       # 충남 아산시가 아니다
    ], resolver(), "x", TODAY)
    assert [r["name"] for r in rows] == ["청소년장학사업", "의료비"]
    assert rows[0]["region_code"] is not None and len(rows[0]["region_code"]) == 2
    assert rows[1]["region_code"] is None


def test_scholarship_rows():
    rows = private_data.scholarship_rows([
        scholarship(),
        scholarship(모집시작일="2025-03-02", 모집종료일="2025-03-20"),     # 같은 장학금의 지난해 공고 → 최근 것만
        scholarship(상품명="아주 옛 공고", 모집종료일="2024-01-10"),        # 끝난 지 오래됨 → 뺀다
        scholarship(상품명="대통령과학장학금", 운영기관구분="한국장학재단"),  # 정부24에 있는 쪽 → 뺀다
        scholarship(상품명="인문100년 장학금", 운영기관구분="공공기관"),      # 정부24 이름과 같음 → 뺀다
        scholarship(운영기관명="영동군민장학회", 상품명="일반장학생", 운영기관구분="지자체(출자출연기관)",
                    모집종료일="2026-12-10"),
    ], resolver(), "x", gov_names=["인문100년장학금"], today=TODAY)
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"롯데장학생", "일반장학생"}
    lotte = by_name["롯데장학생"]
    assert lotte["source"] == "민간 장학금" and lotte["region_code"] is None
    assert lotte["apply_period"].startswith("지난 모집 2026-03-02 ~ 2026-03-20")
    assert lotte["url"] == "https://www.lottescholarship.or.kr"
    assert lotte["_rule_tags"][0] == ["youth"] and "성적 좋은 대학생 장학금" in lotte["_rule_tags"][2]
    local = by_name["일반장학생"]
    assert local["source"] == "지역 장학금" and local["apply_period"] == "2026-03-02 ~ 2026-12-10"
    assert local["region_code"] not in (None, "UNKNOWN") and len(local["region_code"]) == 5


def test_scholarship_with_unknown_place_is_not_national():
    [row] = private_data.scholarship_rows(
        [scholarship(운영기관명="금왕장학회", 학자금유형구분="지역연고", 지역거주여부_상세내용="")],
        resolver(), "x", today=TODAY)
    assert row["region_code"] == "UNKNOWN"


def test_source_reaches_cards_and_messenger():
    card = retriever.to_card({"id": "PRV1", "name": "꿈장학", "agency": "삼성꿈장학재단", "summary": None,
                              "content": "중학생 180만원", "has_income_rule": True, "url": None,
                              "apply_period": "상시신청", "collected_at": "2026-11-25", "source": "민간 지원"})
    assert card["source"] == "민간 지원"
    assert "삼성꿈장학재단 · 민간 지원" in messenger.policy_text(1, card)

"""정책 검색용 꼬리표 테스트 (data/policy_tags.tsv, services/tags.py)."""
from app.services import faq, tags


def test_tag_file_is_loaded():
    table = tags.load()
    assert len(table) > 9000
    ages, special, words = table["SSE000000170"]   # 기초연금
    assert ages == ["elder"] and special == [] and "나라에서 매달 주는 돈" in words


def test_normalize_rules():
    # 효도수당은 모시는 자녀가 받는다
    assert tags.normalize("효도수당 지급", 120, ["elder"], []) == (["middle", "elder"], [])
    assert tags.normalize("장수수당", 120, ["elder"], [])[0] == ["elder"]
    # 자립준비청년은 나이 코드가 17~18세여도 청년이 받는다
    assert tags.normalize("자립준비청년 자립정착금", 18, ["child"], [])[0] == ["child", "youth"]
    # 손주 돌봄은 조부모가 받는다
    assert tags.normalize("손주돌봄 수당", 4, ["child"], [])[0] == ["child", "middle", "elder"]
    # 19~39세 청년 정책은 35~49세에게도
    assert tags.normalize("청년 월세", 39, ["youth"], [])[0] == ["youth", "middle"]
    assert tags.normalize("청년 월세", 34, ["youth"], [])[0] == ["youth"]
    # all 은 혼자
    assert tags.normalize("시민안전보험", None, ["all", "child"], [])[0] == ["all"]


def test_fits():
    assert not tags.fits(["parent"], [], "육아휴직급여", "75plus")
    assert tags.fits(["parent"], [], "육아휴직급여", "35_49")
    assert tags.fits(["all"], [], "에너지바우처", "u19")
    assert tags.fits(["elder"], [], "기초연금", None)                     # 나이를 모르면 거르지 않는다
    assert tags.fits(["child"], [], "아동수당", "65_74", for_child=True)   # 손주를 위한 질문
    # 장애 이야기를 했으면 나이 코드가 좁게 잘못 들어간 장애인 정책도 보여 준다
    assert not tags.fits(["child"], ["disabled"], "장애수당", "50_64")
    assert tags.fits(["child"], ["disabled"], "장애수당", "50_64", context="장애가 있는데 수당 있나요")
    # 이름에 아이 대상이 드러난 장애인 정책은 그대로 나이를 본다
    assert not tags.fits(["child"], ["disabled"], "장애아동수당", "75plus", context="장애 판정을 받았어요")


def test_fits_age_uses_tags_when_present():
    row = {"name": "출산전후휴가 급여", "target": "근로자", "summary": "", "tag_ages": ["pregnant"]}
    assert not faq.fits_age(row, "75plus", False)
    # 꼬리표가 없으면 예전처럼 낱말로 본다 (무리 말이 없으면 통과)
    assert faq.fits_age({**row, "tag_ages": None}, "75plus", False)


def test_is_special_uses_tags():
    # 이름에 대상이 드러나지 않는 전용 정책도 꼬리표로 잡는다
    assert faq.is_special("발달재활서비스", "아이 말이 늦어요", ["disabled"])
    assert not faq.is_special("발달재활서비스", "장애가 있는 아이", ["disabled"])
    assert not faq.is_special("기초연금", "노인 연금", [])

import pytest

from app.services.privacy import MASK, mask


@pytest.mark.parametrize("secret", [
    "900101-1234567",          # 주민등록번호
    "9001011234567",
    "010-1234-5678",           # 휴대폰
    "01012345678",
    "010 1234 5678",
    "011-234-5678",
    "02-123-4567",             # 일반 전화
    "031-1234-5678",
    "hong.gildong@example.com",  # 이메일
    "1234-5678-9012-3456",     # 카드번호
    "110-123-456789",          # 계좌번호
    "12345678901234",          # 긴 숫자
])
def test_secret_is_masked(secret):
    masked, changed = mask(f"제 정보는 {secret} 입니다")
    assert changed
    assert secret not in masked and MASK in masked
    # 번호의 일부도 남지 않아야 한다
    assert not any(ch.isdigit() for ch in masked)


@pytest.mark.parametrize("text", [
    "78살이고 서울 강남구에 살아요",
    "65~74세 지원이 궁금해요",
    "2026-11-14 기준으로 알려 주세요",
    "월 30만원, 1년에 360만원 정도 벌어요",
    "국번 없이 129에 물어봤어요",
    "",
])
def test_ordinary_text_is_kept(text):
    assert mask(text) == (text, False)


def test_several_secrets_in_one_text():
    masked, changed = mask("전화 010-1234-5678, 메일 a@b.co.kr, 주민번호 900101-2234567")
    assert changed and masked.count(MASK) == 3
    assert masked.startswith("전화 ") and "메일" in masked


def test_none_is_safe():
    assert mask(None) == (None, False)

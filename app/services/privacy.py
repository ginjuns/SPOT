"""개인정보 마스킹. LLM에 보내기 전에 번호·이메일을 [가림]으로 바꾼다."""
import re

MASK = "[가림]"
NOTICE = "이름이나 번호는 입력하지 않으셔도 돼요."

SEP = r"[-.\s]?"
PATTERNS = [
    re.compile(r"\d{6}\s?-?\s?[1-4]\d{6}"),                           # 주민등록번호
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),                      # 이메일
    re.compile(rf"01[016789]{SEP}\d{{3,4}}{SEP}\d{{4}}"),             # 휴대폰
    re.compile(rf"0\d{{1,2}}{SEP}\d{{3,4}}{SEP}\d{{4}}"),             # 일반 전화
]
# 카드·계좌번호처럼 보이는 것: 숫자와 줄표(-)가 이어지고 숫자가 10자리 이상
NUMBER_RUN = re.compile(r"\d[\d-]*\d")


def _mask_long_number(match):
    digits = sum(ch.isdigit() for ch in match.group())
    return MASK if digits >= 10 else match.group()


def mask(text):
    """(가린 글, 가린 것이 있었는지)를 돌려준다."""
    if not text:
        return text, False
    masked = text
    for pattern in PATTERNS:
        masked = pattern.sub(MASK, masked)
    masked = NUMBER_RUN.sub(_mask_long_number, masked)
    return masked, masked != text

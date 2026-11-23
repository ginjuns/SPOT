"""정책 검색용 꼬리표 (data/policy_tags.tsv).

정책마다 "누가 받는지(나이 무리)", "특정 대상 전용인지", "어르신이 평소에 할 법한 말"을 미리 붙여 두었다
(2026-11-22~23, Claude가 정책 글을 하나씩 읽고 만듦). 검색에만 쓰고 사용자에게 보이지 않는다.
  - 나이 무리: 정책 이름·지원 대상 글에서 낱말로 찾던 나이 검사(faq.fits_age)를 대신한다.
    낱말 검사는 "청년·어르신" 같은 말이 없으면 그냥 통과시켜서, 75세에게 육아휴직급여가 섞여 나왔다.
  - 특정 대상: 장애인·국가유공자 등 전용 정책을 질문에 그 말이 없으면 뒤로 미룰 때 쓴다.
  - 일상 표현: 의미 검색용 글 뒤에 붙인다 ("나라에서 매달 주는 돈" → 기초연금).
꼬리표가 없는 정책(나중에 새로 생긴 정책)은 예전 낱말 검사를 그대로 쓴다.
"""
import re
from functools import lru_cache

from app import config

AGES = {"child", "youth", "middle", "elder", "pregnant", "parent", "all"}
SPECIALS = {"disabled", "veteran", "defector", "multicultural", "farmer", "injured_worker"}
# 사용자 나이대 → 맞는 나이 무리
USER_GROUPS = {
    "u19": {"child"}, "19_34": {"youth", "pregnant", "parent"}, "35_49": {"middle", "pregnant", "parent"},
    "50_64": {"middle"}, "65_74": {"elder"}, "75plus": {"elder"},
}
# 아이를 위한 질문(부모·조부모가 묻는 것)이면 아이·대학생 자녀·부모 정책도 맞는 것으로 본다
FOR_CHILD_GROUPS = {"child", "youth", "parent"}

FILIAL = re.compile(r"효도|효행|봉양")
LEAVING_CARE = re.compile(r"자립준비|보호종료|자립정착|자립수당|시설\s*퇴소|퇴소\s*아동")
GRANDCHILD = re.compile(r"손주|손자녀|조손")
CHILD_NAME = re.compile(r"아동|아이|어린이|영유아|청소년|학생|자녀")


@lru_cache(maxsize=1)
def load():
    """정책 ID → (나이 무리, 특정 대상, 일상 표현). 파일에 적힌 그대로다 (기준 맞추기 전)."""
    table = {}
    path = config.DATA_DIR / "policy_tags.tsv"
    if not path.exists():
        return table
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        pid, ages, special, words = (line.split("\t") + ["", "", ""])[:4]
        table[pid] = (
            [a for a in ages.split(",") if a in AGES],
            [s for s in special.split(",") if s in SPECIALS],
            [w.strip() for w in words.split(";") if w.strip()],
        )
    return table


def normalize(name, age_max, ages, special):
    """꼬리표를 만든 에이전트마다 기준이 조금씩 갈린 경우를 규칙으로 맞춘다.

    - 효도·효행·봉양 수당: 나이 코드는 모시는 어르신 나이지만 돈은 모시는 자녀가 받는다 → 중장년·어르신
    - 자립준비청년·보호종료 아동: 나이 코드가 17~18세로 들어간 것이 많지만 실제로는 18세 이후 청년이 받는다 → 청년 더함
    - 손주 돌봄·조손 가정: 아이 정책이어도 돈이나 도움은 조부모가 받는다 → 중장년·어르신 더함
    - 청년 정책인데 나이 코드가 39세처럼 35세를 넘으면 중장년(35~49세)에게도 보이게 한다
    - "누구나"(all)는 다른 무리와 함께 적지 않는다
    """
    ages = set(ages)
    if FILIAL.search(name or "") and "장수" not in (name or ""):
        ages = {"middle", "elder"}
    if LEAVING_CARE.search(name or ""):
        ages.add("youth")
    if GRANDCHILD.search(name or ""):
        ages |= {"middle", "elder"}
    if "youth" in ages and age_max is not None and 35 <= age_max <= 49:
        ages.add("middle")
    if "all" in ages:
        ages = {"all"}
    order = ["child", "youth", "middle", "elder", "pregnant", "parent", "all"]
    return [a for a in order if a in ages], sorted(set(special))


def for_row(row):
    """수집할 때 쓰는 값: (나이 무리, 특정 대상, 일상 표현 글). 꼬리표가 없으면 (None, None, None)."""
    found = load().get(row["id"])
    if not found:
        return None, None, None
    ages, special, words = found
    ages, special = normalize(row.get("name"), row.get("age_max"), ages, special)
    return ages, special, " ".join(words) or None


def fits(tag_ages, tag_special, name, age_group, for_child=False, context=""):
    """꼬리표로 본 나이 무리가 사용자 나이대와 맞는지. 나이를 모르면 True.

    장애 이야기를 한 질문이면 장애인 정책은 나이와 상관없이 보여 준다
    (장애는 나이와 상관이 없는데, 나이 코드가 0~18세나 65세 이상처럼 좁게 잘못 들어간 장애인 정책이 있다).
    """
    if not age_group or not tag_ages:
        return True
    # 이름에 아이 대상이 드러난 정책("장애아동수당")은 빼고 (75세 장애 질문에 장애아동수당이 나왔다)
    if ("장애" in (context or "") and ("disabled" in (tag_special or []) or "장애" in (name or ""))
            and not CHILD_NAME.search(name or "")):
        return True
    if "all" in tag_ages:
        return True
    allowed = USER_GROUPS[age_group] | (FOR_CHILD_GROUPS if for_child else set())
    return bool(set(tag_ages) & allowed)

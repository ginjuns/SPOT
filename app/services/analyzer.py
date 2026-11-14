"""질문 분석: 사용자 글 → 구조화된 조건(JSON).

Groq(작은 모델)에 물어보고, 안 되면 규칙 기반(data/keywords.json)으로 대신한다.
LLM이 준 값은 그대로 믿지 않고 정해진 값인지 코드로 다시 확인한다.
"""
import csv
import json
import re
from collections import Counter
from functools import lru_cache

from app import config
from app.services import llm

NEEDS = ["의료비", "생활비", "주거", "일자리", "돌봄", "교육", "출산·육아", "장애", "기타"]
HOUSEHOLDS = {"single", "single_parent", "multi_child", "multicultural", "no_house"}
SEARCH_TEXT_LIMIT = 80   # LLM이 다듬은 문장의 최대 길이

PROMPT = (config.BASE_DIR / "app" / "prompts" / "analyze.txt").read_text(encoding="utf-8")
KEYWORDS = json.loads((config.DATA_DIR / "keywords.json").read_text(encoding="utf-8"))


# ---------- 나이 ----------

def age_to_group(age):
    """정확한 나이 → 나이대."""
    if age is None or not 0 <= age <= 120:
        return None
    for limit, group in [(18, "u19"), (34, "19_34"), (49, "35_49"), (64, "50_64"), (74, "65_74")]:
        if age <= limit:
            return group
    return "75plus"


def decade_to_group(decade):
    """"70대"처럼 말한 경우. 두 나이대에 걸치면(30대, 60대, 70대) 정하지 않고 되묻게 둔다."""
    if decade is None or decade < 0 or decade > 110:
        return None
    low, high = age_to_group(decade), age_to_group(min(decade + 9, 120))
    return low if low == high else None


# ---------- 지역 ----------

# 줄임말·옛 이름 → 지금 시·도 이름
SIDO_ALIASES = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
    "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시", "제주": "제주특별자치도",
    "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
    "경북": "경상북도", "경남": "경상남도", "전북": "전북특별자치도", "전라북도": "전북특별자치도",
    "전남": "전남광주통합특별시", "전라남도": "전남광주통합특별시", "광주": "전남광주통합특별시",
}
# 규칙 기반 분석(문장 전체를 훑을 때)에서 쓰는 줄임말. 다른 뜻으로 잘 안 쓰이는 것만.
SAFE_ALIASES = {"서울", "부산", "대구", "인천", "울산", "제주"}


@lru_cache(maxsize=1)
def _regions():
    with open(config.DATA_DIR / "regions.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    sido = {r["sido"]: r["code"] for r in rows if not r["sigungu"]}
    sigungu = {(r["sido"], r["sigungu"]): r["code"] for r in rows if r["sigungu"]}
    return sido, sigungu


def _longest_unique(hits):
    """찾은 (이름, 코드) 중 가장 긴 이름. 같은 이름이 여러 곳이면 정하지 않는다."""
    if not hits:
        return None
    longest = max(len(name) for name, _ in hits)
    codes = {code for name, code in hits if len(name) == longest}
    return codes.pop() if len(codes) == 1 else None


def resolve_region(text, strict=False):
    """지역을 가리키는 말 → region_code. 못 정하면 None.

    strict=True 는 문장 전체를 훑을 때 쓴다: "고령자"를 고령군으로 잡지 않도록
    "강남구"처럼 끝 글자까지 맞는 이름과 헷갈리지 않는 시·도 줄임말만 쓴다.
    """
    if not text:
        return None
    sido_codes, sigungu_codes = _regions()
    t = re.sub(r"\s+", "", text)

    # 1) 시·도: 정식 이름 또는 줄임말 중 문장에서 가장 먼저 나오는 것
    found = [(t.find(name), name) for name in sido_codes if name in t]
    for alias, full in SIDO_ALIASES.items():
        if alias in t and full in sido_codes and (not strict or alias in SAFE_ALIASES):
            found.append((t.find(alias), full))
    sido = min(found)[1] if found else None

    # 2) 시·군·구: "강남구" 그대로, 또는 (strict 가 아니면) "강남"처럼 끝 글자를 뺀 말
    def hits(names):
        out = [(g, code) for g, code in names if g in t]
        if not strict:
            out += [(g[:-1], code) for g, code in names if len(g) >= 3 and g[:-1] in t]
        return out

    if sido:
        inside = [(g, code) for (s, g), code in sigungu_codes.items() if s == sido]
        return _longest_unique(hits(inside)) or sido_codes[sido]
    return _longest_unique(hits([(g, code) for (_, g), code in sigungu_codes.items()]))


# ---------- LLM 분석 ----------

def _as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _clean_text(value):
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else None


def normalize(raw, message):
    """LLM이 준 JSON을 정해진 값으로만 걸러서 돌려준다."""
    region_text = _clean_text(raw.get("region_text"))
    search_text = _clean_text(raw.get("search_text")) or _clean_text(message) or ""
    return {
        "need": raw.get("need") if raw.get("need") in NEEDS else "기타",
        "age_group": age_to_group(_as_int(raw.get("age"))) or decade_to_group(_as_int(raw.get("age_decade"))),
        "gender": raw.get("gender") if raw.get("gender") in ("M", "F") else None,
        "region_text": region_text,
        "region_code": resolve_region(region_text),
        "household": raw.get("household") if raw.get("household") in HOUSEHOLDS else None,
        "search_text": search_text[:SEARCH_TEXT_LIMIT],
    }


def build_user_prompt(message, history):
    lines = []
    if history:
        lines.append("<이전 대화>")
        for turn in history[-6:]:
            who = "사용자" if turn.get("role") == "user" else "안내"
            lines.append(f"{who}: {turn.get('text', '')}")
        lines.append("</이전 대화>")
    lines.append(f"<사용자 글>{message}</사용자 글>")
    return "\n".join(lines)


# ---------- 규칙 기반 분석 ----------

def analyze_by_rules(message):
    """LLM 없이 낱말로만 분석한다. 확실한 것만 채운다."""
    def pick(table):
        counts = Counter({key: sum(w in message for w in words) for key, words in table.items()})
        key, n = counts.most_common(1)[0]
        return key if n > 0 else None

    age = re.search(r"(\d{1,3})\s*(?:살|세)", message)
    decade = re.search(r"(\d{1,2}0)\s*대", message)
    return {
        "need": pick(KEYWORDS["need"]) or "기타",
        "age_group": (age_to_group(int(age.group(1))) if age else None)
        or (decade_to_group(int(decade.group(1))) if decade else None),
        "gender": pick(KEYWORDS["gender"]),
        "region_text": None,
        "region_code": resolve_region(message, strict=True),
        "household": pick(KEYWORDS["household"]),
        "search_text": " ".join(message.split()),
    }


def with_question(search_text, message):
    """검색 문장 = 다듬은 문장 + 원래 질문.

    다듬은 문장만 쓰면 질문의 뜻이 빠질 때가 있고("다시 취직"이 사라짐), 질문만 쓰면 군말 때문에
    엉뚱한 정책이 가까워진다. 시나리오 평가에서 둘을 이어 붙인 것이 가장 잘 맞았다 (30개 중 26개).
    """
    question = " ".join(message.split())
    if not search_text or search_text == question[:SEARCH_TEXT_LIMIT]:
        return question
    return f"{search_text}. {question}"


def analyze(message, history=None):
    """사용자 글을 분석한다. message 와 history 는 개인정보를 가린 뒤에 넘겨야 한다.

    돌려주는 dict 의 "source" 는 "llm" 또는 "rules" (LLM이 안 돼서 규칙으로 대신한 경우).
    """
    try:
        raw = llm.chat_json(config.GROQ_MODEL_ANALYZE, PROMPT, build_user_prompt(message, history))
        result = normalize(raw, message)
        result["search_text"] = with_question(result["search_text"], message)
        return {**result, "source": "llm"}
    except llm.LLMError:
        return {**analyze_by_rules(message), "source": "rules"}

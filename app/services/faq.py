"""자주 묻는 질문으로 AI 없이 답하기 (키워드 방식).

data/faq.json 에 주제마다 "확실한 낱말"(keys)과 "보여 줄 정책 이름 낱말"(names)을 적어 둔다.
질문에 딱 한 주제의 낱말만 들어 있으면, 그 주제의 이름 낱말이 들어간 정책을 사용자 조건(나이·지역 등)으로
걸러서 보여 준다. 이때 AI(질문 분석·답변 생성)를 한 번도 부르지 않는다. 카드 내용은 모두 DB 값 그대로다.
두 주제 이상이 걸리거나 아무것도 안 걸리면 None 을 돌려주고, 부르는 쪽이 지금처럼 AI로 처리한다.

처음에는 질문 문장끼리 의미 거리(임베딩)로 비교하려 했지만, 말투가 비슷하면 내용이 달라도 가깝게 나와서
("암 치료비" ↔ "난임 치료비") 맞는 것만큼 틀렸다 (2026-11-21, 질문 412개: 거리 0.08 기준 맞음 60 / 틀림 78).
정책은 ID가 아니라 이름 낱말로 찾으므로, 지역판 정책도 같이 나오고 정책을 다시 수집해도 깨지지 않는다.
"""
import json

from app import config, db
from app.services import retriever

TOPICS = json.loads((config.DATA_DIR / "faq.json").read_text(encoding="utf-8"))
BY_ID = {t["id"]: t for t in TOPICS}
NATION_LIMIT = 3   # 전국 정책 몇 건
LOCAL_LIMIT = 2    # 사는 지역 정책 몇 건
# 여러 가지를 이어서 묻는 말. 한 주제 낱말만 걸려도 다른 걱정이 같이 있으니 AI가 판단한다
# ("아들이 취직을 못 해서 걱정이에요 그리고 저도 아파요").
SEVERAL_THINGS = ["그리고", "게다가", "뿐만 아니라", "그 밖에도", "그밖에도"]
RESULT_TEXT ="'{title}' 관련 지원을 찾았어요. 자격은 신청하는 곳에서 최종 확인해 주세요."


def _squash(text):
    """띄어쓰기를 빼고 영문은 소문자로 ("독감 주사" = "독감주사")."""
    return "".join((text or "").split()).lower()


# 낱말 하나 = 띄어쓰기를 뺀 조각 목록. "일하다+다쳤"처럼 +로 이으면 조각이 모두 있어야 걸린다.
_KEYS = [(t["id"], [[_squash(p) for p in k.split("+")] for k in t["keys"]]) for t in TOPICS]


def matched_topics(message):
    """질문에 낱말이 들어 있는 주제 ID 목록."""
    text = _squash(message)
    return [tid for tid, keys in _KEYS if any(all(p in text for p in parts) for parts in keys)]


def match(message):
    """질문에 걸린 주제가 하나면 그 주제. 없거나 여럿이면 None (AI가 판단한다).

    여럿이 걸리면 단계(level)가 가장 높은 주제만 남긴다: -1 아주 넓음("병원비") < 0 넓음 < 1 보통(기본) < 2 좁음.
    "무릎 수술비"는 "큰 병원비"(넓음)와 "무릎 관절 수술"(보통)에 둘 다 걸리는데, 좁은 쪽이 맞다.
    """
    hits = matched_topics(message)
    if not hits or any(w in message for w in SEVERAL_THINGS):
        return None
    top = max(BY_ID[h].get("level", 1) for h in hits)
    hits = [h for h in hits if BY_ID[h].get("level", 1) == top]
    return BY_ID[hits[0]] if len(hits) == 1 else None


def name_filter(names):
    """정책 이름에 낱말 중 하나라도 들어 있는지 보는 SQL 조각."""
    params = {f"faq{i}": retriever.like_pattern(n) for i, n in enumerate(names)}
    return " OR ".join(f"name ILIKE %({k})s" for k in params), params


def name_order(params, count):
    """앞에 적은 이름 낱말에 맞는 정책을 먼저 ("휴양림" 질문에 산림복지 일자리보다 휴양림 정책)."""
    cases = " ".join(f"WHEN name ILIKE %(faq{i})s THEN {i}" for i in range(count))
    return f"CASE {cases} ELSE {count} END"


def policies(topic, conditions):
    """주제의 이름 낱말이 들어간 정책을 조건으로 걸러서: 전국 정책(조회수 순) + 사는 지역 정책."""
    where, params = retriever.build_filter(
        conditions.get("age_group"), conditions.get("gender"), conditions.get("region_code"),
        conditions.get("household"), for_child=bool(conditions.get("for_child")),
    )
    names, name_params = name_filter(topic["names"])
    params.update(name_params)
    order = name_order(params, len(topic["names"]))
    base = f"SELECT {retriever.CARD_COLUMNS} FROM policy WHERE for_person AND {where} AND ({names})"
    rows = db.query(f"{base} AND region_code IS NULL ORDER BY {order}, views DESC, name, id LIMIT {NATION_LIMIT}",
                    params)
    if conditions.get("region_code"):
        rows += db.query(
            f"{base} AND region_code IS NOT NULL "
            f"ORDER BY length(region_code) DESC, {order}, views DESC, name, id "
            f"LIMIT {LOCAL_LIMIT}", params)
    return [retriever.to_card(r) for r in rows]


def result_text(topic):
    return RESULT_TEXT.format(title=topic["title"])

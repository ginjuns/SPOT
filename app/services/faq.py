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


# ---------- 나이 무리 검사 ----------
# DB의 나이 칸은 일부러 느슨하게 채웠다 (잘못 뽑으면 받을 수 있는 사람에게 숨겨지므로, ingest.py age_from_text).
# AI 경로에서는 답변 AI가 지원 대상 글을 읽고 나이가 안 맞는 정책을 뺐지만, 이 경로에는 AI가 없어서
# 75세에게 "학교 급식비", "난임 부부 상담"이 나왔다 (2026-11-21 카카오톡). 그래서 정책 이름과 지원 대상 글
# 앞부분에 나이 무리를 뜻하는 말이 있으면, 사용자 나이대와 맞는 무리일 때만 보여 준다.
GROUP_WORDS = {
    "youth": ["청년", "대학생", "대학원생", "대학(원)생"],   # "대학생"의 "학생"이 아이 무리로 잡히지 않게 먼저 지운다
    "child": ["아동", "어린이", "영유아", "영아", "유아", "초등", "중학생", "고등학생", "고교생", "청소년", "학생",
              "소년소녀", "자녀"],
    "elder": ["노인", "어르신", "경로", "고령"],
    "pregnant": ["임산부", "임신부", "산모", "난임", "임신"],
}
USER_GROUPS = {   # 나이대 → 맞는 무리
    "u19": {"child"}, "19_34": {"youth", "pregnant"}, "35_49": {"pregnant"},
    "50_64": set(), "65_74": {"elder"}, "75plus": {"elder"},
}
HEAD_LENGTH = 80   # 지원 대상 글에서 볼 앞부분 글자 수 (뒤쪽은 예외·제외 조건이 많다)
# 누구나 받는다는 말. 이런 말이 있으면 뒤에 나오는 무리는 우대 대상일 뿐이다
# ("만 19세 이상의 국민 - 청년층: ..." K-패스가 청년 전용으로 잘못 보였다).
EVERYONE_WORDS = ["국민", "누구나", "전 연령", "제한 없", "제한없"]


def age_groups(name, target):
    """정책 이름 + 지원 대상 글 앞부분에 나오는 나이 무리. 누구나 받는 정책이면 빈 집합."""
    text = (name or "") + " " + " ".join((target or "").split())[:HEAD_LENGTH]
    if any(w in text for w in EVERYONE_WORDS):
        return set()
    found = set()
    for group, words in GROUP_WORDS.items():
        if any(w in text for w in words):
            found.add(group)
            for w in words:
                text = text.replace(w, " ")
    return found


def fits_age(row, age_group, for_child):
    """나이 무리가 적혀 있으면 사용자 나이대와 맞는 무리일 때만 True. 적혀 있지 않거나 나이를 모르면 True."""
    if not age_group:
        return True
    groups = age_groups(row["name"], row.get("target"))
    if not groups:
        return True
    allowed = USER_GROUPS[age_group] | ({"child"} if for_child else set())
    return bool(groups & allowed)


def policies(topic, conditions):
    """주제의 이름 낱말이 들어간 정책을 조건으로 걸러서: 전국 정책 3건 + 사는 지역 정책 2건.

    - 순서: 앞에 적은 이름 낱말 → 주제 검색 문장과 뜻이 가까운 순 (조회수 순이면 "국토교통부 전세보증금"처럼
      이름에 낱말만 우연히 들어간 정책이 위로 올라왔다)
    - 뜻이 먼 정책(MAX_DISTANCE 초과)은 이름 낱말이 맞아도 뺀다
    - 나이 무리가 맞지 않는 정책은 뺀다 (fits_age)
    """
    from app.services.analyzer import expand
    from app.services.embedder import embed_query

    where, params = retriever.build_filter(
        conditions.get("age_group"), conditions.get("gender"), conditions.get("region_code"),
        conditions.get("household"), for_child=bool(conditions.get("for_child")),
    )
    names, name_params = name_filter(topic["names"])
    params.update(name_params)
    params["v"] = embed_query(expand(topic["search_text"]))
    params["max_distance"] = config.MAX_DISTANCE
    order = name_order(params, len(topic["names"]))
    base = (f"SELECT {retriever.CARD_COLUMNS}, target FROM policy WHERE for_person AND {where} AND ({names}) "
            "AND embedding <=> %(v)s <= %(max_distance)s")
    distance = "embedding <=> %(v)s"

    def pick(rows, limit):
        age, for_child = conditions.get("age_group"), bool(conditions.get("for_child"))
        return [r for r in rows if fits_age(r, age, for_child)][:limit]

    # 나이 무리 검사로 빠질 몫까지 넉넉히 가져온 뒤 고른다
    rows = pick(db.query(f"{base} AND region_code IS NULL ORDER BY {order}, {distance}, id LIMIT 20", params),
                NATION_LIMIT)
    if conditions.get("region_code"):
        rows += pick(db.query(
            f"{base} AND region_code IS NOT NULL "
            f"ORDER BY length(region_code) DESC, {order}, {distance}, id LIMIT 20", params), LOCAL_LIMIT)
    return [retriever.to_card(r) for r in rows]


def result_text(topic):
    return RESULT_TEXT.format(title=topic["title"])

"""조건 필터 + 의미 검색."""
from app import config, db

PAGE_SIZE = 10
CANDIDATE_LIMIT = 8  # 의미 검색으로 고르는 후보 수

# 의미 검색 후보에 필요한 열 (답변 생성에 지원 대상·지원 내용을 쓴다)
CANDIDATE_COLUMNS = "id, name, agency, summary, target, content, has_income_rule, url, collected_at"

# 나이대 → (가장 어린 나이, 가장 많은 나이)
AGE_RANGES = {
    "u19": (0, 18),
    "19_34": (19, 34),
    "35_49": (35, 49),
    "50_64": (50, 64),
    "65_74": (65, 74),
    "75plus": (75, 120),
}

CARD_COLUMNS = "id, name, agency, summary, has_income_rule, url, collected_at"


CHILD_AGE_MAX = 18


def build_filter(age_group=None, gender=None, region_code=None, household=None, for_child=False):
    """조건을 SQL WHERE 절과 값으로 바꾼다. 조건이 없는 항목은 넣지 않는다 (지역만 예외).

    for_child: 부모가 아이를 위한 지원을 묻는 경우. 아이 대상 정책(대상 나이가 18세 이하)은
    부모 나이로 걸러지지 않게 나이 조건에서 빼 준다.
    """
    where, params = [], {}
    if region_code:
        where.append(
            "(region_code IS NULL OR region_code = %(region)s OR region_code = LEFT(%(region)s, 2))"
        )
        params["region"] = region_code
    else:
        # 지역을 모르면 전국 정책만. 조건을 빼 버리면 다른 지역의 정책이 섞여 나온다.
        where.append("region_code IS NULL")
    if age_group:
        params["age_lo"], params["age_hi"] = AGE_RANGES[age_group]
        age = "(age_min IS NULL OR age_min <= %(age_hi)s) AND (age_max IS NULL OR age_max >= %(age_lo)s)"
        where.append(f"(({age}) OR age_max <= {CHILD_AGE_MAX})" if for_child else f"({age})")
    if gender:
        where.append("(gender IS NULL OR gender = %(gender)s)")
        params["gender"] = gender
    if household:
        where.append("(household IS NULL OR %(household)s = ANY(household))")
        params["household"] = household
    return " AND ".join(where), params


def one_line(summary, limit=70):
    """LLM을 쓰지 않는 카드의 한 줄 요약: DB 요약의 첫 줄 앞부분."""
    if not summary:
        return ""
    line = summary.strip().split("\n")[0].lstrip("○-·ㆍ* ").strip()
    if len(line) <= limit:
        return line
    cut = line[:limit]
    if " " in cut[limit // 2:]:
        cut = cut[:cut.rindex(" ")]
    return cut + "…"


def to_card(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "agency": row["agency"],
        "one_line": one_line(row["summary"]),
        "has_income_rule": row["has_income_rule"],
        "url": row["url"],
        "collected_at": row["collected_at"],
    }


def drop_far(rows, max_distance):
    """거리가 기준값보다 먼 후보는 버린다."""
    return [r for r in rows if r["distance"] <= max_distance]


def search_semantic(search_text, age_group=None, gender=None, region_code=None, household=None,
                    limit=CANDIDATE_LIMIT, max_distance=None, for_child=False):
    """채팅 검색: 조건으로 거른 정책 중에서 질문과 뜻이 가까운 순으로 고른다.

    돌려주는 행에는 distance(코사인 거리, 작을수록 가까움)가 들어 있다.
    max_distance 를 주지 않으면 config.MAX_DISTANCE 를 쓴다.
    """
    from app.services.embedder import embed_query  # 모델은 처음 쓸 때만 불러온다

    where, params = build_filter(age_group, gender, region_code, household, for_child=bool(for_child))
    params["query_vec"] = embed_query(search_text)
    params["limit"] = limit
    rows = db.query(
        f"SELECT {CANDIDATE_COLUMNS}, embedding <=> %(query_vec)s AS distance "
        f"FROM policy WHERE {where} AND embedding IS NOT NULL "
        "ORDER BY distance, id LIMIT %(limit)s",
        params,
    )
    return drop_far(rows, config.MAX_DISTANCE if max_distance is None else max_distance)


def search_by_conditions(age_group=None, gender=None, region_code=None, household=None, page=1):
    """버튼 조회: 조건 필터만 사용. 시·군·구 정책 → 시·도 정책 → 전국 정책 → 정책명순."""
    where, params = build_filter(age_group, gender, region_code, household)
    total = db.query(f"SELECT count(*) AS n FROM policy WHERE {where}", params)[0]["n"]
    params["limit"] = PAGE_SIZE
    params["offset"] = (page - 1) * PAGE_SIZE
    rows = db.query(
        f"SELECT {CARD_COLUMNS} FROM policy WHERE {where} "
        "ORDER BY CASE WHEN region_code IS NULL THEN 2 WHEN length(region_code) = 2 THEN 1 ELSE 0 END, "
        "name, id LIMIT %(limit)s OFFSET %(offset)s",
        params,
    )
    return {"total": total, "policies": [to_card(r) for r in rows]}

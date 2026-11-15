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


def build_filter(age_group=None, gender=None, region_code=None, household=None, for_child=False,
                 all_regions=False):
    """조건을 SQL WHERE 절과 값으로 바꾼다. 조건이 없는 항목은 넣지 않는다 (지역만 예외).

    for_child: 부모가 아이를 위한 지원을 묻는 경우. 아이 대상 정책(대상 나이가 18세 이하)은
    부모 나이로 걸러지지 않게 나이 조건에서 빼 준다.
    all_regions: 지역을 고르지 않았을 때 모든 지역에서 찾는다 (낱말로 찾을 때만 쓴다).
    """
    where, params = [], {}
    if region_code:
        where.append(
            "(region_code IS NULL OR region_code = %(region)s OR region_code = LEFT(%(region)s, 2))"
        )
        params["region"] = region_code
    elif not all_regions:
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
    return " AND ".join(where) or "TRUE", params


KEYWORD_COLUMNS = ("name", "summary", "target", "content")   # 낱말을 찾아보는 열
MAX_KEYWORDS = 5


def keyword_terms(text):
    """검색창에 적은 글을 띄어쓰기로 나눈 낱말 목록 (최대 5개)."""
    return (text or "").split()[:MAX_KEYWORDS]


def like_pattern(term):
    """낱말을 LIKE 검색용 글로 바꾼다. %, _ 는 글자 그대로 찾는다."""
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


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


def search_by_conditions(age_group=None, gender=None, region_code=None, household=None, page=1,
                         category=None, keyword=None):
    """직접 찾기 (LLM을 쓰지 않는다): 조건 필터 + 분야 + 낱말.

    순서: (낱말이 있으면 이름이 낱말과 똑같은 정책 → 이름에 낱말이 있는 정책 →)
          시·군·구 정책 → 시·도 정책 → 전국 정책 → 정책명순.
    낱말은 정책 이름·요약·지원 대상·지원 내용에서 찾고, 여러 낱말이면 모두 들어 있는 정책만 고른다.
    낱말로 찾는데 지역을 고르지 않았으면 모든 지역에서 찾고, 전국 정책을 먼저 보여 준다.
    """
    terms = keyword_terms(keyword)
    where, params = build_filter(age_group, gender, region_code, household, all_regions=bool(terms))
    if category:
        where += " AND category = %(category)s"
        params["category"] = category
    order = ""
    if terms:
        for i, term in enumerate(terms):
            params[f"kw{i}"] = like_pattern(term)
            where += " AND (" + " OR ".join(f"{col} ILIKE %(kw{i})s" for col in KEYWORD_COLUMNS) + ")"
        in_name = " AND ".join(f"name ILIKE %(kw{i})s" for i in range(len(terms)))
        order = f"CASE WHEN name = %(kw_all)s THEN 0 WHEN {in_name} THEN 1 ELSE 2 END, "
    total = db.query(f"SELECT count(*) AS n FROM policy WHERE {where}", params)[0]["n"]
    if terms:
        params["kw_all"] = " ".join(terms)
    # 사는 곳을 골랐으면 가까운 지역 정책부터, 고르지 않았으면 전국 정책부터
    if region_code:
        order += "CASE WHEN region_code IS NULL THEN 2 WHEN length(region_code) = 2 THEN 1 ELSE 0 END, "
    else:
        order += "CASE WHEN region_code IS NULL THEN 0 ELSE 1 END, "
    params["limit"] = PAGE_SIZE
    params["offset"] = (page - 1) * PAGE_SIZE
    rows = db.query(
        f"SELECT {CARD_COLUMNS} FROM policy WHERE {where} "
        f"ORDER BY {order}name, id LIMIT %(limit)s OFFSET %(offset)s",
        params,
    )
    return {"total": total, "policies": [to_card(r) for r in rows]}

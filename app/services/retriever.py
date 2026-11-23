"""조건 필터 + 의미 검색."""
from app import config, db

PAGE_SIZE = 10
CANDIDATE_LIMIT = 8  # 의미 검색으로 고르는 후보 수

# 의미 검색 후보에 필요한 열 (답변 생성에 지원 대상·지원 내용을 쓴다)
CANDIDATE_COLUMNS = ("id, name, agency, summary, target, content, has_income_rule, url, apply_period, "
                     "collected_at, region_code, tag_ages, tag_special")

# 나이대 → (가장 어린 나이, 가장 많은 나이)
AGE_RANGES = {
    "u19": (0, 18),
    "19_34": (19, 34),
    "35_49": (35, 49),
    "50_64": (50, 64),
    "65_74": (65, 74),
    "75plus": (75, 120),
}

CARD_COLUMNS = "id, name, agency, summary, has_income_rule, url, apply_period, collected_at"


CHILD_AGE_MAX = 18
# 나이대 "18세 이하"를 골랐을 때 보여 줄 정책의 시작 나이 상한. 18로 두면 "18세 이상" 어른 정책이
# 모두 걸려서(산후조리비, 농기계 수리비 등) 17로 둔다. 18세가 받을 수 있는 어른 정책은 빠지지만,
# 미성년자에게 어른 정책이 쏟아지는 것보다 낫다.
MINOR_START_MAX = 17


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
        if age_group == "u19":
            params["age_hi"] = MINOR_START_MAX
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
        "apply_period": row.get("apply_period"),   # 신청 기간 ("상시신청", "매년 1월" 등)
        "collected_at": row["collected_at"],
    }


def drop_far(rows, max_distance):
    """거리가 기준값보다 먼 후보는 버린다."""
    return [r for r in rows if r["distance"] <= max_distance]


LOCAL_SLOTS = 3    # 사는 곳을 골랐을 때 후보에 꼭 넣을 지역(시·도, 시·군·구) 정책 수
EXTRA_FETCH = 12   # keep 으로 빠질 몫까지 넉넉히 가져온다


def search_semantic(search_text, age_group=None, gender=None, region_code=None, household=None,
                    limit=CANDIDATE_LIMIT, max_distance=None, for_child=False, keep=None):
    """채팅 검색: 조건으로 거른 정책 중에서 질문과 뜻이 가까운 순으로 고른다.

    돌려주는 행에는 distance(코사인 거리, 작을수록 가까움)가 들어 있다.
    max_distance 를 주지 않으면 config.MAX_DISTANCE 를 쓴다.
    keep: 행을 받아 남길지 정하는 함수 (채팅은 나이 무리 검사 faq.fits_age 를 준다).
    사는 곳을 골랐으면 지역 정책을 LOCAL_SLOTS 건까지 꼭 넣는다. 전국 정책이 많은 주제에서
    가까운 순으로만 고르면 구청·시청 정책이 후보에 아예 들지 못했다. 이때 가장 먼 전국 정책이 빠진다.
    """
    from app.services.embedder import embed_query  # 모델은 처음 쓸 때만 불러온다

    where, params = build_filter(age_group, gender, region_code, household, for_child=bool(for_child))
    params["query_vec"] = embed_query(search_text)
    max_distance = config.MAX_DISTANCE if max_distance is None else max_distance

    def fetch(extra_where, count):
        rows = db.query(
            f"SELECT {CANDIDATE_COLUMNS}, embedding <=> %(query_vec)s AS distance "
            f"FROM policy WHERE {where}{extra_where} AND embedding IS NOT NULL "
            f"ORDER BY distance, id LIMIT {int(count)}",
            params,
        )
        return [r for r in drop_far(rows, max_distance) if keep is None or keep(r)]

    rows = fetch("", limit + EXTRA_FETCH)[:limit]
    if not region_code:
        return rows
    local_count = sum(r.get("region_code") is not None for r in rows)
    if local_count >= LOCAL_SLOTS:
        return rows
    ids = {r["id"] for r in rows}
    local = [r for r in fetch(" AND region_code IS NOT NULL", LOCAL_SLOTS + EXTRA_FETCH) if r["id"] not in ids]
    local = local[:LOCAL_SLOTS - local_count]
    if not local:
        return rows
    # 가장 먼 전국 정책부터 지역 정책에 자리를 내준다
    nation = [r for r in rows if r.get("region_code") is None]
    drop = {r["id"] for r in nation[::-1][:max(0, len(rows) + len(local) - limit)]}
    merged = [r for r in rows if r["id"] not in drop] + local
    return sorted(merged, key=lambda r: (r["distance"], r["id"]))


def search_by_conditions(age_group=None, gender=None, region_code=None, household=None, page=1,
                         category=None, keyword=None, related=None, include_org=False):
    """직접 찾기 (LLM을 쓰지 않는다): 조건 필터 + 분야 + 낱말.

    순서: (낱말이 있으면 이름이 낱말과 똑같은 정책 → 이름에 낱말이나 비슷한 말이 있는 정책 →)
          시·군·구 정책 → 시·도 정책 → 전국 정책 → 조회수가 많은 순 → 정책명순.
    낱말은 정책 이름·요약·지원 대상·지원 내용에서 찾고, 여러 낱말이면 모두 들어 있는 정책만 고른다.
    낱말로 찾는데 지역을 고르지 않았으면 모든 지역에서 찾고, 전국 정책을 먼저 보여 준다.
    related: 낱말과 비슷한 정책 이름 낱말 ("난방비" → "에너지바우처"). 이름에 이 말이 있는 정책도 함께 찾는다.
    include_org: False 면 개인·가구가 받는 지원만 보여 주고, 뺀 건수를 hidden_org 로 알려 준다.
    """
    terms = keyword_terms(keyword)
    related = list(related or []) if terms else []
    where, params = build_filter(age_group, gender, region_code, household, all_regions=bool(terms))
    if category:
        where += " AND category = %(category)s"
        params["category"] = category
    order = ""
    if terms:
        match = []
        for i, term in enumerate(terms):
            params[f"kw{i}"] = like_pattern(term)
            match.append("(" + " OR ".join(f"{col} ILIKE %(kw{i})s" for col in KEYWORD_COLUMNS) + ")")
        in_name = " AND ".join(f"name ILIKE %(kw{i})s" for i in range(len(terms)))
        if related:
            for i, word in enumerate(related):
                params[f"rel{i}"] = like_pattern(word)
            rel_name = " OR ".join(f"name ILIKE %(rel{i})s" for i in range(len(related)))
            where += f" AND (({' AND '.join(match)}) OR {rel_name})"
            # 비슷한 말이 이름에 있는 정책도 낱말이 이름에 있는 정책과 같은 순위로 둔다
            # (그래야 "난방비"를 찾았을 때 전국 정책인 "에너지바우처"가 위쪽에 나온다)
            order = f"CASE WHEN name = %(kw_all)s THEN 0 WHEN ({in_name}) OR {rel_name} THEN 1 ELSE 2 END, "
        else:
            where += " AND " + " AND ".join(match)
            order = f"CASE WHEN name = %(kw_all)s THEN 0 WHEN {in_name} THEN 1 ELSE 2 END, "
    counts = db.query(
        "SELECT count(*) FILTER (WHERE for_person) AS n, count(*) FILTER (WHERE NOT for_person) AS org "
        f"FROM policy WHERE {where}",
        params,
    )[0]
    if include_org:
        total, hidden_org = counts["n"] + counts["org"], 0
    else:
        total, hidden_org = counts["n"], counts["org"]
        where += " AND for_person"
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
        f"ORDER BY {order}views DESC, name, id LIMIT %(limit)s OFFSET %(offset)s",
        params,
    )
    return {"total": total, "hidden_org": hidden_org, "related": related,
            "policies": [to_card(r) for r in rows]}

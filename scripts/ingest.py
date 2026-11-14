"""공공데이터 수집 → 정리 → 임베딩 → DB 저장.

  python scripts/ingest.py                         # API에서 새로 받아서 저장
  python scripts/ingest.py --from-raw              # data/raw/ 에 받아 둔 파일로 다시 만들기
  python scripts/ingest.py --from-raw --no-embed   # 임베딩은 그대로 두고 나머지 열만 갱신
  python scripts/ingest.py --from-raw --dry-run    # DB에 쓰지 않고 통계만 출력
"""
import argparse
import csv
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402

BASE_URL = "https://api.odcloud.kr/api/gov24/v3/"
OPERATIONS = ["serviceList", "serviceDetail", "supportConditions"]
PER_PAGE = 1000  # 5000이면 목록 오퍼레이션이 data 없이 응답한다
RAW_DIR = config.DATA_DIR / "raw"
UNKNOWN = "UNKNOWN"

# 소관기관유형별 지역 처리
NATIONAL_TYPES = {"중앙행정기관", "공공기관"}
# 기관명 앞의 법인 표시 (지역 이름을 찾기 전에 뗀다)
LEGAL_PREFIXES = ["재단법인", "사단법인", "(재)", "(사)", "(재단)"]
# 시·도 줄임말·옛 이름 → 현재 이름 후보. regions.csv 에 있는 이름만 쓴다.
# "세종", "광주"는 다른 뜻으로도 쓰여서(세종문화회관, 경기도 광주시) 넣지 않는다.
SIDO_ALIASES = {
    "서울": ["서울특별시"], "부산": ["부산광역시"], "대구": ["대구광역시"],
    "인천": ["인천광역시"], "대전": ["대전광역시"], "울산": ["울산광역시"],
    "경기": ["경기도"], "강원": ["강원특별자치도"], "충북": ["충청북도"],
    "충남": ["충청남도"], "전북": ["전북특별자치도"], "경북": ["경상북도"],
    "경남": ["경상남도"], "제주": ["제주특별자치도"],
    "전남": ["전라남도", "전남광주통합특별시"],
    "전라남도": ["전라남도", "전남광주통합특별시"],
    "광주광역시": ["광주광역시", "전남광주통합특별시"],
}


# ---------- 수집 ----------

def fetch_all(operation):
    """한 오퍼레이션을 페이지 단위로 끝까지 받는다. 실패하면 최대 3번 다시 시도한다."""
    rows, page = [], 1
    while True:
        params = {"page": page, "perPage": PER_PAGE, "serviceKey": config.DATA_GO_KR_API_KEY}
        for attempt in range(1, 4):
            try:
                r = httpx.get(BASE_URL + operation, params=params, timeout=120)
                r.raise_for_status()
                body = r.json()
                if "data" not in body:
                    raise ValueError("응답에 data가 없음")
                break
            except Exception as e:  # 오류 문구에 인증키가 섞이지 않게 종류만 출력
                print(f"  {operation} {page}쪽 실패 ({attempt}/3): {type(e).__name__}")
                if attempt == 3:
                    sys.exit("수집을 중단합니다. 잠시 뒤 다시 실행해 주세요.")
                time.sleep(5 * attempt)
        rows += body["data"]
        print(f"  {operation}: {len(rows)}/{body['totalCount']}")
        if len(rows) >= body["totalCount"] or not body["data"]:
            return rows
        page += 1


def fetch_and_save():
    if not config.DATA_GO_KR_API_KEY:
        sys.exit(".env 에 DATA_GO_KR_API_KEY 가 없습니다.")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for op in OPERATIONS:
        rows = fetch_all(op)
        (RAW_DIR / f"{op}.json").write_text(
            json.dumps({"fetched_at": date.today().isoformat(), "data": rows}, ensure_ascii=False),
            encoding="utf-8",
        )


def load_raw():
    raw = {}
    for op in OPERATIONS:
        path = RAW_DIR / f"{op}.json"
        if not path.exists():
            sys.exit(f"{path} 가 없습니다. --from-raw 없이 먼저 실행하세요.")
        raw[op] = json.loads(path.read_text(encoding="utf-8"))
    return raw


# ---------- 정리 ----------

def clean(text):
    if not text:
        return None
    text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def map_conditions(cond, rule_text, codes):
    """지원조건 코드 → DB 열. 규칙은 data/condition_codes.json 참고."""
    male = cond.get(codes["gender"]["male"]) == "Y"
    female = cond.get(codes["gender"]["female"]) == "Y"
    gender = "M" if male and not female else "F" if female and not male else None

    age_min = cond.get(codes["age"]["min"])
    age_max = cond.get(codes["age"]["max"])
    if age_min == codes["age"]["no_min_value"]:
        age_min = None
    if age_max == codes["age"]["no_max_value"]:
        age_max = None

    household = None
    if cond.get(codes["household"]["no_limit_code"]) != "Y":
        household = [v for c, v in codes["household"]["map"].items() if cond.get(c) == "Y"] or None

    income_y = [c for c in codes["income"]["codes"] if cond.get(c) == "Y"]
    has_income_rule = 0 < len(income_y) < len(codes["income"]["codes"]) or any(
        k in rule_text for k in codes["income"]["text_keywords"]
    )
    return {
        "gender": gender, "age_min": age_min, "age_max": age_max,
        "household": household, "has_income_rule": has_income_rule,
    }


class RegionResolver:
    """기관명과 기관 유형으로 region_code 를 정한다. 전국은 None, 못 찾으면 'UNKNOWN'."""

    def __init__(self, region_rows):
        self.sido = {r["sido"]: r["code"] for r in region_rows if not r["sigungu"]}
        self.sigungu = {(r["sido"], r["sigungu"]): r["code"] for r in region_rows if r["sigungu"]}
        self.alias = {}
        for short, candidates in SIDO_ALIASES.items():
            for full in candidates:
                if full in self.sido:
                    self.alias[short] = full
        # 전국에 하나뿐인 시·군·구 이름만 쓴다 ("중구", "고성군" 같은 이름은 제외)
        names = Counter(g for _, g in self.sigungu)
        self.unique = {g: (s, g) for s, g in self.sigungu if names[g] == 1}
        stems = Counter(g[:-1] for g in names if len(g) >= 3)
        self.stem = {
            g[:-1]: self.unique[g] for g in self.unique
            if len(g) >= 3 and stems[g[:-1]] == 1
            and g[:-1] not in SIDO_ALIASES and g[:-1] != "광주"
        }

    def resolve(self, agency, agency_type):
        name = (agency or "").strip()
        if agency_type in NATIONAL_TYPES:
            return None
        if agency_type == "광역시도":
            return self.sido.get(name, UNKNOWN)
        if agency_type == "시군구":
            sido, _, rest = name.partition(" ")
            return self.sigungu.get((sido, rest), UNKNOWN)
        return self._from_name(name)

    def _from_name(self, name):
        name = name.replace(" ", "")
        for prefix in LEGAL_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix):]
        # 1) 시·도 이름(또는 줄임말로 시작) → 그 안의 시·군·구까지 있으면 시·군·구
        sido = next((s for s in sorted(self.sido, key=len, reverse=True) if s in name), None)
        if not sido:
            sido = next((full for short, full in self.alias.items() if name.startswith(short)), None)
        if sido:
            inside = [g for s, g in self.sigungu if s == sido and g in name]
            if inside:
                return self.sigungu[(sido, max(inside, key=len))]
            return self.sido[sido]
        # "광주"는 옛 광주광역시인지 경기도 광주시인지 이름만으로 알 수 없다 (예: 광주시민장학회)
        if "광주" in name:
            return UNKNOWN
        # 2) 전국에 하나뿐인 시·군·구 이름이 들어 있으면 그곳 (가장 긴 이름 우선)
        #    "강서구"처럼 여러 곳에 있는 이름이면 그 안의 "서구"로 잘못 잡지 않고 UNKNOWN
        hits = {g for _, g in self.sigungu if g in name}
        if hits:
            longest = max(hits, key=len)
            return self.sigungu[self.unique[longest]] if longest in self.unique else UNKNOWN
        # 3) "고양산업진흥원", "구로문화재단"처럼 시·군·구 이름에서 끝 글자를 뺀 말로 시작하는 경우
        hits = [st for st in self.stem if name.startswith(st)]
        if hits:
            return self.sigungu[self.stem[max(hits, key=len)]]
        return UNKNOWN


def embedding_text(row):
    """임베딩에 넣을 글. 길면 모델이 앞에서부터 512토큰까지만 쓴다."""
    parts = [row["name"], row["summary"], row["target"], row["content"]]
    return "\n".join(p for p in parts if p)


def build_rows(raw):
    codes = json.loads((config.DATA_DIR / "condition_codes.json").read_text(encoding="utf-8"))
    with open(config.DATA_DIR / "regions.csv", encoding="utf-8", newline="") as f:
        resolver = RegionResolver(list(csv.DictReader(f)))
    collected_at = raw["serviceList"]["fetched_at"]
    details = {d["서비스ID"]: d for d in raw["serviceDetail"]["data"]}
    conditions = {c["서비스ID"]: c for c in raw["supportConditions"]["data"]}

    rows = []
    for s in raw["serviceList"]["data"]:
        sid = s["서비스ID"]
        d = details.get(sid, {})
        target = clean(s.get("지원대상") or d.get("지원대상"))
        criteria = clean(s.get("선정기준") or d.get("선정기준"))
        row = {
            "id": sid,
            "name": clean(s.get("서비스명")),
            "agency": clean(s.get("소관기관명")),
            "category": clean(s.get("서비스분야")),
            "summary": clean(s.get("서비스목적요약")),
            "target": target,
            "criteria": criteria,
            "content": clean(s.get("지원내용") or d.get("지원내용")),
            # 목록의 신청방법은 "방문신청||직접입력" 같은 분류값이라, 풀어 쓴 상세 쪽 글을 먼저 쓴다
            "how_to_apply": clean(d.get("신청방법") or s.get("신청방법")),
            "apply_place": clean(s.get("접수기관") or d.get("접수기관명")),
            "contact": clean(d.get("문의처") or s.get("전화문의")),
            "url": clean(s.get("상세조회URL")),
            "region_code": resolver.resolve(s.get("소관기관명"), s.get("소관기관유형")),
            "collected_at": collected_at,
            "_agency_type": s.get("소관기관유형"),
        }
        row.update(map_conditions(conditions.get(sid, {}), (target or "") + (criteria or ""), codes))
        if row["name"]:
            rows.append(row)
    return rows


def print_stats(rows):
    def scope(code):
        if code is None:
            return "전국"
        if code == UNKNOWN:
            return UNKNOWN
        return "시·도" if len(code) == 2 else "시·군·구"

    print("지역 구분:", dict(Counter(scope(r["region_code"]) for r in rows)))
    unknown = Counter(r["agency"] for r in rows if r["region_code"] == UNKNOWN)
    if unknown:
        print(f"UNKNOWN 기관 {len(unknown)}곳 (많은 순 15곳):", unknown.most_common(15))
    print("성별:", dict(Counter(r["gender"] for r in rows)),
          "| 소득 기준 있음:", sum(r["has_income_rule"] for r in rows),
          "| 가구 조건 있음:", sum(r["household"] is not None for r in rows))


# ---------- 저장 ----------

COLUMNS = [
    "id", "name", "agency", "category", "summary", "target", "criteria", "content",
    "how_to_apply", "apply_place", "contact", "url", "region_code", "age_min", "age_max",
    "gender", "household", "has_income_rule", "collected_at",
]


def save(rows, with_embedding):
    import psycopg
    from pgvector.psycopg import register_vector

    columns = COLUMNS + (["embedding"] if with_embedding else [])
    sql = (
        f"INSERT INTO policy ({', '.join(columns)}) "
        f"VALUES ({', '.join('%(' + c + ')s' for c in columns)}) "
        f"ON CONFLICT (id) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "id")
    )
    with psycopg.connect(config.DATABASE_URL) as conn:
        register_vector(conn)
        before = conn.execute("SELECT count(*) FROM policy").fetchone()[0]
        cur = conn.cursor()
        for i in range(0, len(rows), 500):
            cur.executemany(sql, rows[i:i + 500])
            print(f"  저장 {min(i + 500, len(rows))}/{len(rows)}")
        # 이번 목록에 없는 정책은 지운다. 수집이 덜 된 경우 DB를 비우지 않도록 건수를 먼저 본다.
        if len(rows) >= before * 0.8:
            cur.execute("DELETE FROM policy WHERE NOT (id = ANY(%s))", ([r["id"] for r in rows],))
            print(f"  목록에서 사라진 정책 {cur.rowcount}건 삭제")
        else:
            print(f"  이번 건수({len(rows)})가 기존({before})보다 크게 적어서 삭제는 건너뜀")
        total, no_vec = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE embedding IS NULL) FROM policy"
        ).fetchone()
    print(f"DB 정책 수: {total}건" + (f" (임베딩 없는 정책 {no_vec}건)" if no_vec else ""))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-raw", action="store_true", help="API를 부르지 않고 data/raw/ 파일 사용")
    parser.add_argument("--no-embed", action="store_true", help="임베딩은 다시 계산하지 않음")
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 통계만 출력")
    args = parser.parse_args()

    if not args.from_raw:
        print("1) 공공데이터 API에서 받는 중")
        fetch_and_save()
    print("2) 정리하는 중")
    rows = build_rows(load_raw())
    print(f"정책 {len(rows)}건")
    print_stats(rows)
    if args.dry_run:
        return

    if not args.no_embed:
        print("3) 임베딩 계산 중 (몇 분 걸려요)")
        from app.services.embedder import embed_passages

        vectors = embed_passages([embedding_text(r) for r in rows], show_progress=True)
        for row, vec in zip(rows, vectors):
            row["embedding"] = vec
    print("4) DB에 저장하는 중")
    save(rows, with_embedding=not args.no_embed)


if __name__ == "__main__":
    main()

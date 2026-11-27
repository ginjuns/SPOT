"""공공데이터 수집 → 정리 → 임베딩 → DB 저장.

  python scripts/ingest.py                         # API에서 새로 받아서 저장
  python scripts/ingest.py --from-raw              # data/raw/ 에 받아 둔 파일로 다시 만들기
  python scripts/ingest.py --from-raw --no-embed   # 임베딩은 그대로 두고 나머지 열만 갱신
  python scripts/ingest.py --from-raw --dry-run    # DB에 쓰지 않고 통계만 출력

정부24 정책과 함께 민간 복지 지원·장학금(공공데이터포털 파일 자료, scripts/private_data.py)과
정부24에 없는 지자체 복지(한국사회보장정보원 API, scripts/local_welfare.py)도 받아서 넣는다.
"""
import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from scripts import local_welfare, private_data  # noqa: E402

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
    for name in private_data.DATASETS:
        try:
            count = private_data.download(name, RAW_DIR / f"{name}.csv")
            print(f"  {name}: {count}건")
        except Exception as e:   # 민간 자료를 못 받아도 정부24 수집은 이어 간다 (지난번 받은 파일이 있으면 그걸 쓴다)
            print(f"  {name} 받기 실패 ({type(e).__name__}: {e}). 지난번 파일이 있으면 그대로 씁니다.")
    # 지자체 복지: 정부24와 겹치는지 보려면 방금 받은 정부24 목록이 필요하다
    path = RAW_DIR / LOCAL_WELFARE_FILE
    old = json.loads(path.read_text(encoding="utf-8")).get("details", {}) if path.exists() else {}
    try:
        resolver = load_resolver()
        gov = [{"name": s["서비스명"], "region_code": resolver.resolve(s.get("소관기관명"), s.get("소관기관유형"))}
               for s in load_raw()["serviceList"]["data"]]
        saved = local_welfare.fetch(config.DATA_GO_KR_API_KEY, resolver, gov, old)
        path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    except Exception as e:   # 못 받아도 정부24 수집은 이어 간다
        print(f"  지자체복지 받기 실패 ({type(e).__name__}). 지난번 파일이 있으면 그대로 씁니다.")


LOCAL_WELFARE_FILE = "local_welfare.json"


def load_resolver():
    with open(config.DATA_DIR / "regions.csv", encoding="utf-8", newline="") as f:
        return RegionResolver(list(csv.DictReader(f)))


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


LOCAL_ONLY = re.compile(r"주변지역|사업장\s*주변|발전소\s*주변|[가-힣]+[시군구]\s+[가-힣]+[읍면동]\s*주민")


def local_only(name, target):
    """특정 지역 주민만 받는 정책인지: 이름이나 지원 대상 글 앞 80자에 "주변지역", "서천군 서면 주민" 같은 말이 있다."""
    head = " ".join((target or "").split())[:80]
    return bool(LOCAL_ONLY.search(name or "") or LOCAL_ONLY.search(head))


def embedding_text(row):
    """임베딩에 넣을 글. 길면 모델이 앞에서부터 512토큰까지만 쓴다."""
    # 꼬리표의 일상 표현("나라에서 매달 주는 돈")은 맨 뒤에 붙인다. 512토큰을 넘으면 잘리지만,
    # 지원 대상·내용이 아주 긴 정책은 원래 글만으로도 뜻이 충분하다.
    parts = [row["name"], row["summary"], row["target"], row["content"], row.get("tag_words")]
    return "\n".join(p for p in parts if p)


def add_tags(rows):
    """정책 검색용 꼬리표(data/policy_tags.tsv, app/services/tags.py)를 행에 붙인다. 없는 정책은 NULL."""
    from app.services import tags

    missing = 0
    for row in rows:
        row["tag_ages"], row["tag_special"], row["tag_words"] = tags.for_row(row)
        # 민간 지원·장학금은 자료의 생애주기·장학금 종류로 만든 꼬리표를 기본으로 쓴다 (Claude 꼬리표가 있으면 그쪽)
        if row["tag_ages"] is None and row.get("_rule_tags"):
            ages, special, words = row["_rule_tags"]
            row["tag_ages"], row["tag_special"] = tags.normalize(row["name"], None, ages, special, row.get("target"))
            row["tag_words"] = words
        # 꼬리표는 개인·가구 대상 정책에만 만들었다 (기업·단체 대상은 채팅 나이 검사와 상관없다)
        missing += row["tag_ages"] is None and row["for_person"]
    print(f"꼬리표: {len(rows)}건 중 붙인 정책 {sum(r['tag_ages'] is not None for r in rows)}건, "
          f"꼬리표가 없는 개인 대상 정책 {missing}건" + (" (새로 생긴 정책이면 꼬리표를 만들어 data/policy_tags.tsv에 더하기)" if missing else ""))


AGE_FROM = re.compile(r"(\d{1,3})\s*세\s*이상")
AGE_UNDER = re.compile(r"(\d{1,3})\s*세\s*(미만|이하)")
AGE_RANGE = re.compile(r"(\d{1,3})\s*세?\s*[~∼-]\s*(\d{1,3})\s*세")
AGE_EXACT_IN_NAME = re.compile(r"^(\d{2})세\s")
AGE_AT_START = re.compile(r"^[○\-·ㆍ*\s]*(만\s*)?\d{1,3}\s*(세|[~∼-])")
# 이런 말이 있으면 나이는 여러 대상 중 하나의 조건이거나 자녀의 나이다
AGE_NOT_SURE = re.compile(r"[,·ㆍ/]|및|또는|자녀|아이|세대|가구|가정|기업")


def _ages_in(text):
    text = re.sub(r"만\s*(?=\d)", "", text.split("(")[0])   # "만 6세" → "6세". 괄호 안의 나이는 덧붙인 설명이라 보지 않는다
    ranged = AGE_RANGE.search(text)
    if ranged:
        under = text[ranged.end():].lstrip().startswith("미만")   # "6세~65세 미만" → 64세까지
        return int(ranged.group(1)), int(ranged.group(2)) - (1 if under else 0)
    start, under = AGE_FROM.search(text), AGE_UNDER.search(text)
    age_min = int(start.group(1)) if start else None
    age_max = int(under.group(1)) - (1 if under.group(2) == "미만" else 0) if under else None
    return age_min, age_max


def age_from_text(name, target):
    """지원조건 코드에 나이가 없을 때, 정책 이름과 지원 대상 글에서 나이를 뽑는다. (age_min, age_max)

    지자체 정책은 나이를 글로만 적어 둔 경우가 많다 ("65세 이상 폐렴구균 예방접종", "56세 C형간염").
    잘못 뽑으면 받을 수 있는 정책이 가려지므로 아주 확실한 경우만 본다:
      - 이름이 "56세 ..."처럼 나이로 시작하거나, 이름에 "N세 이상/이하"가 있을 때
      - 지원 대상이 한 항목뿐이고(○ 가 1개 이하), 글이 나이로 시작할 때 ("만 40세 이상 예비 창업자")
    글 앞머리(60자)에 쉼표·"및"·"자녀"·"가구" 같은 말이 있으면 쓰지 않는다. 나이가 여러 대상 중
    하나의 조건이거나("65세 이상 노인, 장애인, 한부모") 자녀의 나이("18세 이하 자녀를 둔 가정")일 수 있다.
    """
    name = name or ""
    head = " ".join((target or "").split())[:60]
    exact = AGE_EXACT_IN_NAME.search(name)
    if exact:
        age_min = age_max = int(exact.group(1))
    elif not AGE_NOT_SURE.search(name) and _ages_in(name) != (None, None):
        age_min, age_max = _ages_in(name)
    elif (target or "").count("○") <= 1 and AGE_AT_START.search(head) and not AGE_NOT_SURE.search(head):
        age_min, age_max = _ages_in(head)
    else:
        return None, None
    # 말이 안 되는 값은 버린다 (0세, 150세, 시작이 끝보다 큰 경우)
    if age_min is not None and not 0 < age_min <= 120:
        age_min = None
    if age_max is not None and not 0 < age_max <= 120:
        age_max = None
    if age_min is not None and age_max is not None and age_min > age_max:
        return None, None
    return age_min, age_max

AGE_OVER = re.compile(r"(\d{1,3})\s*세\s*이상")
AGE_BELOW = re.compile(r"(\d{1,3})\s*세\s*(?:이하|미만)")
ELDER_AGE = 60     # 이 나이 이상을 어르신 무리로 본다
CHILD_AGE = 19     # 이 나이 이하를 아이·청소년 무리로 본다


def widen_for_other_groups(age_min, age_max, target):
    """지원조건 코드에 한 나이 무리만 들어 있는데, 지원 대상 글에 다른 나이 무리가 따로 있으면 나이 제한을 푼다.

    "인플루엔자 국가예방접종"은 어린이·임신부·65세 이상이 대상인데 코드에는 0~14세만 있어서 어르신에게
    보이지 않았다. 관람료·이용료 감면은 반대로 65세 이상만 들어 있어 어린이 무리가 빠졌다 (2026-11-19).
    받을 수 있는 사람에게 숨기는 것보다 넓게 보여 주고 신청처에서 확인하게 하는 쪽이 낫다.
    자녀 나이가 글에 나오는 정책(18~44세 임산부 + "2세 미만 영아")은 어느 경우에도 걸리지 않는다.
    """
    text = re.sub(r"만\s*(?=\d)", "", target or "")
    elders = [int(a) for a in AGE_OVER.findall(text) if int(a) >= ELDER_AGE]
    children = [int(a) for a in AGE_BELOW.findall(text) if int(a) <= CHILD_AGE]
    if age_max is not None and age_max < ELDER_AGE and elders:
        return None, None
    if age_min is not None and age_min >= ELDER_AGE and children:
        return None, None
    return age_min, age_max


# 구비서류 칸에 "없다"는 뜻으로 적어 둔 값들 (이런 값은 보여 주지 않는다)
NO_DOCUMENTS = {"해당없음", "없음", "-", "구비서류없음", "해당사항없음", "별도구비서류없음", "제출서류없음"}


def documents(text):
    """준비할 서류. "해당없음"처럼 없다는 뜻의 값은 None 으로 바꾼다."""
    text = clean(text)
    if not text or text.replace(" ", "").rstrip(".") in NO_DOCUMENTS:
        return None
    return text


def for_person(user_types):
    """개인·가구가 받는 지원인지. 목록 응답의 사용자구분 ("개인||가구", "소상공인", "법인/시설/단체" 등).

    소상공인·법인·시설·단체만 받는 지원이면 False 다. 값이 없으면 숨기지 않도록 True 로 둔다.
    """
    types = [t.strip() for t in (user_types or "").split("||") if t.strip()]
    return not types or any(t in ("개인", "가구") for t in types)


def build_rows(raw):
    codes = json.loads((config.DATA_DIR / "condition_codes.json").read_text(encoding="utf-8"))
    resolver = load_resolver()
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
            "apply_period": clean(s.get("신청기한") or d.get("신청기한")),
            "documents": documents(d.get("구비서류")),
            "contact": clean(d.get("문의처") or s.get("전화문의")),
            "url": clean(s.get("상세조회URL")),
            "region_code": resolver.resolve(s.get("소관기관명"), s.get("소관기관유형")),
            "for_person": for_person(s.get("사용자구분")),
            "views": int(s.get("조회수") or 0),   # 많이 찾는 정책을 먼저 보여 주는 데 쓴다
            "collected_at": collected_at,
            "source": None,   # 정부24 정책. 민간 지원·장학금은 "민간 지원", "민간 장학금" 같은 이름 (private_data.py)
            "_agency_type": s.get("소관기관유형"),
        }
        # "발전소 주변지역 장학금"처럼 특정 지역 주민만 받는 공공기관 정책은 전국 정책으로 두지 않는다.
        # 이름에 없어도 지원 대상 글 앞부분에 적혀 있으면 같다 (2026-11-23, "신서천발전본부 주택용 전기요금 지원"
        # → 대상 "충남 서천군 서면 주민". 전기요금을 물은 모든 사람에게 나왔다).
        if row["region_code"] is None and local_only(row["name"], target):
            row["region_code"] = UNKNOWN
        row.update(map_conditions(conditions.get(sid, {}), (target or "") + (criteria or ""), codes))
        if row["age_min"] is None and row["age_max"] is None:
            row["age_min"], row["age_max"] = age_from_text(row["name"], target)
        else:
            row["age_min"], row["age_max"] = widen_for_other_groups(row["age_min"], row["age_max"], target)
        if row["name"]:
            rows.append(row)
    return rows + build_local_rows(resolver, rows) + build_private_rows(resolver, rows)


def build_local_rows(resolver, gov_rows):
    """정부24에 없는 지자체 복지 (data/raw/local_welfare.json). 파일이 없으면 건너뛴다."""
    path = RAW_DIR / LOCAL_WELFARE_FILE
    if not path.exists():
        print(f"  {path.name} 가 없어서 지자체 복지는 넣지 않습니다. --from-raw 없이 실행하면 받아요.")
        return []
    saved = json.loads(path.read_text(encoding="utf-8"))
    todo = local_welfare.new_items(saved["list"], resolver, gov_rows)
    got = local_welfare.rows(todo, saved["details"], resolver, saved["fetched_at"], age_from_text)
    print(f"  지자체복지: 목록 {len(saved['list'])}건 중 정부24에 없는 것 {len(todo)}건, 넣은 것 {len(got)}건 "
          f"(상세가 없거나 끝난 사업은 뺌)")
    return got


def build_private_rows(resolver, gov_rows):
    """민간 복지 지원과 장학금 (data/raw/private_welfare.csv, scholarship.csv). 파일이 없으면 건너뛴다."""
    out = []
    for name in private_data.DATASETS:
        path = RAW_DIR / f"{name}.csv"
        if not path.exists():
            print(f"  {path.name} 가 없어서 {name}은 넣지 않습니다. --from-raw 없이 실행하면 받아요.")
            continue
        records = private_data.load(path)
        collected_at = date.fromtimestamp(path.stat().st_mtime).isoformat()
        if name == "private_welfare":
            got = private_data.welfare_rows(records, resolver, collected_at)
        else:
            got = private_data.scholarship_rows(records, resolver, collected_at, [r["name"] for r in gov_rows])
        print(f"  {name}: 파일 {len(records)}건 중 {len(got)}건 넣음")
        out += got
    return out


def print_stats(rows):
    def scope(code):
        if code is None:
            return "전국"
        if code == UNKNOWN:
            return UNKNOWN
        return "시·도" if len(code) == 2 else "시·군·구"

    print("출처:", dict(Counter(r.get("source") or ("지자체복지" if r["id"].startswith("WLF") else "정부24") for r in rows)))
    print("지역 구분:", dict(Counter(scope(r["region_code"]) for r in rows)))
    unknown = Counter(r["agency"] for r in rows if r["region_code"] == UNKNOWN)
    if unknown:
        print(f"UNKNOWN 기관 {len(unknown)}곳 (많은 순 15곳):", unknown.most_common(15))
    print("성별:", dict(Counter(r["gender"] for r in rows)),
          "| 소득 기준 있음:", sum(r["has_income_rule"] for r in rows),
          "| 가구 조건 있음:", sum(r["household"] is not None for r in rows),
          "| 기업·단체만 받는 지원:", sum(not r["for_person"] for r in rows))


# ---------- 저장 ----------

COLUMNS = [
    "id", "name", "agency", "category", "summary", "target", "criteria", "content",
    "how_to_apply", "apply_place", "apply_period", "documents", "contact", "url", "region_code", "age_min", "age_max",
    "gender", "household", "has_income_rule", "for_person", "views", "collected_at",
    "tag_ages", "tag_special", "tag_words", "source",
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
    add_tags(rows)
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

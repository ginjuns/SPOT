"""정부24에 없는 시·군·구, 시·도 복지 지원 (한국사회보장정보원_지자체복지서비스 API, 공공데이터포털, 무료).

복지로에 올라온 지자체 복지 약 4,800건 가운데 정부24에도 있는 것(이름이 같거나 비슷한 것)을 빼고 넣는다.
정부24 정책과 마찬가지로 나라(지자체)에서 하는 지원이라 source 는 NULL 로 두고, ID는 복지로 서비스 ID
("WLF00006646")를 그대로 쓴다. 인증키는 정부24와 같은 DATA_GO_KR_API_KEY 다.

  - 목록 오퍼레이션은 한 번에 1000건씩 받는다 (5번).
  - 목록에는 지원 대상·내용이 없어서 상세 오퍼레이션을 정책마다 부른다. 정부24와 겹치지 않는 것만 부르고,
    받은 상세는 data/raw/local_welfare.json 에 두었다가 다음 수집 때 고친 날짜(lastModYmd)가 같으면 다시 쓴다.
    하루 호출 수를 넘거나 실패가 이어지면 받은 데까지만 저장하고 멈춘다. 다음 날 다시 실행하면 이어서 받는다.
"""
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date

import httpx

from scripts.private_data import TOPIC_CATEGORY, base_row

BASE_URL = "https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/"
PER_PAGE = 1000
# 정부24 정책과 이름이 이만큼 비슷하면 같은 지원으로 보고 넣지 않는다 (0~1. 아래 similarity)
SAME_POLICY = 0.5
# 목록에 거의 모든 정책에 "서민금융"이 붙어 있어서(4,837건 중 3,172건) 분야를 정하는 데 쓰지 않는다
IGNORE_THEMES = {"서민금융"}
# 분야를 관심주제로 못 정했을 때 이름으로 정한다 (앞에 있는 것부터)
NAME_CATEGORY = [
    (re.compile(r"임신|출산|산모|산후|난임|신생아"), "임신·출산"),
    (re.compile(r"보육|어린이집|유치원|입학|학생|장학|교육|교복|급식"), "보육·교육"),
    (re.compile(r"의료|진료|치료|수술|검사|검진|접종|건강|의치|틀니|보청기|약제"), "보건·의료"),
    (re.compile(r"주거|주택|월세|임차|전세|집수리|이사"), "주거·자립"),
    (re.compile(r"일자리|취업|고용|창업|구직"), "고용·창업"),
    (re.compile(r"돌봄|요양|보호|위탁|입양|간병"), "보호·돌봄"),
    (re.compile(r"문화|여가|관람|체육|여행|목욕"), "문화·환경"),
]
LIFE_AGES = {"영유아": "child", "아동": "child", "청소년": "child", "청년": "youth",
             "중장년": "middle", "노년": "elder", "임신 · 출산": "pregnant", "임신·출산": "pregnant"}
INCOME_WORDS = re.compile(r"중위소득|소득인정액|기초생활|수급자|차상위|저소득")


# ---------- 받기 ----------

def _get(operation, params, key):
    """XML 응답을 받아 ElementTree 로 돌려준다. 실패하면 3번까지 다시 시도한다."""
    for attempt in range(1, 4):
        try:
            r = httpx.get(BASE_URL + operation, params={"serviceKey": key, **params}, timeout=60)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            if (root.findtext("resultCode") or "").strip() != "0":
                raise ValueError(f"resultCode {root.findtext('resultCode')} {root.findtext('resultMessage')}")
            return root
        except Exception as e:  # 오류 문구에 인증키가 섞이지 않게 종류만 출력
            print(f"  지자체복지 {operation} 실패 ({attempt}/3): {type(e).__name__}")
            if attempt < 3:
                time.sleep(3 * attempt)
    return None


def _flat(node):
    """XML 한 덩어리 → dict. 문의처처럼 같은 이름이 여러 번 나오는 칸은 목록으로 모은다."""
    out = {}
    for child in node:
        if len(child):
            out.setdefault(child.tag, []).append({c.tag: (c.text or "").strip() for c in child})
        else:
            out[child.tag] = (child.text or "").strip()
    return out


def fetch_list(key):
    items, page = [], 1
    while True:
        root = _get("LcgvWelfarelist", {"pageNo": page, "numOfRows": PER_PAGE}, key)
        if root is None:
            raise RuntimeError("목록을 받지 못했습니다")
        got = [_flat(s) for s in root.findall("servList")]
        items += got
        total = int(root.findtext("totalCount") or 0)
        print(f"  지자체복지 목록: {len(items)}/{total}")
        if len(items) >= total or not got:
            return items
        page += 1


def fetch_details(items, old, key):
    """정책마다 상세를 받는다. old(지난번 상세)에 고친 날짜가 같은 것이 있으면 다시 부르지 않는다."""
    details, called = {}, 0
    for i, item in enumerate(items, 1):
        sid = item["servId"]
        prev = old.get(sid)
        if prev and prev.get("lastModYmd") == item.get("lastModYmd"):
            details[sid] = prev
            continue
        root = _get("LcgvWelfaredetailed", {"servId": sid}, key)
        if root is None:
            print(f"  상세를 더 받지 못해서 멈춥니다 ({i - 1}/{len(items)}). 하루 호출 수를 넘었으면 내일 다시 실행하면 이어서 받아요.")
            # 못 받은 것은 지난번 상세라도 쓴다
            details.update({k: v for k, v in old.items() if k not in details})
            break
        details[sid] = _flat(root)
        called += 1
        if called % 200 == 0:
            print(f"  지자체복지 상세: {i}/{len(items)}")
    print(f"  지자체복지 상세: 새로 받은 것 {called}건, 지난번 것 다시 씀 {len(details) - called}건")
    return details


# ---------- 정부24와 겹치는지 ----------

GENERIC = re.compile(r"지원사업|지원금|지원|사업|운영|지급|시행|추진|제공|서비스|안내|및|의|등")


class Matcher:
    """정부24 정책과 같은 지원인지 이름으로 본다. 같은 지역(또는 그 시·도, 지역 불명) 정책만 비교한다.

    이름에서 지역 이름, 괄호 속 말, "지원·사업·지급" 같은 흔한 말을 떼고(핵심 이름) 두 글자씩 끊어 겹치는 비율을 본다.
    한쪽 핵심 이름이 4글자 이상이고 다른 쪽에 통째로 들어 있으면 같은 것으로 본다
    ("보훈명예수당 지원" ↔ "보훈명예수당", "출생축하용품 지원사업" ↔ "출생축하용품 지원").
    """

    def __init__(self, resolver, gov_rows):
        names = set(resolver.sido) | set(resolver.alias) | {g for _, g in resolver.sigungu} | set(resolver.stem)
        self.region_words = re.compile("|".join(sorted(map(re.escape, names), key=len, reverse=True)))
        self.by_region = {}
        for row in gov_rows:
            self.by_region.setdefault(row["region_code"], []).append(self.core(row["name"]))

    def core(self, name):
        name = re.sub(r"\([^)]*\)|\[[^\]]*\]|<[^>]*>|「|」", "", name or "")
        name = self.region_words.sub("", name)
        name = re.sub(r"[^가-힣A-Za-z0-9]", "", name)
        return GENERIC.sub("", name)

    @staticmethod
    def similarity(a, b):
        if not a or not b:
            return 0.0
        if a == b or (len(a) >= 4 and a in b) or (len(b) >= 4 and b in a):
            return 1.0
        pa = {a[i:i + 2] for i in range(len(a) - 1)} or {a}
        pb = {b[i:i + 2] for i in range(len(b) - 1)} or {b}
        return len(pa & pb) / len(pa | pb)

    def in_gov24(self, name, region_code):
        mine = self.core(name)
        codes = [region_code, "UNKNOWN"] + ([region_code[:2]] if region_code and len(region_code) == 5 else [])
        return any(self.similarity(mine, other) >= SAME_POLICY
                   for code in codes for other in self.by_region.get(code, []))


def region_of(item, resolver):
    """시·도 + 시·군·구 이름 → region_code. 시·군·구를 못 찾으면(교육청, 제주시, 바뀐 구 이름) 시·도로 둔다."""
    sido, sgg = (item.get("ctpvNm") or "").strip(), (item.get("sggNm") or "").strip()
    code = resolver.sigungu.get((sido, sgg)) if sgg else None
    return code or resolver.sido.get(sido) or "UNKNOWN"


def new_items(items, resolver, gov_rows):
    """정부24에 없는 지자체 복지만 고른다."""
    matcher = Matcher(resolver, gov_rows)
    return [i for i in items if i.get("servId") and i.get("servNm")
            and not matcher.in_gov24(i["servNm"], region_of(i, resolver))]


# ---------- 정리 ----------

def _text(value):
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value or value in ("-", "해당없음", "없음"):
        return None
    # 항목을 줄바꿈 없이 "◯", "○"로만 이어 둔 글이 많다 → 항목마다 줄을 나눈다
    return re.sub(r"\s*[◯○]\s*", "\n○ ", value).strip()


def _ymd(value):
    value = (value or "").strip()
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if re.fullmatch(r"\d{8}", value) else None


def _split(value):
    return [t.strip() for t in (value or "").split(",") if t.strip()]


def category(themes, name):
    for t in themes:
        if t not in IGNORE_THEMES and t in TOPIC_CATEGORY:
            return TOPIC_CATEGORY[t]
    return next((c for pattern, c in NAME_CATEGORY if pattern.search(name or "")), "생활안정")


def rows(items, details, resolver, collected_at, age_from_text, today=None):
    """정부24에 없는 지자체 복지(new_items 결과) → policy 행. 상세가 없거나 끝난 사업은 넣지 않는다.

    age_from_text 는 ingest.age_from_text (이름·지원 대상 글에서 나이 뽑기. ingest.py 가 이 모듈을 불러서 넘겨받는다).
    """
    today = (today or date.today()).isoformat()
    out = []
    for item in items:
        d = details.get(item["servId"])
        if not d:
            continue
        start, end = _ymd(d.get("enfcBgngYmd")), _ymd(d.get("enfcEndYmd"))
        if end and end < today:
            continue
        name = _text(d.get("servNm") or item.get("servNm"))
        target, criteria = _text(d.get("sprtTrgtCn")), _text(d.get("slctCritCn"))
        who = _split(d.get("trgterIndvdlNmArray") or item.get("trgterIndvdlNmArray"))
        contacts = [" ".join(x for x in (c.get("wlfareInfoReldNm"), c.get("wlfareInfoReldCn")) if x)
                    for c in d.get("inqplCtadrList", [])]
        sido, sgg = (item.get("ctpvNm") or "").strip(), (item.get("sggNm") or "").strip()
        row = base_row(
            id=item["servId"], name=name, agency=" ".join(x for x in (sido, sgg if sgg != "-" else "") if x) or None,
            source=None, category=category(_split(d.get("intrsThemaNmArray")), name),
            summary=_text(d.get("servDgst")), target=target, criteria=criteria, content=_text(d.get("alwServCn")),
            how_to_apply=_text(d.get("aplyMtdCn")) or _text(item.get("aplyMtdNm")),
            apply_place=_text(d.get("bizChrDeptNm")),
            # 끝나는 날을 9999-12-31처럼 적어 둔 것은 기한 없이 계속하는 사업이다
            apply_period="상시신청" if not end or end >= "2090" else f"{start or ''} ~ {end}".strip(),
            contact="\n".join(c for c in contacts if c) or None,
            url=(d.get("servDtlLink") or item.get("servDtlLink") or "").strip() or None,
            region_code=region_of(item, resolver),
            has_income_rule="저소득" in who or bool(INCOME_WORDS.search((target or "") + (criteria or ""))),
            views=int(d.get("inqNum") or item.get("inqNum") or 0),
            collected_at=collected_at,
        )
        row["age_min"], row["age_max"] = age_from_text(name, target)
        # 꼬리표: 생애주기 → 나이 무리, 대상이 한 무리뿐이면 특정 대상. 생애주기가 비어 있으면 꼬리표 없이 둔다
        # (그동안은 예전 낱말 나이 검사로 동작한다. tag_new.py 나 Claude로 꼬리표를 만들 수 있다)
        ages = sorted({LIFE_AGES[x] for x in _split(d.get("lifeNmArray") or item.get("lifeNmArray")) if x in LIFE_AGES})
        special = []
        if who == ["장애인"]:
            special.append("disabled")
        elif who == ["보훈대상자"]:
            special.append("veteran")
        elif who == ["다문화·탈북민"]:
            special.append("defector" if re.search(r"탈북|북한이탈", name) else "multicultural")
        if ages:
            row["_rule_tags"] = (ages, special, None)
        if name:
            out.append(row)
    return out


def fetch(key, resolver, gov_rows, old_details):
    """목록을 받고, 정부24에 없는 것만 상세를 받는다. 저장할 dict 를 돌려준다."""
    items = fetch_list(key)
    todo = new_items(items, resolver, gov_rows)
    print(f"  지자체복지: {len(items)}건 중 정부24에 없는 것 {len(todo)}건의 상세를 받아요")
    details = fetch_details(todo, old_details, key)
    return {"fetched_at": date.today().isoformat(), "list": items, "details": details}


if __name__ == "__main__":
    sys.exit("python scripts/ingest.py 로 실행하세요 (정부24 자료와 함께 받습니다).")

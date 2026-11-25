"""정부24 밖의 지원: 민간 복지 지원과 장학금 (공공데이터포털 파일 자료, 무료).

  - 한국사회보장정보원_민간복지서비스정보 (복지로에 올라온 민간 재단·기업·단체의 지원, 약 330건, 1년에 한 번 갱신)
  - 한국장학재단_학자금지원정보(대학생) (기업·재단·지자체 장학회의 장학금 모집 공고, 약 1,900건)

ingest.py 가 정부24 자료와 함께 받아서 같은 policy 표에 넣는다. source 열에 "민간 지원", "민간 장학금",
"장학금"처럼 화면에 보일 이름을 적어서 정부 지원과 헷갈리지 않게 한다 (정부24 정책은 NULL).
파일은 로그인 없이 받을 수 있어서 API 키가 필요 없다.
"""
import csv
import hashlib
import io
import re
from datetime import date, timedelta

import httpx

# 이름 → 공공데이터포털 파일 자료 번호
DATASETS = {"private_welfare": "15116392", "scholarship": "15028252"}
PORTAL = "https://www.data.go.kr"

# 민간 복지 "관심주제" → 정부24 분야 (분야 고르기 화면에서 같이 보이게)
TOPIC_CATEGORY = {
    "교육": "보육·교육", "보육": "보육·교육", "신체건강": "보건·의료", "정신건강": "보건·의료",
    "주거": "주거·자립", "문화·여가": "문화·환경", "임신·출산": "임신·출산", "일자리": "고용·창업",
    "생활지원": "생활안정", "서민금융": "생활안정", "에너지": "생활안정", "보호·돌봄": "보호·돌봄",
    "안전·위기": "행정·안전", "법률": "행정·안전",
}
# 민간 복지 "생애주기" → 꼬리표 나이 무리
LIFE_AGES = {"영유아": "child", "아동": "child", "청소년": "child", "청년": "youth",
             "중장년": "middle", "노년": "elder", "임신 · 출산": "pregnant"}
# 장학금 운영기관구분 → 화면에 보일 이름. 정부·한국장학재단 장학금은 정부24에 이미 있어서 넣지 않는다.
SCHOLARSHIP_SOURCE = {"기타": "민간 장학금", "지자체(출자출연기관)": "지역 장학금", "공공기관": "장학금"}
# 지난 모집이 이만큼 안에 끝났으면 넣는다 (장학금은 해마다 비슷한 때 다시 모집한다)
SCHOLARSHIP_RECENT_DAYS = 400
# 값이 없다는 뜻으로 적어 둔 칸
EMPTY = re.compile(r"^[\s※○]*(해당\s*없음|없음|제한\s*없음|기관\s*확인\s*필요|-)?[\s.]*$")
URL = re.compile(r"https?://[^\s,)<>\"']+|www\.[^\s,)<>\"']+")


# ---------- 받기 ----------

def download(name, path):
    """공공데이터포털 파일 자료를 받아 UTF-8 CSV로 저장한다. 포털 화면의 [다운로드] 버튼과 같은 순서로 부른다."""
    pk = DATASETS[name]
    with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"}) as c:
        page = c.get(f"{PORTAL}/data/{pk}/fileData.do").text
        detail = re.search(r'name="publicDataDetailPk" value="([^"]+)"', page)
        if not detail:
            raise RuntimeError(f"{name}: 자료 화면에서 파일 번호를 찾지 못했습니다")
        info = c.post(f"{PORTAL}/tcs/dss/selectFileDataDownload.do", data={
            "publicDataDetailPk": detail.group(1), "publicDataPk": pk, "atchFileId": "",
            "fileDetailSn": "1", "publicDataTyCode": "PR0051"}).json()
        if not info.get("status"):
            raise RuntimeError(f"{name}: 파일 받기 실패")
        raw = c.get(f"{PORTAL}/cmm/cmm/fileDownload.do",
                    params={"atchFileId": info["atchFileId"], "fileDetailSn": info["fileDetailSn"]}).content
    text = decode(raw)
    if not text.lstrip().startswith(("기관명", "번호", "﻿")):
        raise RuntimeError(f"{name}: 받은 파일이 CSV가 아닙니다")
    path.write_text(text, encoding="utf-8")
    return len(list(csv.DictReader(io.StringIO(text))))


def decode(raw):
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("cp949", errors="replace")


def load(path):
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8").lstrip("﻿"))))


# ---------- 정리 ----------

def text(value):
    """칸 값 정리. "해당없음", "※ 기관확인필요" 같은 값은 None."""
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if EMPTY.match(value):
        return None
    # 장학금 자료는 항목을 줄바꿈 없이 "○"로만 이어 붙여 둔다 ("대상 1명 1000만원○ 최우수상 2명 …") → 항목마다 줄을 나눈다
    return re.sub(r"\s*○\s*", "\n○ ", value).strip()


def make_id(prefix, *parts):
    """기관명+사업명으로 만든 고정 ID. 해마다 다시 받아도 같은 지원은 같은 ID다 (조회수·꼬리표가 이어진다)."""
    key = "|".join(re.sub(r"\s+", "", p or "") for p in parts)
    return prefix + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10].upper()


def first_url(*texts):
    for t in texts:
        found = URL.search(t or "")
        if found:
            url = found.group(0).rstrip(".")
            return url if url.startswith("http") else "https://" + url
    return None


def normal_name(name):
    return re.sub(r"[\s()·ㆍ\-]", "", name or "")


def sido_in(resolver, name):
    """이름에 시·도 이름이 분명히 있을 때만 그 시·도 (서울장학재단 → 서울, 경남은행사랑나눔재단 → 경남). 없으면 None.

    민간 기관 이름은 시·군·구 이름과 우연히 겹치는 일이 많아서(아산사회복지재단 → 충남 아산시) 시·도만 본다.
    """
    name = re.sub(r"\s|^(재단법인|사단법인|\((재|사)\))", "", name or "")
    full = next((sd for sd in sorted(resolver.sido, key=len, reverse=True) if sd in name), None)
    if not full:
        full = next((f for short, f in resolver.alias.items() if name.startswith(short)), None)
    return resolver.sido[full] if full else None


def base_row(**values):
    row = {
        "summary": None, "criteria": None, "documents": None, "contact": None, "url": None,
        "category": None, "apply_place": None, "region_code": None, "age_min": None, "age_max": None,
        "gender": None, "household": None, "has_income_rule": False, "for_person": True, "views": 0,
    }
    row.update(values)
    return row


def welfare_rows(records, resolver, collected_at, today=None):
    """민간 복지 지원. 사업 종료일이 지난 것은 뺀다 (끝난 사업이다. 신청 기간이 지난 것과 다르다)."""
    today = today or date.today()
    rows = []
    for r in records:
        name, agency = text(r.get("사업명")), text(r.get("기관명"))
        if not name or not agency:
            continue
        end = (r.get("사업종료일") or "").strip()
        if end and end < today.isoformat():
            continue
        start = (r.get("사업시작일") or "").strip()
        topics = [t for t in (r.get("관심주제") or "").split(",") if t.strip()]
        lives = [t.strip() for t in (r.get("생애주기") or "").split(",") if t.strip()]
        homes = (r.get("가구상황") or "")
        how = "\n".join(t for t in (text(r.get("신청방법")), text(r.get("기타"))) if t) or None
        row = base_row(
            id=make_id("PRV", agency, name), name=name, agency=agency, source="민간 지원",
            category=next((TOPIC_CATEGORY[t] for t in topics if t in TOPIC_CATEGORY), "생활안정"),
            summary=text(r.get("사업목적")), target=text(r.get("지원대상")), content=text(r.get("지원내용")),
            how_to_apply=how, apply_place=agency, documents=text(r.get("제출서류")),
            # 끝나는 날을 2099-12-31처럼 적어 둔 것은 기한 없이 계속하는 사업이다
            apply_period="상시신청" if not end or end >= "2090" else f"{start} ~ {end}",
            url=first_url(r.get("신청방법"), r.get("기타")),
            # 기관 이름에 시·도가 들어 있으면 그 지역 (경남은행사랑나눔재단 → 경상남도). 없으면 전국
            region_code=sido_in(resolver, agency),
            has_income_rule="저소득" in homes, collected_at=collected_at,
        )
        ages = sorted({LIFE_AGES[x] for x in lives if x in LIFE_AGES}) or ["all"]
        special = []
        if homes and all(h in ("장애인",) for h in homes.split(",")):
            special.append("disabled")
        row["_rule_tags"] = (ages, special, None)    # Claude 꼬리표(policy_tags.tsv)가 있으면 그쪽을 쓴다
        rows.append(row)
    return rows


SCHOLARSHIP_WORDS = {
    "성적우수": "성적 좋은 대학생 장학금", "소득구분": "형편이 어려운 대학생 학비", "지역연고": "우리 지역 대학생 장학금",
    "특기자": "특기 있는 학생 장학금", "장애인": "장애 대학생 장학금",
}


def scholarship_rows(records, resolver, collected_at, gov_names=(), today=None):
    """장학금. 같은 장학금이 여러 해 올라와 있으면 가장 최근 모집만 남기고, 끝난 지 오래된 모집은 뺀다."""
    today = today or date.today()
    oldest = (today - timedelta(days=SCHOLARSHIP_RECENT_DAYS)).isoformat()
    gov = {normal_name(n) for n in gov_names}
    latest = {}
    for r in records:
        source = SCHOLARSHIP_SOURCE.get((r.get("운영기관구분") or "").strip())
        name, agency = text(r.get("상품명")), text(r.get("운영기관명"))
        if not source or not name or not agency:
            continue
        if normal_name(name) in gov:   # 정부24에 같은 이름이 있으면 그쪽만 둔다
            continue
        end = (r.get("모집종료일") or "").strip()
        if not end or end < oldest:
            continue
        key = make_id("SCH", agency, name)
        if key not in latest or end > (latest[key].get("모집종료일") or ""):
            latest[key] = r

    rows = []
    for key, r in latest.items():
        name, agency = text(r.get("상품명")), text(r.get("운영기관명"))
        source = SCHOLARSHIP_SOURCE[(r.get("운영기관구분") or "").strip()]
        start, end = (r.get("모집시작일") or "").strip(), (r.get("모집종료일") or "").strip()
        kind = (r.get("학자금유형구분") or "").strip()
        place = text(r.get("지역거주여부 상세내용"))
        who = [f"{label}: {text(r.get(col))}" for col, label in (
            ("대학구분", "학교"), ("학년구분", "학년"), ("학과구분", "학과")) if text(r.get(col))]
        target = "\n".join(t for t in [
            text(r.get("특정자격 상세내용")), f"사는 곳: {place}" if place else None, *who] if t) or None
        criteria = "\n".join(f"{label}: {v}" for label, v in (
            ("성적", text(r.get("성적기준 상세내용"))), ("소득", text(r.get("소득기준 상세내용"))),
            ("받을 수 없는 사람", text(r.get("자격제한 상세내용"))),
            ("추천", text(r.get("추천필요여부 상세내용"))),
        ) if v) or None
        how = "\n".join(t for t in (text(r.get("선발방법 상세내용")),
                                     f"뽑는 인원: {text(r.get('선발인원 상세내용'))}" if text(r.get("선발인원 상세내용")) else None)
                        if t) or None
        if end >= today.isoformat():
            period = f"{start} ~ {end}"
        else:
            period = f"지난 모집 {start} ~ {end} (해마다 비슷한 때 모집하는 경우가 많아요. 홈페이지에서 확인해 주세요)"
        # 지역: 지자체 장학회는 기관 이름으로("영동군민장학회" → 영동군), 사는 곳 조건이 있으면 그 글로 찾는다.
        # 지역 조건이 있는데 어디인지 못 찾으면 UNKNOWN (전국 사람에게 보이지 않게). 민간 재단 이름은 시·도만 본다.
        region = sido_in(resolver, agency)
        if source == "지역 장학금":
            region = resolver.resolve(agency, None)
        if (region is None or region == "UNKNOWN") and (place or kind == "지역연고"):
            region = resolver.resolve(place, None) if place else "UNKNOWN"
        row = base_row(
            id=key, name=name, agency=agency, source=source, category="보육·교육",
            summary=None, target=target, criteria=criteria, content=text(r.get("지원내역 상세내용")),
            how_to_apply=how, apply_place=agency, apply_period=period,
            documents=text(r.get("제출서류 상세내용")), url=first_url(r.get("홈페이지 주소")),
            region_code=region, has_income_rule=bool(text(r.get("소득기준 상세내용"))), collected_at=collected_at,
        )
        graduate = "대학원" in (r.get("대학구분") or "")
        words = ["대학생 장학금", "대학 등록금 도움", "학비 지원"]
        if kind in SCHOLARSHIP_WORDS:
            words.append(SCHOLARSHIP_WORDS[kind])
        if "생활비" in (row["content"] or ""):
            words.append("대학생 생활비")
        row["_rule_tags"] = (["youth", "middle"] if graduate else ["youth"],
                             ["disabled"] if kind == "장애인" else [], " ".join(words))
        rows.append(row)
    return rows

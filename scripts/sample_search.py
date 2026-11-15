"""조회 정확도 확인용 표본 뽑기.

  python scripts/sample_search.py              # 조건 5세트 × 20건을 뽑아 화면에 출력
  python scripts/sample_search.py --json 파일   # 같은 내용을 JSON 파일로도 저장

조건 5세트로 버튼 조회(`/api/search`와 같은 필터)를 하고, 세트마다 결과에서 20건을 무작위로 뽑는다.
뽑은 정책의 원문(소관 기관, 지원 대상, 선정 기준)을 함께 보여 주므로,
사람이 읽고 나이·지역·성별 조건에 맞는지 대조한다. 목표는 조건 부합 90% 이상이다.
난수 씨앗을 고정해서 다시 돌려도 같은 정책이 뽑힌다 (DB 내용이 바뀌면 달라진다).
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.services import retriever  # noqa: E402

SAMPLE_SIZE = 20
SEED = 2026

# 나이대·성별·지역·가구 형태가 골고루 들어가게 고른 조건 5세트
CONDITION_SETS = [
    {"label": "75세 이상 · 여성 · 서울 강남구 · 혼자 살아요",
     "age_group": "75plus", "gender": "F", "region_code": "18101", "household": "single"},
    {"label": "19~34세 · 남성 · 부산 해운대구",
     "age_group": "19_34", "gender": "M", "region_code": "17116", "household": None},
    {"label": "35~49세 · 여성 · 경기 수원시 · 한부모·조손 가정",
     "age_group": "35_49", "gender": "F", "region_code": "12113", "household": "single_parent"},
    {"label": "65~74세 · 남성 · 전북 전주시",
     "age_group": "65_74", "gender": "M", "region_code": "23112", "household": None},
    {"label": "18세 이하 · 여성 · 강원 춘천시",
     "age_group": "u19", "gender": "F", "region_code": "11113", "household": None},
]

COLUMNS = "id, name, agency, region_code, age_min, age_max, gender, household, target, criteria, url"


def sample(conditions, rng):
    where, params = retriever.build_filter(
        conditions["age_group"], conditions["gender"], conditions["region_code"], conditions["household"]
    )
    # 실제 화면과 같이 개인·가구가 받는 지원만 본다
    rows = db.query(f"SELECT {COLUMNS} FROM policy WHERE {where} AND for_person ORDER BY id", params)
    return len(rows), rng.sample(rows, min(SAMPLE_SIZE, len(rows)))


def short(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="뽑은 표본을 저장할 JSON 파일 경로")
    args = parser.parse_args()

    rng = random.Random(SEED)
    output = []
    db.open_pool()
    try:
        samples = [sample(conditions, rng) for conditions in CONDITION_SETS]
    finally:
        db.close_pool()
    for number, (conditions, (total, rows)) in enumerate(zip(CONDITION_SETS, samples), 1):
        print(f"\n== 세트 {number}: {conditions['label']} (조회 결과 {total}건 중 {len(rows)}건) ==")
        for i, r in enumerate(rows, 1):
            print(f"{number}-{i:02d} [{r['id']}] {r['name']} / {r['agency']}")
            print(f"     DB 조건: 지역 {r['region_code'] or '전국'}, 나이 {r['age_min']}~{r['age_max']}, "
                  f"성별 {r['gender'] or '무관'}, 가구 {r['household'] or '무관'}")
            print(f"     지원 대상: {short(r['target'], 400)}")
            print(f"     선정 기준: {short(r['criteria'], 200)}")
        output.append({"set": number, "conditions": conditions, "total": total, "rows": rows})

    if args.json:
        Path(args.json).write_text(json.dumps(output, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()

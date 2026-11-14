"""시나리오 30개 자동 평가.

  python scripts/eval_scenarios.py --no-llm            # 검색만 평가 (Groq를 쓰지 않아 몇 번이든 돌려도 된다)
  python scripts/eval_scenarios.py --no-llm --analyze  # 질문 분석(작은 모델)만 Groq로 하고 검색 평가 (5분쯤 걸림)

--no-llm 평가: 시나리오의 질문을 그대로 검색 문장으로 써서, 기대 정책이 후보 8개 안에 들어오는지 본다.
--analyze 를 붙이면 실제 채팅처럼 질문 분석이 만든 검색 문장(다듬은 문장 + 원래 질문)으로 검색한다. 답변 생성은 하지 않는다.
기대 정책 ID가 비어 있는 시나리오는 후보의 정책명·요약에 기대 분야의 낱말이 있으면 맞은 것으로 본다.
끝에 "맞는 정책"과 "관계없는 질문"의 거리 분포를 출력한다. MAX_DISTANCE 를 정할 때 쓴다.
(LLM을 쓰는 답변 평가는 4주차에 추가)
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, db  # noqa: E402
from app.services import retriever  # noqa: E402

TOP = retriever.CANDIDATE_LIMIT
LOOK = 50  # 8등 밖으로 밀린 기대 정책이 몇 등인지 보려고 넉넉히 가져온다

# 기대 정책 ID가 없는 시나리오에서 쓰는 분야별 낱말
NEED_WORDS = {
    "의료비": ["의료", "진료", "수술", "치료", "검진", "병원"],
    "생활비": ["생계", "생활", "연금", "난방", "에너지", "요금", "감면"],
    "주거": ["주거", "주택", "집수리", "임대", "월세", "전세", "개보수", "수선"],
    "일자리": ["일자리", "취업", "구직", "고용", "창업", "훈련"],
    "돌봄": ["돌봄", "요양", "간병", "보호", "안심"],
    "교육": ["교육", "장학", "학비", "등록금", "학습"],
    "출산·육아": ["출산", "임신", "육아", "양육", "보육", "산모", "아동"],
    "장애": ["장애"],
}
# 지원 정책과 관계없는 질문. 이런 질문의 후보는 모두 버려지는 것이 좋다.
OFF_TOPIC = [
    "오늘 저녁 메뉴 추천해 주세요",
    "내일 서울 날씨가 어때요?",
    "손흥민 선수 나이가 몇 살이에요?",
    "재미있는 영화 하나 알려 주세요",
    "김치찌개 맛있게 끓이는 방법",
    "비트코인 지금 사도 될까요",
]


def search(text, conditions):
    return retriever.search_semantic(
        text,
        age_group=conditions.get("age_group"),
        gender=conditions.get("gender"),
        region_code=conditions.get("region_code"),
        household=conditions.get("household"),
        limit=LOOK,
        max_distance=2.0,  # 평가에서는 거리로 버리지 않고 전부 본다
    )


def summary(values):
    if not values:
        return "없음"
    values = sorted(values)
    return (f"최소 {values[0]:.3f} | 중간 {statistics.median(values):.3f} | "
            f"최대 {values[-1]:.3f} ({len(values)}개)")


def eval_no_llm(analyze=False):
    scenarios = json.loads((config.DATA_DIR / "scenarios.json").read_text(encoding="utf-8"))
    hits, hit_distances, top_distances = 0, [], []
    print(f"검색 평가 (후보 {TOP}개 안에 기대 정책이 있는지)\n")
    by_rules = 0
    for s in scenarios:
        text = s["question"]
        if analyze:
            from app.services import analyzer

            result = analyzer.analyze(text)
            text = result["search_text"]
            by_rules += result["source"] == "rules"
            time.sleep(8)  # 무료 한도(분당 호출 수)를 넘지 않게 천천히 부른다
        rows = search(text, s["conditions"])
        top = rows[:TOP]
        top_distances += [r["distance"] for r in top]
        ranks = {r["id"]: i + 1 for i, r in enumerate(rows)}
        if s["expected_ids"]:
            found = [(ranks[i], i) for i in s["expected_ids"] if i in ranks]
            best = min(found)[0] if found else None
            ok = best is not None and best <= TOP
            detail = f"{best}등" if best else f"{LOOK}등 밖"
            hit_distances += [rows[rank - 1]["distance"] for rank, _ in found if rank <= TOP]
        else:
            words = NEED_WORDS[s["expected_need"]]
            matched = [r for r in top if any(w in (r["name"] + (r["summary"] or "")) for w in words)]
            ok = bool(matched)
            detail = f"분야 낱말 {len(matched)}건"
            hit_distances += [r["distance"] for r in matched]
        hits += ok
        shown = text if analyze else s["question"]
        print(f"{'○' if ok else '✗'} {s['id']:2d} [{s['expected_need']}] {shown[:34]}  → {detail}")
        if not ok:
            for r in top[:3]:
                print(f"       {r['distance']:.3f} {r['name'][:36]}")

    off_best, off_all = [], []
    for text in OFF_TOPIC:
        rows = search(text, {})[:TOP]
        off_best.append(rows[0]["distance"])
        off_all += [r["distance"] for r in rows]

    if analyze and by_rules:
        print(f"\n주의: {by_rules}건은 Groq가 안 돼서 규칙 기반 분석으로 대신했습니다.")
    rate = hits / len(scenarios) * 100
    print(f"\n결과: {hits}/{len(scenarios)} ({rate:.0f}%)  목표 80% 이상 → {'달성' if rate >= 80 else '미달'}")
    print("\n거리 분포 (작을수록 가까움)")
    print("  기대 정책(맞는 정책)      :", summary(hit_distances))
    print("  시나리오 후보 8개 전체    :", summary(top_distances))
    print("  관계없는 질문의 1등 후보  :", summary(off_best))
    print("  관계없는 질문의 후보 전체 :", summary(off_all))
    print(f"\n지금 MAX_DISTANCE = {config.MAX_DISTANCE}")
    for limit in (0.13, 0.14, 0.15, 0.16, 0.17):
        kept = sum(d <= limit for d in hit_distances)
        off = sum(d <= limit for d in off_all)
        print(f"  기준 {limit:.2f}: 맞는 정책 {kept}/{len(hit_distances)}개 남음, "
              f"관계없는 질문 후보 {off}/{len(off_all)}개 남음")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="Groq 없이 검색만 평가")
    parser.add_argument("--analyze", action="store_true", help="질문 분석만 Groq로 해서 검색 문장을 다듬는다")
    args = parser.parse_args()
    if not args.no_llm:
        sys.exit("지금은 --no-llm 평가만 됩니다. (LLM 답변 평가는 4주차에 추가)")
    db.open_pool()
    try:
        eval_no_llm(analyze=args.analyze)
    finally:
        db.close_pool()


if __name__ == "__main__":
    main()

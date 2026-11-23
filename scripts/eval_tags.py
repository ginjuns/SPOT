"""꼬리표 적용 전후 비교용 평가 (AI 안 씀, 몇 번이든 돌려도 된다).

  python scripts/eval_tags.py [시험 문제 파일]     # 기본: data/scenarios_tags.json

시험 문제는 꼬리표를 보지 않은 에이전트가 따로 썼다 (2026-11-23, 어르신 말투 질문 + 나이대 + 정답·금지 정책 이름 낱말).
실제 채팅처럼 자주 묻는 질문이면 그 답을, 아니면 의미 검색 후보 8건(나이 검사 포함)을 본다.
질문 분석 AI는 쓰지 않으므로 검색 문장은 질문 그대로다 (일상 표현 보완 규칙만 적용).
  - 맞음: 정답 낱말이 든 정책이 결과에 있음
  - 금지: 그 나이대에게 나오면 안 되는 정책이 보이는 자리에 있음
    (자주 묻는 질문은 카드 전부, 의미 검색은 앞 5건. 의미 검색 결과는 답변 AI가 한 번 더 거른다)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.services import analyzer, faq, retriever  # noqa: E402

SHOWN = 5


def run(q, age):
    topic = faq.match(q)
    if topic:
        cards = faq.policies(topic, {"age_group": age, "for_child": faq.for_child(topic, q)}, q)
        if cards:
            names = [c["name"] for c in cards]
            return "faq", names, names
    for_child = analyzer.analyze_by_rules(q)["for_child"]
    rows = retriever.search_semantic(
        analyzer.expand(q), age_group=age, for_child=for_child,
        keep=lambda r: faq.fits_age(r, age, for_child, q),
        person_only=not analyzer.mentions_business(q),
    )
    names = [r["name"] for r in rows]
    return "ai", names, names[:SHOWN]


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "scenarios_tags.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    db.open_pool()
    hit = bad = 0
    by_path = {"faq": [0, 0], "ai": [0, 0]}
    for s in items:
        via, names, shown = run(s["question"], s.get("age_group"))
        ok = any(w in n for n in names for w in s["expected_names"])
        wrong = [n for n in shown for w in s.get("forbid_names", []) if w in n]
        hit += ok
        bad += bool(wrong)
        by_path[via][0] += 1
        by_path[via][1] += ok
        mark = ("O" if ok else "X") + ("!" if wrong else " ")
        print(f"{mark} {s['id']} [{s.get('age_group')}/{via}] {s['question'][:40]}")
        if not ok:
            print("     나온 것:", [n[:20] for n in names[:5]])
        if wrong:
            print("     나오면 안 되는 것:", [n[:20] for n in wrong])
    n = len(items)
    print(f"\n결과: 맞음 {hit}/{n} ({hit * 100 // n}%)  금지 정책이 보인 질문 {bad}/{n}")
    for via, (cnt, ok) in by_path.items():
        print(f"  {via}: {cnt}개 중 맞음 {ok}")


if __name__ == "__main__":
    main()

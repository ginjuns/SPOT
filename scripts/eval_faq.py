"""자주 묻는 질문 정확도 평가 (AI를 쓰지 않으므로 몇 번이든 돌려도 된다).

  python scripts/eval_faq.py                         # data/scenarios_faq.json (시험 문제 A)
  python scripts/eval_faq.py data/scenarios_faq_b.json

시험 문제 한 줄 = {"q": 질문, "topic": 기대 주제 id 또는 null(AI로 넘겨야 함), "names": 결과에 있어야 할 정책 이름 낱말}
  맞음: 기대 주제로 답했고, 보여 준 정책 이름에 names 낱말이 있다
  틀림: 다른 주제로 답했거나(null 인데 답한 것 포함), 기대 주제인데 맞는 정책이 없다  ← 가장 나쁘다
  넘김: AI로 넘겼다 (틀리지는 않지만 Groq 한도를 쓴다)
faq.json 의 예시 질문과 겹치지 않는 문장으로 시험해야 정확도를 제대로 볼 수 있다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.services import faq  # noqa: E402

# 정책을 고를 때 쓰는 보기 조건. 나이는 질문마다 맞는 값이 달라서(산후조리 ↔ 노인 일자리) 넣지 않는다.
COND = {"region_code": "11109"}


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "scenarios_faq.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    db.open_pool()
    count = {"맞음": 0, "틀림": 0, "넘김": 0}
    lines = []
    for s in items:
        topic = faq.match(s["q"])
        cards = faq.policies(topic, {**COND, "for_child": topic.get("for_child")}) if topic else []
        names = [c["name"] for c in cards]
        if not cards:   # 주제가 없거나 맞는 정책이 없으면 실제로도 AI로 넘어간다
            kind = "넘김"
        elif s["topic"] and topic["id"] == s["topic"] and any(w in n for n in names for w in s["names"]):
            kind = "맞음"
        else:
            kind = "틀림"
        count[kind] += 1
        if kind != "맞음" and not (kind == "넘김" and s["topic"] is None):
            got = topic["id"] if topic else faq.matched_topics(s["q"])
            lines.append(f"[{kind}] {s['q']}  기대={s['topic']} 결과={got} {names[:3]}")
    print("\n".join(lines))
    expected_ai = sum(1 for s in items if s["topic"] is None)
    total = len(items)
    print(f"\n{path.name}: {total}개 (AI로 넘겨야 하는 질문 {expected_ai}개 포함)")
    print(f"  맞음 {count['맞음']}  틀림 {count['틀림']}  넘김 {count['넘김']}")
    answered = count["맞음"] + count["틀림"]
    if answered:
        print(f"  AI 없이 답한 것 중 맞은 비율: {count['맞음'] * 100 // answered}%  (AI 없이 답한 비율: {answered * 100 // total}%)")


if __name__ == "__main__":
    main()

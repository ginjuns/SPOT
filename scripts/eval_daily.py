"""일상 질문 평가 (data/scenarios_daily.json, 복지 밖 분야까지 35개).

공연·보청기·장례·귀농·법률상담처럼 평소 말투와 정책 이름이 많이 다른 질문에서
맞는 정책이 나오는지 본다. 기대 정책은 이름에 들어갈 낱말(expected_names)로 적었다.

  python scripts/eval_daily.py                 # 검색만 (AI 없이 규칙 보완만. 몇 번이든 돌려도 된다)
  python scripts/eval_daily.py --analyze       # AI 질문 분석 → 검색 (작은 모델, 5분쯤)
  python scripts/eval_daily.py --answer        # 실제 채팅과 똑같이 답변까지 (15분쯤, 하루 1~2번만)
  python scripts/eval_daily.py --answer --region 12 --only 101,106
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.models import ChatRequest  # noqa: E402
from app.services import analyzer, chat_core, rate_limit, retriever  # noqa: E402


def matched(names, scenario):
    return any(w in n for n in names for w in scenario["expected_names"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyze", action="store_true", help="AI 질문 분석으로 검색 문장을 만든다")
    parser.add_argument("--answer", action="store_true", help="답변 생성까지 (실제 채팅과 같다)")
    parser.add_argument("--region", default="", help="지역 코드 (비우면 전국 정책만)")
    parser.add_argument("--only", default="", help="몇 개만 (예: 101,106)")
    args = parser.parse_args()

    items = json.loads((ROOT / "data" / "scenarios_daily.json").read_text(encoding="utf-8"))
    if args.only:
        wanted = {int(x) for x in args.only.split(",")}
        items = [s for s in items if s["id"] in wanted]
    region = args.region or None
    db.open_pool()
    ok = 0
    for s in items:
        q = s["question"]
        if args.answer:
            rate_limit.reset()
            r = chat_core.handle(ChatRequest(message=q, asked=True, conditions={"region_code": region}), "eval")
            names, note = [p["name"] for p in r.get("policies", [])], r["type"]
        else:
            text = analyzer.analyze(q, [])["search_text"] if args.analyze else q
            names = [r["name"] for r in retriever.search_semantic(analyzer.expand(text), region_code=region)]
            note = "후보 8개"
        hit = matched(names, s)
        ok += hit
        print(f"{s['id']} {'O' if hit else 'X'} ({note}) {q}")
        if not hit:
            print("    나온 것:", names[:5])
        if args.answer or args.analyze:
            time.sleep(22 if args.answer else 8)   # Groq 분당 한도
    print(f"결과: {ok}/{len(items)} ({ok * 100 // max(len(items), 1)}%)")


if __name__ == "__main__":
    main()

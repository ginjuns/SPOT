"""실제 채팅과 똑같이(분석 AI + 답변 AI) 시험 문제를 돌리고, 사용자가 받을 답을 파일에 저장한다.

  python scripts/eval_answers.py [시험 문제 파일] [저장할 파일]
  기본: data/scenarios_tags.json → eval_answers.json (현재 폴더)

저장한 답은 사람이나 Claude가 읽고 채점한다 (정답 낱말이 들어 있는지만 보는 자동 채점보다 정확하다).
다시 채점할 때는 저장한 파일을 쓰므로 Groq를 또 부르지 않는다.
Groq 사용량: AI로 가는 질문 1개에 분석 1번(작은 모델) + 답변 1번(큰 모델). 자주 묻는 질문은 0번.
분당 토큰 한도 때문에 AI로 간 질문 뒤에는 20초 쉰다 (60개면 20~30분).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.models import ChatRequest  # noqa: E402
from app.services import chat_core, rate_limit  # noqa: E402


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "scenarios_tags.json"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("eval_answers.json")
    items = json.loads(src.read_text(encoding="utf-8"))
    db.open_pool()
    results = []
    for s in items:
        rate_limit.reset()
        req = ChatRequest(message=s["question"], asked=True, conditions={"age_group": s.get("age_group")})
        started = time.time()
        r = chat_core.handle(req, "eval")
        used_ai = r.get("via") != "faq" and r["type"] in ("result", "none", "fallback")
        policies = [{"name": p["name"], "agency": p.get("agency"), "one_line": p.get("one_line")}
                    for p in r.get("policies", [])]
        hit = any(w in p["name"] for p in policies for w in s["expected_names"])
        results.append({**s, "type": r["type"], "via": r.get("via", "ai"), "text": r.get("text"),
                        "policies": policies, "auto_hit": hit, "seconds": round(time.time() - started, 1)})
        print(f"{'O' if hit else 'X'} {s['id']} [{r['type']}/{r.get('via', 'ai')}] {s['question'][:36]} → "
              f"{[p['name'][:18] for p in policies]}", flush=True)
        dst.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        if used_ai:
            time.sleep(20)
    ok = sum(r["auto_hit"] for r in results)
    print(f"\n자동 채점(정답 낱말): {ok}/{len(results)}  저장: {dst}")


if __name__ == "__main__":
    main()

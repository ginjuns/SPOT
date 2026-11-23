"""자주 묻는 질문(data/faq.json) 검사. DB에는 쓰지 않는다.

  python scripts/load_faq.py

  1. 주제마다 이름 낱말(names)에 맞는 개인 대상 정책이 DB에 있는지
  2. 주제마다 적어 둔 예시 질문(questions)이 그 주제 하나에만 걸리는지 (다른 주제와 겹치면 AI로 넘어간다)
  3. 평가 질문(scenarios.json, scenarios_daily.json)이 몇 개나 AI 없이 답해지고, 그 정책이 맞는지

faq.json 을 고쳤거나 정책을 다시 수집했으면 다시 실행한다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.services import faq  # noqa: E402


def check_names():
    bad = 0
    for t in faq.TOPICS:
        where, params = faq.name_filter(t["names"])
        row = db.query(
            f"SELECT count(*) FILTER (WHERE region_code IS NULL) AS nation, count(*) AS total "
            f"FROM policy WHERE for_person AND ({where})", params)[0]
        if not row["total"]:
            bad += 1
            print(f"  [정책 없음] {t['id']} {t['names']}")
        elif not row["nation"]:
            print(f"  [지역 정책만] {t['id']} {t['names']} ({row['total']}건)")
    print(f"1. 이름 낱말: 주제 {len(faq.TOPICS)}개 중 맞는 정책이 없는 주제 {bad}개")
    return bad


def check_examples():
    bad = 0
    total = 0
    for t in faq.TOPICS:
        for q in t["questions"]:
            total += 1
            topic = faq.match(q)
            if not topic or topic["id"] != t["id"]:
                bad += 1
                print(f"  [{'다른 주제' if topic else '안 걸림·겹침'}] {t['id']}: {q} → {faq.matched_topics(q)}")
    print(f"2. 예시 질문: {total}개 중 자기 주제 하나에만 걸리지 않은 것 {bad}개")
    return bad


def check_scenarios():
    items = json.loads((ROOT / "data" / "scenarios_daily.json").read_text(encoding="utf-8"))
    hit = right = 0
    for s in items:
        topic = faq.pick(s["question"])
        names = [p["name"] for p in faq.policies(topic, {})] if topic else []
        if not names:   # 주제가 없거나 맞는 정책이 없으면 실제 채팅에서도 AI로 넘어간다
            continue
        hit += 1
        ok = any(w in n for n in names for w in s["expected_names"])
        right += ok
        if not ok:
            print(f"  [틀림] {s['id']} {s['question']} → {topic['id']} {names}")
    print(f"3. 일상 질문 {len(items)}개 중 AI 없이 답함 {hit}개, 그중 맞는 정책이 나옴 {right}개")

    items = json.loads((ROOT / "data" / "scenarios.json").read_text(encoding="utf-8"))
    hit = right = 0
    for s in items:
        topic = faq.pick(s["question"])
        cond = {**(s.get("conditions") or {}), "for_child": faq.for_child(topic, s["question"])} if topic else {}
        cards = faq.policies(topic, cond, s["question"]) if topic else []
        if not cards:
            continue
        hit += 1
        ok = any(p["id"] in s["expected_ids"] for p in cards)
        right += ok
        if not ok:
            print(f"  [기대 정책 없음] {s['id']} {s['question']} → {topic['id']} {[p['name'] for p in cards]}")
    print(f"   시나리오 {len(items)}개 중 AI 없이 답함 {hit}개, 그중 기대 정책이 나옴 {right}개")


def main():
    db.open_pool()
    bad = check_names() + check_examples()
    check_scenarios()
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

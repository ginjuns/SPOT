"""꼬리표가 없는 정책에 Groq로 꼬리표를 만들어 data/policy_tags.tsv 에 더한다.

새로 수집한 정책이나 기업·단체 대상 정책처럼 꼬리표가 없는 정책에 쓴다 (PROJECT_SPEC.md 8-6).
  python scripts/ingest.py               # 1) 수집 (새 정책은 꼬리표 없이 들어간다)
  python scripts/tag_new.py              # 2) 꼬리표 없는 정책만 Groq로 꼬리표 만들기 (무료, 10건에 약 40초)
  python scripts/ingest.py --from-raw    # 3) 꼬리표를 붙여 다시 저장 (임베딩에 일상 표현이 들어간다)

처음 9,934건은 Claude가 만들었다. Groq(gpt-oss-120b)는 같은 200건 비교에서 나이 판단이 92% 같았고
"15~65세" 같은 범위를 놓치는 일이 있어서, 지시에 그 점을 따로 적었다.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, db  # noqa: E402
from app.services import tags  # noqa: E402

BATCH = 10
SYSTEM = """너는 정부 지원 정책 자료에 검색용 꼬리표를 붙인다. 정책마다 아래 세 가지를 정해 JSON으로만 답한다.

1. ages: 이 지원을 실제로 받는 사람의 나이 무리 (여러 개 가능)
   child(0~18세 아이·학생 본인), youth(19~34세), middle(35~64세), elder(65세 이상),
   pregnant(임신·출산 당사자, 난임 부부), parent(아이를 키우는 부모가 받는 것), all(나이와 상관없이 누구나)
   - 나이 범위가 적혀 있으면 그대로 따른다. "15~65세" → youth,middle (끝에 1~2살 걸치는 무리는 넣지 않는다)
   - [코드 나이]가 있으면 어긋나지 않게 한다. 성인만이면 youth,middle,elder
   - 사업주·소상공인·농업인·법인이 받는 지원은 그 사업을 하는 어른이 받는다: youth,middle,elder
   - 근로자가 받는 고용보험 급여에 elder 를 함부로 넣지 않는다
2. special: 그 대상만 받으면 적는다 (없으면 빈 목록)
   disabled(장애인), veteran(국가유공자·보훈), defector(북한이탈주민), multicultural(다문화·결혼이민·외국인),
   farmer(농업인·어업인·축산·임업), injured_worker(산업재해 노동자)
3. words: 이 지원이 필요한 사람이 평소에 할 법한 짧은 상황 표현 3~5개
   - 정책 이름이나 제도 용어를 그대로 쓰지 않는다 ("고용안정장려금 신청" ✗ → "직원 육아휴직 때 대체 인력" ○)
   - 질문 문장으로 길게 쓰지 않는다. 글에 없는 금액·조건을 지어내지 않는다.

출력: {"items": [{"id": "정책 ID 그대로", "ages": [...], "special": [...], "words": [...]}]}"""


def block(r):
    cut = lambda s, n: " ".join((s or "").split())[:n]  # noqa: E731
    code = ""
    if r["age_min"] is not None or r["age_max"] is not None:
        code = f" [코드 나이: {r['age_min'] or 0}~{r['age_max'] or 120}세]"
    who = "" if r["for_person"] else " [받는 곳: 기업·소상공인·법인·시설·단체]"
    return (f"[{r['id']}] {r['name']} ({r['agency']}){code}{who}\n 요약: {cut(r['summary'], 120)}\n"
            f" 대상: {cut(r['target'], 260)}\n 내용: {cut(r['content'], 160)}")


def main():
    from groq import Groq, RateLimitError

    db.open_pool()
    have = set(tags.load())
    rows = [r for r in db.query("SELECT id, name, agency, summary, target, content, age_min, age_max, for_person "
                                "FROM policy ORDER BY id") if r["id"] not in have]
    print(f"꼬리표가 없는 정책 {len(rows)}건")
    if not rows:
        return
    client = Groq(api_key=config.GROQ_API_KEY, timeout=120, max_retries=0)
    path = config.DATA_DIR / "policy_tags.tsv"
    with open(path, "a", encoding="utf-8", newline="\n") as out:
        out.write(f"# 아래는 Groq({config.GROQ_MODEL})로 만든 꼬리표 ({time.strftime('%Y-%m-%d')}, scripts/tag_new.py)\n")
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i + BATCH]
            data = None
            for _ in range(6):
                try:
                    r = client.chat.completions.create(
                        model=config.GROQ_MODEL, temperature=0, max_tokens=4000, reasoning_effort="low",
                        response_format={"type": "json_object"},
                        messages=[{"role": "system", "content": SYSTEM},
                                  {"role": "user", "content": "\n".join(block(x) for x in batch)}])
                    data = json.loads(r.choices[0].message.content)
                    break
                except RateLimitError:
                    time.sleep(40)
                except Exception as e:   # 응답이 깨지면 잠시 뒤 다시
                    print("  다시 시도:", type(e).__name__)
                    time.sleep(10)
            got = {str(x.get("id", "")).strip("[] "): x for x in (data or {}).get("items", []) if isinstance(x, dict)}
            for x in batch:
                t = got.get(x["id"])
                if not t:
                    print("  못 만듦:", x["id"], x["name"][:30])
                    continue
                ages = [a for a in t.get("ages") or [] if a in tags.AGES] or ["all"]
                special = [s for s in t.get("special") or [] if s in tags.SPECIALS]
                words = [w.replace("\t", " ").replace(";", ",").strip() for w in t.get("words") or [] if w.strip()]
                out.write("\t".join([x["id"], ",".join(ages), ",".join(special), ";".join(words[:6])]) + "\n")
            out.flush()
            print(f"  {min(i + BATCH, len(rows))}/{len(rows)}", flush=True)
    print("끝. 이제 python scripts/ingest.py --from-raw 로 DB에 반영하세요.")


if __name__ == "__main__":
    main()

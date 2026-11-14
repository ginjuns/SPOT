"""답변 생성 + 검증.

검색된 후보 정책만 LLM에 주고, 상황에 맞는 정책을 고르게 한다.
LLM이 준 답은 그대로 믿지 않는다:
  - 후보 목록에 없는 ID는 버린다.
  - 안내 문장에 목록 밖 정책 이름이나 자격을 확정하는 말이 있으면 정해 둔 문장으로 바꾼다.
"""
import json
from functools import lru_cache

from app import config, db
from app.services import llm, retriever

PROMPT = (config.BASE_DIR / "app" / "prompts" / "answer.txt").read_text(encoding="utf-8")
OPTIONS = json.loads((config.DATA_DIR / "options.json").read_text(encoding="utf-8"))

MAX_PICKS = 5
ONE_LINE_LIMIT = 90
TEXT_LIMIT = 300
MIN_NAME_LENGTH = 4   # 이보다 짧은 정책 이름은 보통 낱말과 겹쳐서 검사하지 않는다
# 자격을 확정하는 말. 이런 말이 있으면 LLM 문장을 쓰지 않는다.
CONFIRMING_WORDS = ["받을 수 있습니다", "받으실 수 있습니다", "받을 수 있어요", "받으실 수 있어요",
                    "대상입니다", "대상이에요", "자격이 됩니다", "자격이 돼요", "해당됩니다"]
FINAL_CHECK = "자격은 신청하는 곳에서 최종 확인해 주세요."


def _label(group, value):
    return next((o["label"] for o in OPTIONS[group] if o["value"] == value), None)


def _cut(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def build_user_prompt(situation, conditions, candidates):
    cond = [
        _label("age_group", conditions.get("age_group")),
        _label("gender", conditions.get("gender")),
        _label("household", conditions.get("household")),
    ]
    cond = ", ".join(c for c in cond if c)
    lines = ["<사용자 상황>", situation]
    if cond:
        lines.append(f"조건: {cond}")
    lines += ["</사용자 상황>", "<후보 정책>"]
    limit = config.CANDIDATE_TEXT_LIMIT
    for c in candidates:
        lines.append(
            f"[{c['id']}] {c['name']} / 대상: {_cut(c['target'], limit)} / 내용: {_cut(c['content'], limit)}"
        )
    lines.append("</후보 정책>")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _all_policy_names():
    """DB의 모든 정책 이름 (목록 밖 정책 언급 검사용). 서버가 켜져 있는 동안 1번만 읽는다."""
    return frozenset(
        r["name"] for r in db.query("SELECT DISTINCT name FROM policy")
        if len(r["name"]) >= MIN_NAME_LENGTH
    )


def mentions_outside_policy(text, candidates, all_names=None):
    """안내 문장에 후보 목록 밖의 정책 이름이 들어 있는지."""
    names = _all_policy_names() if all_names is None else all_names
    # 아래 경우는 문제 삼지 않는다:
    #  - 후보 이름의 일부인 이름 (후보 "청년월세 지원" 안의 "월세 지원")
    #  - 후보 정책의 DB 글에 원래 나오는 이름 ("훈련연장급여"의 설명에 나오는 "구직급여")
    allowed = " ".join(
        str(c.get(key) or "") for c in candidates for key in ("name", "summary", "target", "content")
    )
    return any(name in text and name not in allowed for name in names)


def default_text(count):
    return f"확인해 볼 만한 지원 {count}건을 찾았어요. {FINAL_CHECK}"


def validate(raw, candidates, all_names=None):
    """LLM 응답을 검사해서 {"text", "picks"} 로 돌려준다. picks 가 비면 맞는 정책이 없는 것이다."""
    by_id = {c["id"]: c for c in candidates}
    picks, seen = [], set()
    for item in raw.get("picks") if isinstance(raw.get("picks"), list) else []:
        if not isinstance(item, dict):
            continue
        pid = item.get("id")
        if not isinstance(pid, str):
            continue
        pid = pid.strip().strip("[]")
        if pid not in by_id or pid in seen:   # 목록에 없는 ID, 같은 ID 반복은 버린다
            continue
        seen.add(pid)
        one_line = item.get("one_line")
        one_line = _cut(one_line, ONE_LINE_LIMIT) if isinstance(one_line, str) else ""
        if not one_line or mentions_outside_policy(one_line, [by_id[pid]], all_names):
            one_line = retriever.one_line(by_id[pid]["summary"])
        picks.append({"id": pid, "one_line": one_line})
        if len(picks) == MAX_PICKS:
            break

    text = raw.get("text")
    text = " ".join(text.split()) if isinstance(text, str) else ""
    if (
        not text
        or len(text) > TEXT_LIMIT
        or any(w in text for w in CONFIRMING_WORDS)
        or mentions_outside_policy(text, [by_id[p["id"]] for p in picks], all_names)
    ):
        text = default_text(len(picks))
    elif "최종 확인" not in text and "확인해 보세요" not in text and "확인해 주세요" not in text:
        text = f"{text} {FINAL_CHECK}"
    return {"text": text, "picks": picks}


def answer(situation, conditions, candidates):
    """후보 정책 중 상황에 맞는 것을 고른다. LLM이 안 되면 llm.LLMError 가 그대로 올라간다."""
    raw = llm.chat_json(
        config.GROQ_MODEL, PROMPT, build_user_prompt(situation, conditions, candidates),
        max_tokens=900, backup=config.GROQ_MODEL_BACKUP,
    )
    return validate(raw, candidates)

"""POST /api/chat — 질문 분석 → 되묻기 → 검색 → 답변 생성.

서버는 대화를 저장하지 않는다. 이전 대화와 정해진 조건은 브라우저가 매번 같이 보낸다.
"""
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from app.models import ChatRequest
from app.services import analyzer, answerer, llm, privacy, rate_limit, retriever

router = APIRouter(prefix="/api")
logger = logging.getLogger("benefit")

MESSAGE_LIMIT = 300
HISTORY_LIMIT = 6
HISTORY_TEXT_LIMIT = 300

# 되묻기 문구는 LLM이 만들지 않고 여기 정해 둔 것만 쓴다.
ASK_TEXT = {
    ("age_group", "region"): "맞는 지원을 찾으려고 몇 가지만 여쭤볼게요. 나이대와 사시는 지역을 골라 주세요.",
    ("age_group",): "맞는 지원을 찾으려고 한 가지만 여쭤볼게요. 나이대를 골라 주세요.",
    ("region",): "맞는 지원을 찾으려고 한 가지만 여쭤볼게요. 사시는 지역을 골라 주세요.",
}
NONE_TEXT = (
    "말씀하신 상황에 맞는 지원을 찾지 못했어요. "
    "가까운 주민센터나 보건복지상담센터(국번 없이 129)에 물어보시면 도움을 받을 수 있어요."
)
REGION_HINT = "사시는 지역을 알려 주시면 지역 지원도 찾아 드려요."
FALLBACK_TEXT = "지금은 AI 답변이 어려워요. 버튼으로 찾아 볼까요?"
USER_LIMIT_TEXT = "오늘 질문 횟수를 다 쓰셨어요. 버튼으로 찾기는 계속 쓸 수 있어요."


def merge_conditions(sent, analysis):
    """브라우저가 보낸 조건과 이번 분석 결과를 합친다. 버튼으로 고른 값이 우선."""
    merged = {
        key: sent.get(key) or analysis.get(key)
        for key in ("age_group", "gender", "region_code", "household")
    }
    # "75살이고 서울 살아요"처럼 조건만 덧붙인 말이면 앞에서 정한 분야·검색 문장을 그대로 둔다.
    keep_previous = bool(sent.get("search_text")) and analysis.get("need") == "기타"
    source = sent if keep_previous else analysis
    merged["need"] = source.get("need")
    merged["search_text"] = source.get("search_text")
    return merged


def fallback(text, conditions=None):
    """AI 답변이 안 될 때: 화면은 버튼 조회로 안내한다. 조건은 버튼 조회에 이어 쓰라고 돌려준다."""
    response = {"type": "fallback", "text": text}
    if conditions:
        response["conditions"] = conditions
    return response


def handle(req, client_key):
    message = req.message.strip()
    if len(message) > MESSAGE_LIMIT:
        raise HTTPException(400, "조금만 짧게 말씀해 주세요.")
    sent = req.conditions.model_dump()
    if not message and not sent.get("search_text"):
        raise HTTPException(400, "궁금한 점을 말씀해 주세요.")

    limit = rate_limit.check(client_key, is_question=bool(message))
    if limit != rate_limit.OK:
        text = USER_LIMIT_TEXT if limit == rate_limit.USER_LIMIT else FALLBACK_TEXT
        return fallback(text, {k: sent.get(k) for k in ("age_group", "gender", "region_code", "household")})

    masked = False
    if message:
        message, masked = privacy.mask(message)
        history = [
            {"role": h.role, "text": privacy.mask(h.text[:HISTORY_TEXT_LIMIT])[0]}
            for h in req.history[-HISTORY_LIMIT:]
        ]
        conditions = merge_conditions(sent, analyzer.analyze(message, history))
    else:
        # 버튼으로 조건만 고른 호출: 분석(LLM)을 건너뛰고 바로 검색한다.
        conditions = sent
    notice = " " + privacy.NOTICE if masked else ""

    missing = tuple(
        name for name, key in (("age_group", "age_group"), ("region", "region_code"))
        if not conditions.get(key)
    )
    if missing and not req.asked:
        return {"type": "ask", "text": ASK_TEXT[missing] + notice, "ask": list(missing), "conditions": conditions}

    candidates = retriever.search_semantic(
        conditions["search_text"],
        age_group=conditions["age_group"],
        gender=conditions["gender"],
        region_code=conditions["region_code"],
        household=conditions["household"],
    )
    if not candidates:
        return {"type": "none", "text": NONE_TEXT + notice, "conditions": conditions}

    try:
        answer = answerer.answer(conditions["search_text"], conditions, candidates)
    except llm.LLMError:
        return fallback(FALLBACK_TEXT, conditions)
    if not answer["picks"]:
        return {"type": "none", "text": NONE_TEXT + notice, "conditions": conditions}

    # 카드 내용은 DB 값 그대로. LLM이 쓴 것은 한 줄 요약(one_line)뿐이다.
    by_id = {c["id"]: c for c in candidates}
    policies = [
        {**retriever.to_card(by_id[p["id"]]), "one_line": p["one_line"]} for p in answer["picks"]
    ]
    text = answer["text"]
    if not conditions["region_code"]:
        text += " " + REGION_HINT
    return {"type": "result", "text": text + notice, "policies": policies, "conditions": conditions}


@router.post("/chat")
def chat(req: ChatRequest, request: Request):
    started = time.perf_counter()
    response = handle(req, rate_limit.client_key(request))
    # 질문 내용은 남기지 않는다. 결과 유형과 걸린 시간만 남긴다.
    logger.info("chat %s %dms", response["type"], (time.perf_counter() - started) * 1000)
    return response

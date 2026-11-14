"""POST /api/chat — 질문 분석 → 되묻기 또는 후보 정책 목록.

서버는 대화를 저장하지 않는다. 이전 대화와 정해진 조건은 브라우저가 매번 같이 보낸다.
(답변 생성과 사용량 제한은 3주차에 추가)
"""
import logging
import time

from fastapi import APIRouter, HTTPException

from app.models import ChatRequest
from app.services import analyzer, privacy, retriever

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


def result_text(need, count, has_region, masked):
    if need and need != "기타":
        # 끝 글자에 받침이 있으면 "과", 없으면 "와" (돌봄과, 의료비와)
        has_final = (ord(need[-1]) - 0xAC00) % 28 != 0
        topic = f"{need}{'과' if has_final else '와'} 관련해"
    else:
        topic = "말씀하신 내용과 관련해"
    parts = [f"{topic} 확인해 볼 만한 지원 {count}건을 찾았어요. 자격은 신청하는 곳에서 최종 확인해 주세요."]
    if not has_region:
        parts.append(REGION_HINT)
    if masked:
        parts.append(privacy.NOTICE)
    return " ".join(parts)


def handle(req):
    message = req.message.strip()
    if len(message) > MESSAGE_LIMIT:
        raise HTTPException(400, "조금만 짧게 말씀해 주세요.")
    sent = req.conditions.model_dump()
    masked = False

    if message:
        message, masked = privacy.mask(message)
        history = [
            {"role": h.role, "text": privacy.mask(h.text[:HISTORY_TEXT_LIMIT])[0]}
            for h in req.history[-HISTORY_LIMIT:]
        ]
        conditions = merge_conditions(sent, analyzer.analyze(message, history))
    elif sent.get("search_text"):
        # 버튼으로 조건만 고른 호출: 분석(LLM)을 건너뛰고 바로 검색한다.
        conditions = sent
    else:
        raise HTTPException(400, "궁금한 점을 말씀해 주세요.")

    missing = tuple(
        name for name, key in (("age_group", "age_group"), ("region", "region_code"))
        if not conditions.get(key)
    )
    if missing and not req.asked:
        text = ASK_TEXT[missing] + (" " + privacy.NOTICE if masked else "")
        return {"type": "ask", "text": text, "ask": list(missing), "conditions": conditions}

    rows = retriever.search_semantic(
        conditions["search_text"],
        age_group=conditions["age_group"],
        gender=conditions["gender"],
        region_code=conditions["region_code"],
        household=conditions["household"],
    )
    if not rows:
        return {"type": "none", "text": NONE_TEXT, "conditions": conditions}
    return {
        "type": "result",
        "text": result_text(conditions["need"], len(rows), bool(conditions["region_code"]), masked),
        "policies": [retriever.to_card(r) for r in rows],
        "conditions": conditions,
    }


@router.post("/chat")
def chat(req: ChatRequest):
    started = time.perf_counter()
    response = handle(req)
    # 질문 내용은 남기지 않는다. 결과 유형과 걸린 시간만 남긴다.
    logger.info("chat %s %dms", response["type"], (time.perf_counter() - started) * 1000)
    return response

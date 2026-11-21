"""POST /api/chat — 웹 채팅. 실제 처리는 services/chat_core.py가 한다.

서버는 대화를 저장하지 않는다. 이전 대화와 정해진 조건은 브라우저가 매번 같이 보낸다.
"""
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from app.models import ChatRequest
from app.services import chat_core, rate_limit

router = APIRouter(prefix="/api")
logger = logging.getLogger("benefit")


@router.post("/chat")
def chat(req: ChatRequest, request: Request):
    started = time.perf_counter()
    response = chat_core.handle(req, rate_limit.client_key(request))
    # 질문 내용은 남기지 않는다. 결과 유형과 걸린 시간만 남긴다.
    # via=faq: 자주 묻는 질문으로 AI 없이 답했다 (AI 호출이 얼마나 줄었는지 보려고 남긴다).
    logger.info("chat %s%s %dms", response["type"], " faq" if response.get("via") == "faq" else "",
                (time.perf_counter() - started) * 1000)
    if response["type"] == "error":
        raise HTTPException(400, response["text"])
    return response

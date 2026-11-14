"""Groq 클라이언트 래퍼: 타임아웃, 재시도, 실패 처리.

LLM이 안 되면 LLMError 를 던진다. 부르는 쪽에서 규칙 기반 분석이나 버튼 조회 안내로 넘어간다.
질문 내용은 로그에 남기지 않는다 (오류 종류만 남긴다).
"""
import json
import logging
from functools import lru_cache

from app import config

logger = logging.getLogger("benefit")

TIMEOUT_SECONDS = 15


class LLMError(Exception):
    """LLM 호출 실패 (키 없음, 한도 초과, 시간 초과, JSON이 아닌 응답 등)."""


@lru_cache(maxsize=1)
def _client():
    from groq import Groq

    # 재시도는 아래에서 직접 1번만 한다.
    return Groq(api_key=config.GROQ_API_KEY, timeout=TIMEOUT_SECONDS, max_retries=0)


def chat_json(model, system, user, max_tokens=600):
    """JSON 모드로 물어보고 dict 를 돌려준다. 실패하면 1번 다시 시도한 뒤 LLMError."""
    if not config.GROQ_API_KEY:
        raise LLMError("no_key")
    from groq import RateLimitError

    options = {}
    if config.GROQ_REASONING_EFFORT:
        options["reasoning_effort"] = config.GROQ_REASONING_EFFORT
    last = "unknown"
    for _ in range(2):
        try:
            response = _client().chat.completions.create(
                model=model,
                temperature=0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                **options,
            )
            data = json.loads(response.choices[0].message.content or "")
            if isinstance(data, dict):
                return data
            last = "not_object"
        except RateLimitError:
            # 무료 한도 초과는 바로 다시 불러도 소용없다.
            logger.warning("llm 실패: rate_limit")
            raise LLMError("rate_limit") from None
        except Exception as e:
            last = type(e).__name__
        logger.warning("llm 실패: %s", last)
    raise LLMError(last)

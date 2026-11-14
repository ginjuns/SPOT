"""하루 질문 수 제한 (메모리 기반. 서버가 다시 켜지면 처음부터 센다).

- 사용자별: IP를 해시한 값 기준으로 하루 DAILY_CHAT_LIMIT 번
- 서비스 전체: 하루 GLOBAL_DAILY_CHAT_LIMIT 번 (Groq 무료 한도가 시연 중에 바닥나지 않게)
- 버튼으로 조건만 고른 재호출은 질문 횟수에 넣지 않는다. 다만 재호출만 끝없이 보내서
  한도를 피해 가는 것을 막으려고 따로 넉넉한 한도(질문 한도의 2배)를 둔다.
IP 원문은 어디에도 남기지 않는다. 매번 새로 만드는 임의 값과 섞어 해시한 것만 메모리에 둔다.
"""
import datetime
import hashlib
import secrets
import threading

from app import config

OK, USER_LIMIT, GLOBAL_LIMIT = "ok", "user_limit", "global_limit"
RECALL_FACTOR = 2

_lock = threading.Lock()
_salt = secrets.token_bytes(16)
_day = None
_counts = {}   # (종류, 사용자 해시 또는 "*") → 오늘 횟수


def client_key(request):
    """요청 → 사용자 구분 값. 프록시 뒤에서는 X-Forwarded-For 의 첫 번째 값이 실제 접속 IP다."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return hashlib.sha256(_salt + ip.encode()).hexdigest()[:16]


def check(key, is_question, today=None):
    """한도 안이면 횟수를 올리고 OK. 넘었으면 USER_LIMIT 또는 GLOBAL_LIMIT (횟수는 올리지 않는다)."""
    global _day
    today = today or datetime.date.today()
    kind = "q" if is_question else "r"
    factor = 1 if is_question else RECALL_FACTOR
    with _lock:
        if _day != today:   # 날짜가 바뀌면 처음부터
            _day = today
            _counts.clear()
        if _counts.get((kind, "*"), 0) >= config.GLOBAL_DAILY_CHAT_LIMIT * factor:
            return GLOBAL_LIMIT
        if _counts.get((kind, key), 0) >= config.DAILY_CHAT_LIMIT * factor:
            return USER_LIMIT
        _counts[(kind, "*")] = _counts.get((kind, "*"), 0) + 1
        _counts[(kind, key)] = _counts.get((kind, key), 0) + 1
        return OK


def reset():
    """테스트용."""
    global _day
    with _lock:
        _day = None
        _counts.clear()

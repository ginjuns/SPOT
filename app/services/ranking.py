"""이번 달 많이 본 지원: 정책 상세 화면이 열린 횟수로 한 달 순위를 만든다.

- 한 달 = RANKING_START(2026-11-25)부터 매달 같은 날에 새로 시작한다 (11.25~12.24, 12.25~1.24 …).
- 같은 사람(접속 IP를 해시한 값)이 같은 정책을 같은 날 여러 번 열어도 한 번만 센다.
  그 확인은 메모리에서만 하고 저장하지 않는다. DB에는 정책별 숫자만 남는다 (누가 봤는지는 남기지 않는다).
- 지난달 숫자는 지우지 않고 기간별로 남는다.
"""
import datetime
import threading

from app import config, db

TOP = 5
_lock = threading.Lock()
_seen = set()     # (날짜, 사용자 해시, 정책 ID) — 오늘 이미 센 것
_seen_day = None


def period(today=None):
    """오늘이 속한 한 달의 (시작일, 끝일)."""
    today = today or datetime.date.today()
    start = datetime.date.fromisoformat(config.RANKING_START)
    day = min(start.day, 28)   # 29~31일은 없는 달이 있어서 28일로 본다
    months = (today.year - start.year) * 12 + (today.month - start.month) - (1 if today.day < day else 0)
    months = max(months, 0)

    def add(m):
        y, mo = divmod(start.month - 1 + m, 12)
        return datetime.date(start.year + y, mo + 1, day)

    begin = add(months)
    return begin, add(months + 1) - datetime.timedelta(days=1)


def record(policy_id, client_key, today=None):
    """상세 화면 한 번 열림을 센다. 오늘 이미 센 것이면 False."""
    global _seen_day
    today = today or datetime.date.today()
    with _lock:
        if _seen_day != today:   # 날짜가 바뀌면 처음부터
            _seen.clear()
            _seen_day = today
        key = (client_key, policy_id)
        if key in _seen:
            return False
        _seen.add(key)
    db.execute(
        "INSERT INTO policy_view_month (period_start, policy_id, views) "
        "SELECT %(p)s, id, 1 FROM policy WHERE id = %(id)s "
        "ON CONFLICT (period_start, policy_id) DO UPDATE SET views = policy_view_month.views + 1",
        {"p": period(today)[0], "id": policy_id},
    )
    return True


def top(today=None, limit=TOP):
    """이번 달 많이 본 지원. 기록이 limit 개보다 적으면 정부24 조회수가 많은 개인 대상 전국 정책으로 채운다."""
    begin, end = period(today)
    rows = db.query(
        "SELECT p.id, p.name, p.agency, v.views FROM policy_view_month v JOIN policy p ON p.id = v.policy_id "
        "WHERE v.period_start = %(p)s ORDER BY v.views DESC, p.views DESC, p.id LIMIT %(n)s",
        {"p": begin, "n": limit},
    )
    if len(rows) < limit:
        rows += db.query(
            # 정렬은 정부24 조회수(policy.views). 이번 달 조회수를 "0 AS views"로 두면 정렬이 그 0을 따라가서 안 된다.
            "SELECT id, name, agency FROM policy WHERE for_person AND region_code IS NULL "
            "AND NOT (id = ANY(%(ids)s)) ORDER BY policy.views DESC, id LIMIT %(n)s",
            {"ids": [r["id"] for r in rows], "n": limit - len(rows)},
        )
    return {"period_start": begin.isoformat(), "period_end": end.isoformat(),
            "items": [{"id": r["id"], "name": r["name"], "agency": r["agency"]} for r in rows]}


def reset():
    """테스트용."""
    global _seen_day
    with _lock:
        _seen.clear()
        _seen_day = None

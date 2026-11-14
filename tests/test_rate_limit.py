import datetime

import pytest

from app import config
from app.services import rate_limit
from app.services.rate_limit import GLOBAL_LIMIT, OK, USER_LIMIT, check


@pytest.fixture(autouse=True)
def limits(monkeypatch):
    monkeypatch.setattr(config, "DAILY_CHAT_LIMIT", 3)
    monkeypatch.setattr(config, "GLOBAL_DAILY_CHAT_LIMIT", 5)
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_user_limit():
    assert [check("a", True) for _ in range(4)] == [OK, OK, OK, USER_LIMIT]
    assert check("b", True) == OK   # 다른 사용자는 영향 없음


def test_global_limit():
    for user in "abcde":
        assert check(user, True) == OK
    assert check("f", True) == GLOBAL_LIMIT


def test_button_recalls_do_not_use_up_questions():
    for _ in range(6):               # 재호출 한도는 질문 한도의 2배
        assert check("a", False) == OK
    assert check("a", False) == USER_LIMIT
    assert check("a", True) == OK    # 질문 횟수는 그대로 남아 있다


def test_counts_reset_on_a_new_day():
    day1, day2 = datetime.date(2026, 11, 14), datetime.date(2026, 11, 15)
    assert [check("a", True, day1) for _ in range(4)][-1] == USER_LIMIT
    assert check("a", True, day2) == OK


def test_client_key_uses_first_forwarded_ip_and_hides_it():
    class Request:
        def __init__(self, forwarded, host="10.0.0.1"):
            self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
            self.client = type("C", (), {"host": host})()

    a = rate_limit.client_key(Request("203.0.113.7, 10.0.0.1"))
    assert a == rate_limit.client_key(Request("203.0.113.7, 10.9.9.9"))   # 첫 번째 값만 본다
    assert a != rate_limit.client_key(Request("203.0.113.8, 10.0.0.1"))
    assert a != rate_limit.client_key(Request(None))                      # 헤더가 없으면 접속 IP
    assert "203.0.113.7" not in a and len(a) == 16

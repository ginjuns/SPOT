"""이번 달 많이 본 지원 (정책 상세 조회수 한 달 순위) 테스트. DB 없이 돈다."""
import datetime

from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import ranking

client = TestClient(app)
D = datetime.date


def test_period_is_monthly_from_start(monkeypatch):
    monkeypatch.setattr(config, "RANKING_START", "2026-11-25")
    assert ranking.period(D(2026, 11, 25)) == (D(2026, 11, 25), D(2026, 12, 24))
    assert ranking.period(D(2026, 12, 24)) == (D(2026, 11, 25), D(2026, 12, 24))
    assert ranking.period(D(2026, 12, 25)) == (D(2026, 12, 25), D(2027, 1, 24))
    assert ranking.period(D(2027, 1, 3)) == (D(2026, 12, 25), D(2027, 1, 24))
    # 시작일 전에는 첫 달로 본다
    assert ranking.period(D(2026, 11, 1))[0] == D(2026, 11, 25)


def test_same_person_same_policy_counted_once_a_day(monkeypatch):
    writes = []
    monkeypatch.setattr(ranking.db, "execute", lambda sql, params: writes.append(params))
    ranking.reset()
    day = D(2026, 11, 26)
    assert ranking.record("P1", "user-a", day) is True
    assert ranking.record("P1", "user-a", day) is False     # 같은 날 다시 열어도 한 번
    assert ranking.record("P1", "user-b", day) is True      # 다른 사람은 따로
    assert ranking.record("P1", "user-a", D(2026, 11, 27)) is True   # 다음 날은 다시 센다
    assert [w["id"] for w in writes] == ["P1", "P1", "P1"]
    assert writes[0]["p"] == D(2026, 11, 25)
    ranking.reset()


def test_top_fills_with_popular_policies(monkeypatch):
    calls = []

    def fake_query(sql, params):
        calls.append(sql)
        if "policy_view_month" in sql:
            return [{"id": "P1", "name": "기초연금", "agency": "보건복지부", "views": 3}]
        return [{"id": f"F{i}", "name": f"정책{i}", "agency": "기관"} for i in range(params["n"])]

    monkeypatch.setattr(ranking.db, "query", fake_query)
    result = ranking.top(D(2026, 11, 30))
    assert [i["id"] for i in result["items"]] == ["P1", "F0", "F1", "F2", "F3"]
    assert result["period_start"] == "2026-11-25" and result["period_end"] == "2026-12-24"


def test_view_endpoint(monkeypatch):
    seen = []
    monkeypatch.setattr(ranking, "record", lambda pid, key: seen.append(pid) or True)
    assert client.post("/api/policy/SSE000000170/view").json() == {"counted": True}
    assert client.post("/api/policy/bad id!/view").status_code in (400, 404)
    assert seen == ["SSE000000170"]

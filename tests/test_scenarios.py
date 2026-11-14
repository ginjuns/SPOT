"""data/scenarios.json 형식 검사 (DB 없이)."""
import csv
import json

from app import config
from app.models import Conditions
from app.services.analyzer import NEEDS

SCENARIOS = json.loads((config.DATA_DIR / "scenarios.json").read_text(encoding="utf-8"))


def test_thirty_scenarios_with_unique_ids():
    assert len(SCENARIOS) == 30
    assert [s["id"] for s in SCENARIOS] == list(range(1, 31))
    assert len({s["question"] for s in SCENARIOS}) == 30


def test_fields_and_values():
    with open(config.DATA_DIR / "regions.csv", encoding="utf-8", newline="") as f:
        region_codes = {r["code"] for r in csv.DictReader(f)}
    for s in SCENARIOS:
        assert set(s) == {"id", "question", "conditions", "expected_need", "expected_ids", "note"}, s["id"]
        assert 0 < len(s["question"]) <= 300, s["id"]
        assert s["expected_need"] in NEEDS, s["id"]
        assert isinstance(s["expected_ids"], list), s["id"]
        Conditions(**s["conditions"])  # 정해진 값이 아니면 오류
        assert s["conditions"]["region_code"] in region_codes, s["id"]


def test_every_need_is_covered():
    assert {s["expected_need"] for s in SCENARIOS} >= set(NEEDS) - {"기타"}

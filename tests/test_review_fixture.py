import json
import runpy
from copy import deepcopy
from pathlib import Path

from survey.records import current_fields, validate_records

REPO = Path(__file__).parents[1]
FIXTURE = runpy.run_path(str(REPO / "scripts/review_fixture.py"))


def test_fixture_adaptation_preserves_values_and_original_example():
    example = json.loads((REPO / "schema/example-r01-excerpt.json").read_text())
    before = deepcopy(example)
    record = FIXTURE["adapt_record"](example)
    assert example == before
    assert record["schema_version"] == "0.4.0"
    assert record["region"] == "216460"
    validate_records([record], "216460")
    old_fields = dict(current_fields(example))
    for path, field in current_fields(record):
        assert field["confidence"] is None
        assert {k: v for k, v in field.items() if k != "confidence"} == {
            k: v for k, v in old_fields[path].items() if k != "confidence"
        }
        assert "review" not in field
    household = record["dwelling"]["households"][0]
    assert household["record_id"] == "27-0006-01"
    assert len(record["dwelling"]["households"]) == 1
    assert [card["page"] for card in household["cards"]] == [3, 4]
    assert all(card["image"] == FIXTURE["PDF"] for card in household["cards"])

    assert [card["page"] for card in record["dwelling"]["cards"]] == [1, 2]
    assert all(card["image"] == FIXTURE["PDF"] for card in record["dwelling"]["cards"])

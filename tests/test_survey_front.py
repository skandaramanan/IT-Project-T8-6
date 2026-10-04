"""FR-03: a survey front becomes dwelling number, address and person grid."""

import json
from pathlib import Path

import jsonschema
import pytest

from survey.extraction.card_fields import survey_front_label
from survey.extraction.survey_front import build_survey_front

DEFS = json.loads(
    (Path(__file__).parent.parent / "schema/record-envelope.schema.json").read_text()
)["$defs"]


@pytest.mark.parametrize(
    "raw, status, value",
    [
        ("£4..15", "ok", "£4..15"),
        ("23/-", "ok", "23/-"),
        ("", "no_data", None),
        ("—", "no_data", None),
        ("...", "no_data", None),
        ("__", "no_data", None),
    ],
)
def test_text_cells_are_kept_verbatim(raw, status, value):
    field = build_survey_front({"Address": raw})["address"]
    assert (field["status"], field["value"]) == (status, value)
    assert field["source"] == "survey-front"
    assert "negated" not in field
    jsonschema.validate(field, {"$defs": DEFS, "$ref": "#/$defs/field"})


def test_columns_with_something_read_become_persons():
    front = build_survey_front(
        {
            survey_front_label("Relationship", 1): "Head",
            survey_front_label("Craft", 1): "Labourer",
            survey_front_label("Relationship", 2): "Wife",
            survey_front_label("Relationship", 3): "",
        }
    )
    assert front["dwelling_no"]["status"] == "omitted"
    head, wife = front["persons"]
    assert head["craft"]["value"] == "Labourer"
    assert wife["craft"]["status"] == "omitted"
    for person in front["persons"]:
        jsonschema.validate(person, {"$defs": DEFS, "$ref": "#/$defs/person"})

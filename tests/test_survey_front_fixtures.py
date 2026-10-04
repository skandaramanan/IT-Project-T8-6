"""The FR-03 survey-front fixtures, and Gemini checked against them."""

import json
import os
import re
from pathlib import Path

import pytest
from support import assert_intact_jpeg

from survey.extraction.card_fields import (
    SURVEY_FRONT_COLUMNS,
    SURVEY_FRONT_DWELLING_FIELDS,
    SURVEY_FRONT_PERSON_ROWS,
)
from survey.extraction.survey_front import build_survey_front, record_key

FIXTURES = Path(__file__).parent / "fixtures"
GROUND_TRUTH = json.loads((FIXTURES / "survey_front/ground_truth.json").read_text())
CARDS = pytest.mark.parametrize("card", GROUND_TRUTH["cards"], ids=lambda c: c["image"])


@CARDS
def test_ground_truth_is_well_formed(card):
    assert_intact_jpeg(FIXTURES / card["image"])
    assert "Dwelling Number (top-left corner)" in card["fields"]
    assert set(card["fields"]) <= set(SURVEY_FRONT_DWELLING_FIELDS)
    assert all(isinstance(e, str) and e for e in card["fields"].values())
    assert len(card["persons"]) <= SURVEY_FRONT_COLUMNS
    for person in card["persons"]:
        assert "Relationship" in person and set(person) <= set(SURVEY_FRONT_PERSON_ROWS)
        assert all(isinstance(e, str) and e for e in person.values())


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .,;:").casefold()


def _matches(field: dict, expected) -> bool:
    if expected == "*":
        return True
    if expected is None:
        return field["status"] == "no_data"
    return field["status"] == "ok" and _norm(field["value"]) == _norm(expected)


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="needs GEMINI_API_KEY")
@CARDS
def test_extraction_matches_ground_truth(card):
    from survey.extraction.gemini import GeminiExtractor

    result = GeminiExtractor(survey_front=True).extract(FIXTURES / card["image"])
    front = build_survey_front(result.fields)
    read = [p["relationship"]["value"] for p in front["persons"]]
    assert len(front["persons"]) == len(card["persons"]), f"persons read: {read}"
    checks = [
        (label, front[record_key(label)], card["fields"].get(label))
        for label in SURVEY_FRONT_DWELLING_FIELDS
    ]
    for n, (person, expected) in enumerate(zip(front["persons"], card["persons"]), 1):
        checks += [
            (f"person {n} {row}", person[record_key(row)], expected.get(row))
            for row in SURVEY_FRONT_PERSON_ROWS
        ]
    misses = [
        f"{where}: got {f['status']} {f['value']!r}, expected {e!r}"
        for where, f, e in checks
        if not _matches(f, e)
    ]
    assert not misses, "\n".join(misses)

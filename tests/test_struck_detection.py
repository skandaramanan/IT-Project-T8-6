"""Struck-option detection: prompt shape and parser correctness."""

import json
from pathlib import Path

from survey.extraction.card_fields import FIELD_SCHEMA_BY_NAME
from survey.extraction.json_extraction import (
    BANDED_STRUCK_EXTRACTION_PROMPT,
    STRUCK_EXTRACTION_PROMPT,
    parse_confidence_bands,
    parse_json_fields,
    parse_struck_fields,
)

MANIFEST = json.loads(
    (Path(__file__).parent / "fixtures" / "crossed_out" / "manifest.json").read_text()
)


def _response_for(marks: list[dict], must_not_negate: list[dict]) -> str:
    """A model response matching one image's ground truth exactly."""
    body = {mark["field"]: {"value": "x", "struck": True} for mark in marks}
    for entry in must_not_negate:
        if "field" in entry:
            body[entry["field"]] = {"value": "x", "struck": False}
    return json.dumps(body)


def _marks_by_image(fixture: dict) -> dict[str, list[dict]]:
    """Marks grouped by the image each is actually on. A fixture whose marks
    span more than one image (e.g. the same field struck on two separate
    scans) must be tested per image -- collapsing them into one dict keyed by
    field name would silently drop every image but the last."""
    by_image: dict[str, list[dict]] = {}
    for mark in fixture.get("marks", []):
        image = mark.get("image", fixture.get("image"))
        by_image.setdefault(image, []).append(mark)
    return by_image


def test_every_manifest_mark_names_a_real_schema_field():
    """The round-trip this replaced was tautological -- _response_for built the
    response from the marks, so the parser could only return them. What is
    worth pinning is that the manifest names fields the schema actually has."""
    for fixture in MANIFEST["fixtures"]:
        for mark in fixture.get("marks", []):
            assert mark["field"] in FIELD_SCHEMA_BY_NAME, mark["field"]


def test_absent_and_false_and_non_bool_all_mean_not_struck():
    response = json.dumps(
        {
            "A": {"value": "1", "struck": True},
            "B": {"value": "1", "struck": False},
            "C": {"value": "1"},
            "D": "1",
            "E": {"value": "1", "struck": "yes"},
        }
    )
    assert parse_struck_fields(response) == {"A": True}


def test_fenced_and_truncated_output_still_parses():
    fenced = parse_struck_fields('```json\n{"A": {"value": "1", "struck": true}}\n```')
    assert fenced == {"A": True}
    truncated = parse_struck_fields('{"A": {"value": "1", "struck": true}, "B": {"val')
    assert truncated == {"A": True}


def test_none_and_unparseable_report_nothing_struck():
    assert parse_struck_fields(None) == {}
    assert parse_struck_fields("not json") == {}


def test_prompt_asks_for_the_column_slash_rule():
    """The prompt states the rule. Whether the model obeys it is unmeasured --
    no column slash has been found on a coding card, so there is no fixture."""
    assert "entire column" in STRUCK_EXTRACTION_PROMPT


def test_prompt_asks_for_the_boundary_overlap_rule():
    """As above: the instruction is pinned, the model's compliance is not."""
    assert "neighbouring field" in STRUCK_EXTRACTION_PROMPT


def test_parser_reports_only_the_field_marked_struck():
    """Parser-level only: a response saying one of two is struck yields one."""
    response = json.dumps(
        {
            "A": {"value": "1", "struck": True},
            "B": {"value": "1", "struck": False},
        }
    )
    assert parse_struck_fields(response) == {"A": True}


def test_values_survive_the_struck_prompts_three_key_shape():
    """parse_json_fields must still find values when the response carries
    value/confidence/struck, or struck mode silently extracts nothing."""
    response = json.dumps(
        {
            "Municipality": {"value": "27", "confidence": "high", "struck": False},
            "Garden": {"value": "3", "struck": True},
        }
    )
    assert parse_json_fields(response) == {"Municipality": "27", "Garden": "3"}


def test_banded_and_struck_are_both_readable_from_one_combined_response():
    """The combined prompt lets one call carry both signals; each parser
    reads its own key regardless of the other being present."""
    assert "confidence" in BANDED_STRUCK_EXTRACTION_PROMPT
    assert "struck" in BANDED_STRUCK_EXTRACTION_PROMPT
    response = json.dumps({"A": {"value": "1", "confidence": "high", "struck": True}})
    assert parse_confidence_bands(response) == {"A": "high"}
    assert parse_struck_fields(response) == {"A": True}

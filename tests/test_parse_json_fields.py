"""Parsing rejects a response that answers a different question.

A model that emits a placeholder object parses cleanly and leaves every schema
field empty, which scores well on a card that is mostly empty cells -- so the
parser has to reject it rather than let it through as a partial answer.
"""

import pytest
from json_extraction import (
    BANDED_EXTRACTION_PROMPT,
    EXTRACTION_PROMPT,
    parse_field_statuses,
    parse_json_fields,
)


def test_placeholder_object_is_rejected():
    assert parse_json_fields('{"A": null, "B": null, "C": null}') is None


def test_partial_answer_is_kept():
    fields = parse_json_fields('{"Municipality": "56", "No. of Dwelling": 83}')
    assert fields == {"Municipality": "56", "No. of Dwelling": "83"}


def test_fenced_and_truncated_output_still_parses():
    fenced = parse_json_fields('```json\n{"Municipality": "56"}\n```')
    assert fenced == {"Municipality": "56"}
    truncated = parse_json_fields('{"Municipality": "56", "No. of Dwelling": "8')
    assert truncated == {"Municipality": "56"}


def test_banded_shape_unwraps_to_the_same_fields():
    """The banded prompt nests each value; everything downstream still expects
    a flat {field: value}, so one parser has to read both shapes."""
    banded = parse_json_fields(
        '{"Municipality": {"value": "56", "confidence": "high"},'
        ' "Weekly Rent": {"value": "04", "confidence": "low"}}'
    )
    assert banded == {"Municipality": "56", "Weekly Rent": "04"}


def test_bands_are_read_back_only_where_reported():
    from json_extraction import parse_confidence_bands

    bands = parse_confidence_bands(
        '{"Municipality": {"value": "56", "confidence": "HIGH"},'
        ' "Weekly Rent": {"value": "04", "confidence": "not a band"},'
        ' "Garden": "3"}'
    )
    # case-folded; an invented band and a flat value both report nothing rather
    # than a made-up default
    assert bands == {"Municipality": "high"}


def test_unbanded_output_reports_no_bands():
    from json_extraction import parse_confidence_bands

    assert parse_confidence_bands('{"Municipality": "56"}') == {}
    assert parse_confidence_bands(None) == {}


def test_status_shape_preserves_value_keys_and_statuses():
    payload = (
        '{"Municipality": {"value": "56", "status": "ok"},'
        ' "Weekly Rent": {"value": null, "status": "illegible"}}'
    )
    assert parse_json_fields(payload) == {"Municipality": "56", "Weekly Rent": ""}
    statuses = parse_field_statuses(payload)
    assert statuses["Municipality"] == "ok"
    assert statuses["Weekly Rent"] == "illegible"
    assert statuses["Garden"] == "omitted"


def test_flat_output_has_no_status_map():
    assert parse_field_statuses('{"Municipality": "56"}') is None


def test_standard_and_banded_prompts_both_request_statuses():
    assert '"status"' in EXTRACTION_PROMPT
    assert '"confidence"' not in EXTRACTION_PROMPT
    assert '"status"' in BANDED_EXTRACTION_PROMPT
    assert '"confidence"' in BANDED_EXTRACTION_PROMPT


@pytest.mark.parametrize(
    "payload",
    [
        '{"Municipality": {"value": "56", "status": "unreadable"}}',
        '{"Municipality": {"value": "56"}}',
        '{"Municipality": {"status": "no_data"}}',
        '{"Municipality": {"value": null, "status": "ok"}}',
        '{"Municipality": {"value": "56", "status": "no_data"}}',
        '{"Municipality": {"value": null, "status": "omitted"}}',
    ],
)
def test_malformed_status_output_is_rejected(payload):
    with pytest.raises(ValueError):
        parse_field_statuses(payload)

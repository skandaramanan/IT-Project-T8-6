"""Parsing rejects a response that answers a different question.

A model that emits a placeholder object parses cleanly and leaves every schema
field empty, which scores well on a card that is mostly empty cells -- so the
parser has to reject it rather than let it through as a partial answer.
"""

from json_extraction import parse_json_fields


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

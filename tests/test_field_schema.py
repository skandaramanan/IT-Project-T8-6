"""The schema names the fields the sheet actually has, and links only real codes.

A name that drifts from the ground-truth header is the expensive failure: the
extractor is asked for a key nothing scores against, so the field reads as
wrong on every card and the headline accuracy drops with no visible cause. The
same goes for a category link that doesn't resolve -- describe_field() would
raise mid-prompt-build, or worse, quietly describe the wrong code set.
"""

import pytest
from ground_truth import (
    C3_GROUND_TRUTH_XLSX,
    DEFAULT_GROUND_TRUTH_XLSX,
    field_names,
)

from extraction.code_book import CLOSED_CATEGORIES, SENTINEL_CODES
from extraction.field_schema import (
    C3_FIELD_SCHEMA,
    FIELD_SCHEMA,
    build_extraction_prompt_schema,
    describe_field,
)


@pytest.mark.parametrize(
    ("schema", "xlsx"),
    [
        (FIELD_SCHEMA, DEFAULT_GROUND_TRUTH_XLSX),
        (C3_FIELD_SCHEMA, C3_GROUND_TRUTH_XLSX),
    ],
    ids=["c1c2", "c3"],
)
def test_schema_names_match_the_sheet_in_order(schema, xlsx):
    if not xlsx.exists():
        pytest.skip(f"{xlsx} not synced -- see README, 'Data and secrets'")
    assert [spec.name for spec in schema] == field_names(xlsx)


def test_every_code_book_link_resolves():
    for spec in FIELD_SCHEMA + C3_FIELD_SCHEMA:
        if spec.code_book_category is None:
            continue
        assert (
            spec.code_book_category in CLOSED_CATEGORIES
            or spec.code_book_category in SENTINEL_CODES
        ), f"{spec.name} -> {spec.code_book_category}"


def test_confirmed_kinds_carry_their_link():
    """categorical/numeric_sentinel are claims about a table -- name the table.

    Without this an unlinked "categorical" silently falls through
    describe_field() to the "scheme not confirmed" line, which reads as an
    honest unknown while the schema claims otherwise.
    """
    for spec in FIELD_SCHEMA + C3_FIELD_SCHEMA:
        if spec.kind in ("categorical", "numeric_sentinel"):
            assert spec.code_book_category, spec.name


def test_unknown_fields_say_why():
    for spec in FIELD_SCHEMA:
        if spec.kind == "unknown":
            assert spec.notes, spec.name


def test_prompt_block_is_one_line_per_field():
    assert len(build_extraction_prompt_schema().splitlines()) == len(FIELD_SCHEMA)
    assert len(build_extraction_prompt_schema(C3_FIELD_SCHEMA).splitlines()) == len(
        C3_FIELD_SCHEMA
    )


def test_sentinel_fields_name_their_codes_in_the_prompt():
    """FR-08: 997/998/999 must stay distinct, so the model has to be told."""
    line = describe_field(next(s for s in FIELD_SCHEMA if s.name == "Earnings of Head"))
    assert "997" in line and "998" in line and "999" in line

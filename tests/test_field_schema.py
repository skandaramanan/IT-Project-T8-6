"""The card field lists are internally coherent.

Narrow on purpose. This does not check that a field is linked to the *right*
code book category -- that was settled by checking observed values against the
code book, card by card, and is not re-derivable here. What it checks is that
nothing in either list is silently broken, because both failure modes are
silent:

- A mistyped category name raises nothing until ``describe_field`` happens to
  reach that field while building a prompt.
- A duplicated field name is swallowed by ``FIELD_SCHEMA_BY_NAME``'s dict
  comprehension, and the field disappears from the extraction prompt with no
  error anywhere.

The second is the one worth guarding. A field that quietly stops existing looks
exactly like a field the card never had.
"""

from typing import get_args

import pytest

from extraction.code_book import CLOSED_CATEGORIES, SENTINEL_CODES
from extraction.field_schema import (
    C3_FIELD_SCHEMA,
    FIELD_SCHEMA,
    FIELD_SCHEMA_BY_NAME,
    FIELD_STATUS_DEFINITIONS,
    FieldKind,
    FieldStatus,
    build_extraction_prompt_schema,
)

CARDS = [("C1/C2", FIELD_SCHEMA), ("C3", C3_FIELD_SCHEMA)]


def test_field_kind_excludes_no_data():
    assert set(get_args(FieldKind)) == {
        "categorical",
        "numeric_sentinel",
        "numeric_free",
        "unknown",
    }


def test_c3_unobserved_fields_are_unknown_kind():
    """Keep this provisional expectation until nonblank C3 examples establish
    each field's shape or code-book mapping.

    The two O/C. fields may become numeric_free counts, while Facilities Shared
    may become categorical if its values match the Shared vocabulary.
    """
    names = {
        "Facilities Shared",
        "House No. of Families O/C. (Liv.B)",
        "House No. of Families O/C. (Liv.A)",
    }
    specs = {spec.name: spec for spec in C3_FIELD_SCHEMA}

    assert {name: specs[name].kind for name in names} == {
        name: "unknown" for name in names
    }


def test_field_statuses_and_definitions_are_complete():
    statuses = {"ok", "no_data", "illegible", "damaged", "omitted"}

    assert set(get_args(FieldStatus)) == statuses
    assert set(FIELD_STATUS_DEFINITIONS) == statuses


@pytest.mark.parametrize(("card", "schema"), CARDS)
def test_categorical_fields_name_a_real_category(card, schema):
    for spec in schema:
        if spec.kind != "categorical":
            continue
        assert spec.code_book_category, (
            f"{card}: {spec.name} is categorical with no category"
        )
        assert spec.code_book_category in CLOSED_CATEGORIES, (
            f"{card}: {spec.name} names '{spec.code_book_category}', "
            f"which is not a CLOSED_CATEGORIES table"
        )


@pytest.mark.parametrize(("card", "schema"), CARDS)
def test_sentinel_fields_name_a_real_sentinel_table(card, schema):
    for spec in schema:
        if spec.kind != "numeric_sentinel":
            continue
        assert spec.code_book_category, (
            f"{card}: {spec.name} has sentinels but no category"
        )
        assert spec.code_book_category in SENTINEL_CODES, (
            f"{card}: {spec.name} names '{spec.code_book_category}', "
            f"which is not a SENTINEL_CODES table"
        )


@pytest.mark.parametrize(("card", "schema"), CARDS)
def test_field_names_are_unique(card, schema):
    """A duplicate name doesn't collide -- it overwrites, and the card loses a field."""
    names = [spec.name for spec in schema]
    duplicates = {name for name in names if names.count(name) > 1}
    assert not duplicates, f"{card}: duplicated field names {sorted(duplicates)}"


@pytest.mark.parametrize(("card", "schema"), CARDS)
def test_every_field_reaches_the_prompt(card, schema):
    """The prompt is what the model is actually asked for. A field that doesn't
    make it into this block cannot be extracted, however well it is typed."""
    lines = build_extraction_prompt_schema(schema).splitlines()
    assert len(lines) == len(schema), (
        f"{card}: {len(schema)} fields typed but {len(lines)} lines in the prompt"
    )


def test_lookup_covers_the_whole_c1_c2_card():
    """FIELD_SCHEMA_BY_NAME is what callers resolve a model's key against."""
    assert len(FIELD_SCHEMA_BY_NAME) == len(FIELD_SCHEMA)

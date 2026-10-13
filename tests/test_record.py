"""A coding card becomes a valid D007 record.

The fixture below is a hand-written stand-in, not a transcription -- these
tests are about the translation, not about how well any model reads a card.
Real model output lives under data/benchmark/, which is gitignored, so nothing
here may depend on it.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from survey.extraction.card_fields import FIELD_SCHEMA
from survey.extraction.record import (
    FIELD_MAP,
    build_record,
    build_record_id,
    clean_text,
    fill_identity,
    identity_of,
    normalise,
)

SCHEMA = json.loads(
    (
        Path(__file__).parent.parent / "schema" / "record-envelope.schema.json"
    ).read_text()
)

CARD = {
    "Municipality": "27",
    "Number of Dwelling": "6",
    "Number of Household": "1",
    "Structural Material": "1",
    "Tenure": "1",
    "Weekly Rent": "04",
    "Normal Household I.": "999",
    "Sex of Head": "0",
    "Age of Head": "54",
    "Number under 5": "-",
}


def record():
    return build_record(CARD, region="williamstown", batch="test")


# --- the whole card survives ------------------------------------------------


def test_every_card_field_is_mapped():
    """A field missing from FIELD_MAP is never emitted and never errors -- it
    just stops existing, which is indistinguishable from a card that never had
    it."""
    assert {spec.name for spec in FIELD_SCHEMA} == set(FIELD_MAP)


def test_no_two_fields_share_a_key():
    keys = [key for key, _ in FIELD_MAP.values()]
    assert len(keys) == len(set(keys))


def test_the_record_carries_all_62_fields():
    rec = record()
    household = rec["dwelling"]["households"][0]
    emitted = (
        2  # municipality and dwelling_no sit on the dwelling
        + 1  # household_no on the household
        + len(rec["dwelling"]["house"])
        + len(household["head"])
        + len(household["counts"])
        + len(household["coding"])
    )
    assert emitted == len(FIELD_SCHEMA)


def test_fields_the_model_omitted_are_still_emitted_as_omitted():
    """CARD holds 10 of 62. The rest are absent from the model's answer, and
    have to come back as omitted rather than vanish."""
    counts = record()["dwelling"]["households"][0]["counts"]
    assert counts["home_duties"]["status"] == "omitted"
    assert counts["home_duties"]["value"] is None


def test_returned_empty_field_is_no_data_not_omitted():
    """An explicitly returned empty value is a data-availability outcome."""
    fields = CARD | {"Home Duties": None}
    counts = build_record(fields, region="williamstown", batch="test")["dwelling"][
        "households"
    ][0]["counts"]
    assert counts["home_duties"]["status"] == "no_data"
    assert counts["home_duties"]["value"] is None


# --- cleaning ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.", "1"),  # leader dots read as part of the number
        ("1.5.", "15"),
        ("O4", "04"),  # handwritten 0 read as a letter
        ("!", "1"),
        ("-", ""),  # transcriber's void mark
        ("BB", ""),  # coder voided the cell, one B per column
        (None, ""),
        ("null", ""),  # the model quoted its null; folded, it was "nu11"
        (" NULL ", ""),
    ],
)
def test_normalise(raw, expected):
    assert normalise(raw) == expected


def test_quoted_null_is_blank_text():
    assert clean_text("null") == ""
    assert clean_text("Nullarbor St") == "Nullarbor St"


def test_leading_zeros_are_kept():
    """Fixed-width codes: 04 and 4 are two different codes, not two spellings
    of one."""
    assert normalise("04") == "04"


def test_void_marks_become_no_data():
    counts = record()["dwelling"]["households"][0]["counts"]
    assert counts["number_under_5"]["status"] == "no_data"


# --- decoding ---------------------------------------------------------------


def test_codes_carry_their_meaning():
    assert record()["dwelling"]["house"]["structural_material"]["label"] == "Wood"


def test_sentinels_stay_values_with_a_label():
    """FR-08: 999 means 'over £10'. It must never collapse into missing."""
    field = record()["dwelling"]["households"][0]["coding"]["normal_household_income"]
    assert field["value"] == "999"
    assert field["status"] == "ok"
    assert field["label"] == "Unknown because over £10"


def test_confidence_is_always_null():
    """NFR-01: no benchmarked engine produces a per-field score, and inventing
    one would present an uncertain reading as a confident one."""
    household = record()["dwelling"]["households"][0]
    for group in (household["head"], household["counts"], household["coding"]):
        assert all(field["confidence"] is None for field in group.values())


# --- identity ---------------------------------------------------------------


def test_record_id_is_zero_padded():
    assert build_record_id("27", "6", "1") == "27-0006-01"


def test_record_id_needs_all_three_parts():
    """Dwelling number alone repeats across municipalities."""
    with pytest.raises(ValueError):
        build_record_id("27", "", "1")


def test_a_lettered_dwelling_keeps_its_letter():
    assert build_record_id("21", "487a", "1") == "21-0487A-01"


@pytest.mark.parametrize(
    "identity", [("06", "276303", "1"), ("18", "285", "101"), ("2115", "74", "1")]
)
def test_a_struck_number_read_with_its_replacement_is_no_record_id(identity):
    with pytest.raises(ValueError):
        build_record_id(*identity)


def test_a_card_without_a_usable_identity_is_still_a_record():
    record = build_record(
        {"Municipality": "06", "Number of Dwelling": "276303"}, region="r"
    )
    assert record["dwelling"]["households"][0]["record_id"] is None


# --- the envelope -----------------------------------------------------------


def test_record_validates_against_the_envelope():
    jsonschema.validate(record(), SCHEMA)


def test_a_second_reading_only_fills_what_the_first_lacks():
    first = {"Municipality": "21", "Number of Dwelling": "481512", "Garden": "1"}
    second = {
        "Municipality": "21",
        "Number of Dwelling": "481",
        "Number of Household": "1",
    }
    filled = fill_identity(first, second)
    assert identity_of(filled) == "21-0481-01"
    assert filled["Garden"] == "1"
    # It may not overrule a part the first read has.
    with pytest.raises(ValueError):
        fill_identity({**first, "Municipality": "05"}, {**second, "Municipality": "25"})
    with pytest.raises(ValueError):
        fill_identity(first, {"Municipality": "21"})

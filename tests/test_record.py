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

from extraction.field_schema import FIELD_SCHEMA
from extraction.record import (
    FIELD_MAP,
    build_record,
    build_record_id,
    build_record_outcome,
    normalise,
)

SCHEMA = json.loads(
    (
        Path(__file__).parent.parent / "docs" / "schema" / "record-envelope.schema.json"
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
    ],
)
def test_normalise(raw, expected):
    assert normalise(raw) == expected


def test_leading_zeros_are_kept():
    """Fixed-width codes: 04 and 4 are two different codes, not two spellings
    of one."""
    assert normalise("04") == "04"


def test_void_marks_become_no_data():
    counts = record()["dwelling"]["households"][0]["counts"]
    assert counts["number_under_5"]["status"] == "no_data"


@pytest.mark.parametrize("status", ["illegible", "damaged"])
def test_unreadable_status_discards_a_candidate_value(status):
    fields = CARD | {"Age of Head": "54"}
    head = build_record(
        fields,
        statuses={"Age of Head": status},
        region="williamstown",
        batch="test",
    )["dwelling"]["households"][0]["head"]
    assert head["age_of_head"]["status"] == status
    assert head["age_of_head"]["value"] is None


def test_contradictory_status_and_value_is_rejected():
    with pytest.raises(ValueError, match="no_data"):
        build_record(
            CARD,
            statuses={"Age of Head": "no_data"},
            region="williamstown",
        )


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


@pytest.mark.parametrize("identity", ["Municipality", "Number of Dwelling", "Number of Household"])
def test_degraded_identity_is_quarantined(identity):
    outcome = build_record_outcome(
        CARD,
        statuses={identity: "illegible"},
        region="williamstown",
        batch="test",
        image="tests/fixtures/r01-coding-front.jpg",
        page=1,
    )
    assert outcome.record is None
    assert outcome.quarantine["reason"] == "incomplete_identity"
    assert outcome.quarantine["identity_fields"][identity]["status"] == "illegible"
    assert outcome.quarantine["identity_fields"][identity]["value"] is None


def test_valid_identity_builds_a_record_outcome():
    outcome = build_record_outcome(CARD, region="williamstown", batch="test")
    assert outcome.quarantine is None
    assert outcome.record["dwelling"]["households"][0]["record_id"] == "27-0006-01"


def test_c3_field_names_are_not_accepted_by_c1_c2_record_conversion():
    with pytest.raises(ValueError, match="unknown fields"):
        build_record(CARD, statuses={"Facilities Shared": "ok"}, region="williamstown")


# --- the envelope -----------------------------------------------------------


def test_record_validates_against_the_envelope():
    jsonschema.validate(record(), SCHEMA)

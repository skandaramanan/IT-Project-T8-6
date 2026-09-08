"""Pairing two extractors' readings: what counts as agreement, and what doesn't.

The class that matters most is NO_SECOND_OPINION. Every other mistake here
makes a confidence score slightly wrong; collapsing a missing arm into AGREE
makes it confidently wrong, on exactly the cards where a reviewer most needs
the truth. IT-99 AC4 exists for that case and these tests are its guard.

No API and no data/ -- both arms are constructed as plain dicts, or as text
files under tmp_path.
"""

import json

import pytest
from dual_extract import (
    AGREE,
    ARM_NO_OUTPUT,
    ARM_OK,
    ARM_UNPARSEABLE,
    BOTH_BLANK,
    DISAGREE,
    NO_SECOND_OPINION,
    ONE_BLANK,
    SCHEMA_FIELD_NAMES,
    classify,
    compare_fields,
    load_arm,
    pair_cards,
)

FIELDS = ["Municipality", "Weekly Rent", "Garden"]


# --- the five classes -------------------------------------------------------


@pytest.mark.parametrize(
    "first, second, expected",
    [
        ("56", "56", AGREE),
        ("3", "8", DISAGREE),
        ("3", "", ONE_BLANK),
        ("", "3", ONE_BLANK),
        ("", "", BOTH_BLANK),
        (None, None, BOTH_BLANK),  # both omitted the key: both read no code
        ("-", "B", BOTH_BLANK),  # transcriber's dash vs the coder's void mark
    ],
)
def test_each_class(first, second, expected):
    assert classify(first, second) == expected


@pytest.mark.parametrize(
    "first, second",
    [("1", "1."), ("15", "1.5."), ("0", "O"), ("1", "L"), (" 3 ", "3")],
)
def test_noise_is_not_disagreement(first, second):
    """The artefacts IT-98 AC2 lists: leader dots, digit lookalikes, whitespace."""
    assert classify(first, second) == AGREE


@pytest.mark.parametrize("first, second", [("04", "4"), ("4", "04"), ("060", "60")])
def test_leading_zero_split_is_a_real_disagreement(first, second):
    """IT-98 AC2b. Under a fixed-width code book these are different codes, so
    one model has misread a real value -- that has to pull confidence down, not
    be normalised away (D011)."""
    assert classify(first, second) == DISAGREE


# --- a missing arm ----------------------------------------------------------


def test_missing_second_arm_is_never_agreement():
    """The one that would inflate every downstream confidence number."""
    paired = compare_fields({"Municipality": "56"}, None, FIELDS)
    assert {f["agreement"] for f in paired.values()} == {NO_SECOND_OPINION}


def test_missing_arm_beats_both_blank():
    """Two models agreeing a card is empty and one model never answering are
    different claims. A run that half-failed must not read as a clean one."""
    absent = compare_fields({}, None, FIELDS)
    blank = compare_fields({}, {}, FIELDS)
    assert absent["Garden"]["agreement"] == NO_SECOND_OPINION
    assert blank["Garden"]["agreement"] == BOTH_BLANK


def test_missing_first_arm_is_handled_too():
    paired = compare_fields(None, {"Municipality": "56"}, FIELDS)
    assert paired["Municipality"]["agreement"] == NO_SECOND_OPINION
    assert paired["Municipality"]["b_raw"] == "56"


# --- shape ------------------------------------------------------------------


def test_every_schema_field_is_emitted():
    """A card is 62 fields whatever the models returned, so a field one model
    dropped is visible as a comparison rather than absent (D011's argument)."""
    paired = compare_fields({"Municipality": "56"}, {"Municipality": "56"})
    assert len(paired) == 62
    assert set(paired) == set(SCHEMA_FIELD_NAMES)
    assert paired["Weekly Rent"]["agreement"] == BOTH_BLANK


def test_raw_readings_are_preserved_unmodified():
    """AC4: a disputed field traces back to what each model actually said,
    without re-parsing the raw response blob."""
    paired = compare_fields({"Municipality": "5.6."}, {"Municipality": "56"}, FIELDS)
    field = paired["Municipality"]
    assert (field["a_raw"], field["b_raw"]) == ("5.6.", "56")
    assert (field["a"], field["b"]) == ("56", "56")  # normalised alongside, not instead
    assert field["agreement"] == AGREE


# --- reading both arms off disk ---------------------------------------------


def _write(root, model, page_id, payload):
    raw = root / model / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"{page_id}.txt").write_text(
        payload if isinstance(payload, str) else json.dumps(payload)
    )


def test_load_arm_reports_why_a_card_has_no_reading(tmp_path):
    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    _write(tmp_path, "a", "p2", "the model apologised instead of answering")
    fields, statuses = load_arm(tmp_path, "a")
    assert fields["p1"] == {"Municipality": "56"}
    assert statuses == {"p1": ARM_OK, "p2": ARM_UNPARSEABLE}
    assert fields["p2"] is None


def test_pair_cards_takes_the_union_not_the_intersection(tmp_path):
    """A card only one arm reached still belongs in the output. Intersecting
    would make a half-failed run look complete."""
    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    _write(tmp_path, "a", "p2", {"Municipality": "27"})
    _write(tmp_path, "b", "p1", {"Municipality": "56"})

    records = {r["page_id"]: r for r in pair_cards("a", "b", tmp_path, FIELDS)}
    assert set(records) == {"p1", "p2"}
    assert records["p1"]["fields"]["Municipality"]["agreement"] == AGREE
    assert records["p2"]["fields"]["Municipality"]["agreement"] == NO_SECOND_OPINION
    assert records["p2"]["arms"]["b"]["status"] == ARM_NO_OUTPUT
    assert records["p2"]["arms"]["a"]["status"] == ARM_OK


def test_counts_add_up_to_the_field_count(tmp_path):
    _write(tmp_path, "a", "p1", {"Municipality": "56", "Weekly Rent": "04"})
    _write(tmp_path, "b", "p1", {"Municipality": "56", "Weekly Rent": "4"})
    record = pair_cards("a", "b", tmp_path, FIELDS)[0]
    assert sum(record["counts"].values()) == len(FIELDS)
    assert record["counts"] == {AGREE: 1, DISAGREE: 1, BOTH_BLANK: 1}

"""Settlement must not replace a coding card's missing municipality with a sibling's."""

from copy import deepcopy
from pathlib import Path

import pytest

from survey.association.records import build_dwelling_records
from survey.extraction.base import ExtractionResult
from survey.pipeline import _merge
from survey.segmentation.segmenter import CardType, SegmentedCard


def _records(second_municipality="", second_household="2", third_municipality=None):
    readings = [
        (CardType.FRONT, {"Dwelling Number (top-left corner)": "5"}),
        (
            CardType.NUMERIC_CODING,
            {
                "Municipality": "27",
                "Number of Dwelling": "5",
                "Number of Household": "1",
            },
        ),
        (
            CardType.NUMERIC_CODING,
            {
                "Municipality": second_municipality,
                "Number of Dwelling": "5",
                "Number of Household": second_household,
            },
        ),
    ]
    if third_municipality is not None:
        readings.append(
            (
                CardType.NUMERIC_CODING,
                {
                    "Municipality": third_municipality,
                    "Number of Dwelling": "5",
                    "Number of Household": "1",
                },
            )
        )
    extracted = [
        (
            SegmentedCard(kind, Path(f"{page}.png"), Path("unit.pdf"), page),
            ExtractionResult(fields=fields),
        )
        for page, (kind, fields) in enumerate(readings)
    ]
    # Each card a page of one scan, as the pipeline places them (D026).
    return build_dwelling_records(
        extracted, region="north", locate=lambda c: ("unit.pdf", c.page_index + 1)
    )[0]


def _ids(records):
    return [h["record_id"] for h in records[0]["dwelling"]["households"]]


def _duplicates(records):
    """Which cards, in order, are flagged as sharing a record_id."""
    return [
        "duplicate_record_id" in h["flags"]
        for r in records
        for h in r["dwelling"]["households"]
    ]


def _correct(field, value):
    field.update(
        original_value=field["value"], value=value, origin="corrected", status="ok"
    )


def test_missing_later_municipality_stays_null_on_initial_merge_and_rerun():
    built = _records()
    assert _ids(built) == ["27-0005-01", None]
    merged = _merge([], built)
    assert _ids(merged) == ["27-0005-01", None]
    assert "missing_record_id" in merged[0]["dwelling"]["flags"]
    rerun = _merge(merged, _records())
    assert _ids(rerun) == ["27-0005-01", None]
    assert "missing_record_id" in rerun[0]["dwelling"]["flags"]


@pytest.mark.parametrize("index", [0, 1])
def test_household_number_correction_does_not_supply_missing_municipality(index):
    old = _records()
    _correct(old[0]["dwelling"]["households"][index]["household_no"], "3")
    merged = _merge(old, _records())
    assert _ids(merged) == ["27-0005-03" if index == 0 else "27-0005-01", None]
    assert "missing_record_id" in merged[0]["dwelling"]["flags"]


def test_dwelling_number_correction_does_not_supply_missing_municipality():
    old = _records()
    _correct(old[0]["dwelling"]["households"][0]["dwelling_no"], "6")
    merged = _merge(old, _records())
    assert _ids(merged) == ["27-0006-01", None]
    assert "missing_record_id" in merged[0]["dwelling"]["flags"]


def test_explicit_municipality_correction_can_resolve_missing_municipality():
    old = _records()
    _correct(old[0]["dwelling"]["households"][1]["municipality"], "28")
    merged = _merge(old, _records())
    assert _ids(merged) == ["27-0005-01", "28-0005-02"]
    assert "missing_record_id" not in merged[0]["dwelling"]["flags"]


def test_fresh_read_of_missing_municipality_resolves_identity():
    merged = _merge(_records(), _records(second_municipality="28"))
    assert _ids(merged) == ["27-0005-01", "28-0005-02"]
    assert "missing_record_id" not in merged[0]["dwelling"].get("flags", [])


@pytest.mark.parametrize("index", [0, 1])
def test_household_correction_preserves_each_known_municipality(index):
    old = _records(second_municipality="28")
    _correct(old[0]["dwelling"]["households"][index]["household_no"], "3")
    merged = _merge(old, _records(second_municipality="28"))
    assert _ids(merged) == [
        "27-0005-03" if index == 0 else "27-0005-01",
        "28-0005-03" if index == 1 else "28-0005-02",
    ]


def test_duplicate_households_with_complete_shared_identity_still_settle():
    old = _records(second_municipality="27", second_household="1")
    assert _ids(old) == ["27-0005-01", "27-0005-01"]
    _correct(old[0]["dwelling"]["households"][1]["household_no"], "2")
    merged = _merge(old, deepcopy(old))
    assert _ids(merged) == ["27-0005-01", "27-0005-02"]
    assert _duplicates(merged) == [False, False]


def test_mixed_municipality_duplicates_keep_their_ids_and_are_flagged():
    built = _records("28", "1", third_municipality="27")
    assert _ids(built) == ["27-0005-01", "28-0005-01", "27-0005-01"]
    merged = _merge([], built)
    assert _ids(merged) == ["27-0005-01", "28-0005-01", "27-0005-01"]
    assert _duplicates(merged) == [True, False, True]
    assert all(
        "municipality_mismatch" in h["flags"]
        for h in merged[0]["dwelling"]["households"]
    )


def test_household_municipalities_decide_cross_record_duplicates():
    # The mixed dwelling's 27 card and a separate dwelling's sole 27 card, in
    # the same scan, share an ID; the 28 card shares nothing.
    mixed = _records("28", "1")[0]
    other = deepcopy(mixed)
    other_dwelling = other["dwelling"]
    other_dwelling["households"] = [other_dwelling["households"][0]]
    other_dwelling["households"][0]["cards"][0]["page"] = 99

    merged = _merge([], [mixed, other])

    assert [h["record_id"] for r in merged for h in r["dwelling"]["households"]] == [
        "27-0005-01",
        "28-0005-01",
        "27-0005-01",
    ]
    assert _duplicates(merged) == [True, False, True]


@pytest.mark.parametrize("field", ["household_no", "dwelling_no"])
def test_a_correction_that_keeps_an_identity_leaves_the_duplicate_flagged(field):
    built = _records("28", "1", third_municipality="27")
    old = deepcopy(built)
    target = old[0]["dwelling"]["households"][0]
    _correct(target[field], target[field]["value"])

    merged = _merge(old, built)

    # A human correction confirms a reading; it does not settle a duplicate,
    # which the reviewer resolves by relinking or correcting a card.
    assert _ids(merged) == ["27-0005-01", "28-0005-01", "27-0005-01"]
    assert _duplicates(merged) == [True, False, True]


def test_changed_household_number_resolves_both_duplicates():
    built = _records("28", "1", third_municipality="27")
    old = deepcopy(built)
    _correct(old[0]["dwelling"]["households"][0]["household_no"], "2")

    merged = _merge(old, built)

    assert _ids(merged) == ["27-0005-02", "28-0005-01", "27-0005-01"]
    assert _duplicates(merged) == [False, False, False]

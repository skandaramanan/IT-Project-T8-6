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
    return build_dwelling_records(extracted, region="north")[0]


def _ids(records):
    return [h["record_id"] for h in records[0]["dwelling"]["households"]]


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


def test_shared_dwelling_number_correction_does_not_supply_missing_municipality():
    old = _records()
    _correct(old[0]["dwelling"]["dwelling_no"], "6")
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
    assert _ids(old) == [None, None]
    _correct(old[0]["dwelling"]["households"][1]["household_no"], "2")
    merged = _merge(old, deepcopy(old))
    assert _ids(merged) == ["27-0005-01", "27-0005-02"]
    assert "duplicate_record_id" not in merged[0]["dwelling"].get("flags", [])


def test_mixed_municipality_duplicates_stay_null_until_resolved():
    built = _records("28", "1", third_municipality="27")
    assert _ids(built) == [None, "28-0005-01", None]
    merged = _merge([], built)
    assert _ids(merged) == [None, "28-0005-01", None]
    assert "duplicate_record_id" in merged[0]["dwelling"]["flags"]


def test_household_municipalities_prevent_cross_record_duplicate_restore():
    # Global duplicate suppression has nulled the later 27 card in the mixed
    # dwelling and the sole 27 card in a separate dwelling. The mixed dwelling
    # retains each card's municipality, including for the null ID.
    mixed = _records("28", "1")[0]
    dwelling = mixed["dwelling"]
    dwelling["municipality"]["value"] = "28"
    dwelling["households"][0]["municipality"]["value"] = "28"
    dwelling["households"][1]["municipality"]["value"] = "27"
    dwelling["households"][0]["record_id"] = "28-0005-01"
    dwelling["households"][1]["record_id"] = None
    dwelling["flags"] = ["municipality_mismatch", "duplicate_record_id"]
    other = deepcopy(mixed)
    other_dwelling = other["dwelling"]
    other_dwelling["municipality"]["value"] = "27"
    other_dwelling["households"][0]["municipality"]["value"] = "27"
    other_dwelling["households"] = [other_dwelling["households"][0]]
    other_dwelling["households"][0]["record_id"] = None
    other_dwelling["households"][0]["cards"][0]["image"] = "other.pdf"
    other_dwelling["flags"] = ["duplicate_record_id"]

    merged = _merge([], [mixed, other])

    assert [h["record_id"] for r in merged for h in r["dwelling"]["households"]] == [
        "28-0005-01",
        None,
        None,
    ]
    assert all("duplicate_record_id" in r["dwelling"]["flags"] for r in merged)


@pytest.mark.parametrize("field", ["household_no", "dwelling_no"])
def test_only_a_unique_human_identity_correction_wins_a_duplicate(field):
    built = _records("28", "1", third_municipality="27")
    old = deepcopy(built)
    dwelling = old[0]["dwelling"]
    target = dwelling if field == "dwelling_no" else dwelling["households"][0]
    _correct(target[field], target[field]["value"])

    merged = _merge(old, built)

    # A shared dwelling-number correction protects both competing households;
    # a household correction identifies just one. Neither gives the other an ID.
    expected = "27-0005-01" if field == "household_no" else None
    assert _ids(merged) == [expected, "28-0005-01", None]
    assert "duplicate_record_id" in merged[0]["dwelling"]["flags"]


def test_changed_household_number_resolves_both_duplicates():
    built = _records("28", "1", third_municipality="27")
    old = deepcopy(built)
    _correct(old[0]["dwelling"]["households"][0]["household_no"], "2")

    merged = _merge(old, built)

    assert _ids(merged) == ["27-0005-02", "28-0005-01", "27-0005-01"]
    assert "duplicate_record_id" not in merged[0]["dwelling"]["flags"]

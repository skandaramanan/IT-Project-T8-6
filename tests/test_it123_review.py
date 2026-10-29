"""Regressions for the IT-123 review: conservative association and no lost evidence."""

from copy import deepcopy
from pathlib import Path

import pytest
from review_support import legacy

from survey.association.dwelling import similar_numbers
from survey.association.records import build_dwelling_records
from survey.extraction.base import ExtractionResult
from survey.extraction.card_fields import survey_front_label
from survey.extraction.record import build_record, fill_identity, identity_of
from survey.pipeline import (
    MergeRefused,
    RunSummary,
    _keep_front,
    _merge,
    apply_identity_corrections,
    read_verified_coding,
    recover_coding_cards,
    run,
)
from survey.records import Reference, resolve_field, schema_errors
from survey.segmentation.segmenter import CardType, SegmentedCard


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("4", "84", True),
        ("084", "84", True),
        ("123", "129", True),
        ("123", "923", True),
        ("123", "1", False),
        ("123", "456", False),
        (None, "123", False),
        ("", "123", False),
        ("?", "123", False),
        ("487A", "487", False),
        ("487A", "487B", False),
        ("0487A", "487A", True),
    ],
)
def test_positional_pairing_needs_similar_usable_numbers(a, b, expected):
    assert similar_numbers(a, b) is expected


@pytest.mark.parametrize("value", [None, "", "null"])
def test_crop_can_fill_a_gap_without_rereading_a_known_part(value):
    first = {"Municipality": "27", "Number of Dwelling": "5"}
    second = {
        "Municipality": value,
        "Number of Dwelling": None,
        "Number of Household": "2",
    }
    assert identity_of(fill_identity(first, second)) == "27-0005-02"


@pytest.mark.parametrize(
    "fields",
    [
        {"Address": "Hall St"},
        {"Dwelling Number (top-left corner)": "5"},
        {"Structural Material": "Brick"},
        {survey_front_label("Age", 1): "35"},
    ],
)
def test_genuine_front_data_prevents_retyping_even_with_a_plausible_coding_id(fields):
    card = SegmentedCard(CardType.FRONT, Path("front.png"), Path("scan.pdf"), 0)
    reading = ExtractionResult(fields=fields)
    readings = {card: reading}

    class Coding:
        name = "fake"

        def extract(self, _):
            pytest.fail("A genuine front must not be probed or converted")

    assert recover_coding_cards(
        [card], readings, [1], Path("scan.pdf"), Coding(), None, RunSummary()
    ) == [card]
    assert readings == {card: reading}


def test_front_flag_swap_keeps_current_coding_flags():
    old = {
        "dwelling": {
            "address": {"value": "Hall St", "status": "ok"},
            "families_in_dwelling": {"value": "1", "status": "ok"},
            "handwritten": {},
            "cards": [{"image": "s.pdf", "page": 1, "role": "survey-front"}],
            "households": [{"persons": [{"name": "old"}]}],
            "flags": ["fronts_disagree", "duplicate_record_id"],
        }
    }
    new = deepcopy(old)
    new["dwelling"].update(
        address={"value": None, "status": "omitted"},
        families_in_dwelling={"value": None, "status": "omitted"},
        flags=["missing_dwelling_no", "identity_reread"],
    )
    _keep_front(old, new)
    assert new["dwelling"]["flags"] == ["fronts_disagree", "identity_reread"]
    assert new["dwelling"]["address"] == old["dwelling"]["address"]


def test_zero_record_region_is_reported_without_an_empty_dataset_file(tmp_path):
    scans = tmp_path / "scans"
    scans.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    empty = output / "empty.jsonl"
    empty.touch()
    summary = run(scans, region="empty", extractor=None, out_dir=output)
    assert summary.records == 0
    assert not empty.exists()


def test_new_schema_requires_per_household_municipality_but_reads_legacy():
    record = build_record(
        {"Municipality": "27", "Number of Dwelling": "5", "Number of Household": "1"},
        region="north",
    )
    assert not schema_errors(record)
    published = legacy(record)
    del record["dwelling"]["households"][0]["municipality"]
    assert schema_errors(record)
    del published["dwelling"]["households"][0]["municipality"]
    assert schema_errors(published)
    published["schema_version"] = "0.5.0"
    assert not schema_errors(published)


def test_household_municipality_is_reviewable_on_its_own_coding_card():
    record = build_record(
        {"Municipality": "28", "Number of Dwelling": "5", "Number of Household": "1"},
        region="north",
        image="s.pdf",
        page=3,
    )
    ref = Reference("north", "s.pdf", 3, "/dwelling/households/0/municipality")
    assert resolve_field([record], ref).field["value"] == "28"


def test_verified_coding_decisions_are_explicit_and_region_scoped(tmp_path):
    path = tmp_path / "verified.json"
    path.write_text(
        '[{"region":"north","pdf":"s.pdf","page":3},'
        '{"region":"south","pdf":"s.pdf","page":4}]'
    )
    assert read_verified_coding(path, "north") == {("s.pdf", 3)}
    path.write_text('[{"region":"north","pdf":"s.pdf","page":true}]')
    with pytest.raises(MergeRefused):
        read_verified_coding(path, "north")


def test_verified_scan_decision_precedes_model_readings(monkeypatch):
    from types import SimpleNamespace

    from survey import pipeline

    front = SegmentedCard(CardType.FRONT, Path("p.png"), Path("s.pdf"), 0)
    monkeypatch.setattr(pipeline, "PdfReader", lambda _: SimpleNamespace(pages=[None]))
    monkeypatch.setattr(pipeline, "extract_image", lambda *args: None)
    monkeypatch.setattr(pipeline, "segment_pages", lambda *args, **kwargs: [front])

    class Coding:
        name = "fake"

        def extract(self, _):
            return ExtractionResult(fields={"Municipality": "27"})

    def build(extracted, **kwargs):
        assert extracted[0][0].card_type is CardType.NUMERIC_CODING
        return [], [], []

    monkeypatch.setattr(pipeline, "build_dwelling_records", build)
    assert (
        pipeline._run_pdf(
            Path("s.pdf"),
            "north",
            Coding(),
            None,
            None,
            None,
            None,
            RunSummary(),
            verified_coding={("s.pdf", 1)},
        )
        == []
    )


def test_protected_front_and_coding_numbers_are_applied_before_association():
    front = SegmentedCard(CardType.FRONT, Path("front.png"), Path("s.pdf"), 0)
    coding = SegmentedCard(
        CardType.NUMERIC_CODING, Path("coding.png"), Path("s.pdf"), 2
    )
    readings = {
        front: ExtractionResult(fields={"Dwelling Number (top-left corner)": "303"}),
        coding: ExtractionResult(
            fields={
                "Municipality": "06",
                "Number of Dwelling": "303",
                "Number of Household": "1",
            }
        ),
    }

    def locate(card):
        return "s.pdf", card.page_index + 1

    previous = build_dwelling_records(
        list(readings.items()), region="north", locate=locate
    )[0]
    dwelling = previous[0]["dwelling"]
    card = dwelling["households"][0]
    for field in (card["dwelling_no"], dwelling["handwritten"]["dwelling_no"]):
        field.update(origin="corrected", original_value="999")
    raw = {
        front: ExtractionResult(fields={"Dwelling Number (top-left corner)": "999"}),
        coding: ExtractionResult(
            fields={
                "Municipality": "06",
                "Number of Dwelling": "308",
                "Number of Household": "1",
            }
        ),
    }
    apply_identity_corrections(raw, locate, previous)
    rebuilt = build_dwelling_records(list(raw.items()), region="north", locate=locate)[
        0
    ]
    merged = _merge(previous, rebuilt)
    assert len(merged) == 1
    assert (
        merged[0]["dwelling"]["handwritten"]["dwelling_no"]
        == dwelling["handwritten"]["dwelling_no"]
    )
    assert merged[0]["dwelling"]["households"][0]["record_id"] == "06-0303-01"


def test_conflicting_human_identity_corrections_keep_their_id_and_are_flagged():
    records = [
        build_record(
            {
                "Municipality": "27",
                "Number of Dwelling": "5",
                "Number of Household": "2",
            },
            region="north",
            image="s.pdf",
            page=p,
        )
        for p in (1, 3)
    ]
    for record in records:
        household = record["dwelling"]["households"][0]
        household["household_no"].update(origin="corrected", original_value="1")
    merged = _merge([], records)
    # 0.7.0: a duplicate keeps its derived ID and is flagged on every peer card.
    cards = [r["dwelling"]["households"][0] for r in merged]
    assert all(c["record_id"] == "27-0005-02" for c in cards)
    assert all("duplicate_record_id" in c["flags"] for c in cards)

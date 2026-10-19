"""Keep the scan-verified additions local, auditable and deterministic."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from survey.association.notes import ReverseSlot, attach_notes, read_notes
from survey.association.records import build_dwelling_records
from survey.extraction.base import ExtractionResult
from survey.extraction.card_fields import survey_front_label
from survey.extraction.record import build_record
from survey.records import schema_errors
from survey.segmentation.segmenter import CardType, SegmentedCard

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "additions", ROOT / "scripts/extract_216436_additions.py"
)
additions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(additions)
NUMBER = "Dwelling Number (top-left corner)"


def decision(kind, page, label, old, new):
    return {
        "kind": kind,
        "page": page,
        "field": label,
        "original_value": old,
        "value": new,
    }


def test_changes_are_scoped_and_raw_readings_stay_immutable():
    original = ExtractionResult(
        fields={NUMBER: "01120", "Address": "same"}, raw_text="original"
    )
    index = additions.correction_index(
        {"corrections": [decision("front", 515, NUMBER, "01120", "177")]}
    )
    fixed = additions.corrected_reading("front", 515, original, index)
    assert fixed.fields == {NUMBER: "177", "Address": "same"}
    assert original.fields[NUMBER] == "01120"
    assert fixed.raw_text == original.raw_text == "original"
    assert (
        additions.corrected_reading("front", 519, original, index).fields
        == original.fields
    )
    assert (
        additions.corrected_reading("coding", 515, original, index).fields
        == original.fields
    )


def test_an_unexpected_cache_value_requires_another_source_check():
    index = additions.correction_index(
        {
            "corrections": [
                decision("coding", 551, "Number of Dwelling", "209.522", "209")
            ]
        }
    )
    with pytest.raises(ValueError, match="machine reading changed"):
        additions.corrected_reading(
            "coding", 551, ExtractionResult(fields={"Number of Dwelling": "522"}), index
        )


@pytest.mark.parametrize(
    "items",
    [
        [decision("coding", 570, "Number of Dwelling", None, "1")],
        [decision("front", 515, "Address", "before", "after")],
        [decision("front", 515, NUMBER, "old", "177")] * 2,
    ],
)
def test_uninspected_fields_pages_and_repeated_decisions_refuse(items):
    with pytest.raises(ValueError, match="invalid or repeated"):
        additions.correction_index({"corrections": items})


def test_continuation_keeps_both_grids_notes_and_the_selected_original_value():
    manifest = {
        "corrections": [
            decision("front", page, NUMBER, old, "191")
            for page, old in [(527, "488"), (529, "483")]
        ]
    }
    index = additions.correction_index(manifest)
    originals = {
        ("front", 527): ExtractionResult(
            fields={
                NUMBER: "488",
                "Address": "1145 High Street",
                survey_front_label("Relationship", 1): "Head",
            }
        ),
        ("front", 529): ExtractionResult(
            fields={NUMBER: "483", survey_front_label("Relationship", 1): "Daughter"}
        ),
        ("coding", 531): ExtractionResult(
            fields={
                "Municipality": "14",
                "Number of Dwelling": "191",
                "Number of Household": "1",
            }
        ),
    }
    cards, readings = [], {}
    for (kind, page), original in originals.items():
        card = SegmentedCard(
            CardType.FRONT if kind == "front" else CardType.NUMERIC_CODING,
            Path(f"p{page}.png"),
            Path(additions.PDF_NAME),
            page - 1,
        )
        cards.append(card)
        readings[card] = additions.corrected_reading(kind, page, original, index)
    locate = lambda card: (additions.PDF_NAME, card.page_index + 1)
    records, _, _ = build_dwelling_records(
        list(readings.items()), region="216436", batch=additions.PDF_NAME, locate=locate
    )
    assert len(records) == 1
    record = records[0]
    additions.annotate_corrections(record, originals, index)
    assert [
        p["relationship"]["value"]
        for p in record["dwelling"]["households"][0]["persons"]
    ] == ["Head", "Daughter"]
    number = record["dwelling"]["handwritten"]["dwelling_no"]
    assert (number["value"], number["original_value"], number["origin"]) == (
        "191",
        "488",
        "corrected",
    )
    slots = [
        ReverseSlot(card, Path("back.png"), card.page_index + 2)
        for card in cards
        if card.card_type is CardType.FRONT
    ]
    notes = read_notes(
        slots, lambda _: ExtractionResult(fields={"Interview Notes": "note"})
    )
    assert attach_notes(records, notes, locate) == []
    assert [n["page"] for n in record["dwelling"]["notes"]] == [528, 530]
    assert not schema_errors(record)


def test_coding_corrections_keep_identity_aliases_and_missing_machine_values():
    items = [
        decision("coding", 585, "Municipality", "21", "14"),
        decision("coding", 585, "Type of Family", None, "1"),
    ]
    index = additions.correction_index({"corrections": items})
    original = ExtractionResult(
        fields={
            "Municipality": "21",
            "Number of Dwelling": "233",
            "Number of Household": "1",
            "Type_of_Family": "",
        },
        raw_text="saved raw",
    )
    fixed = additions.corrected_reading("coding", 585, original, index)
    card = SegmentedCard(
        CardType.NUMERIC_CODING, Path("coding.png"), Path(additions.PDF_NAME), 584
    )
    records, _, _ = build_dwelling_records(
        [(card, fixed)],
        region="216436",
        locate=lambda _: (additions.PDF_NAME, 585),
        fronts_read=False,
    )
    record = records[0]
    additions.annotate_corrections(record, {("coding", 585): original}, index)
    dwelling = record["dwelling"]
    assert dwelling["households"][0]["record_id"] == "14-0233-01"
    for field in [dwelling["municipality"], dwelling["households"][0]["municipality"]]:
        assert (field["value"], field["original_value"], field["origin"]) == (
            "14",
            "21",
            "corrected",
        )
    family = dwelling["households"][0]["coding"]["type_of_family"]
    assert (
        family["value"],
        family["status"],
        family["original_value"],
        family["origin"],
    ) == ("1", "ok", None, "corrected")
    assert original.fields.get("Type of Family") is None
    assert not schema_errors(record)


@pytest.mark.skipif(
    not additions.PDF.exists(), reason="needs the local replacement scan and raw caches"
)
def test_complete_local_rebuild_keeps_all_sources_and_resolves_verified_gaps(
    tmp_path, monkeypatch
):
    # The production helper intentionally refuses main/IT-125 checkouts. Replay
    # real local inputs only in scratch space, never rewrite active results.
    baseline = subprocess.check_output(
        [
            "git",
            "show",
            "556913316ae04aeaca0b5332198975bc176d7bc1:results/216436.jsonl",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    # This helper builds the standalone Gemini additions stage. Its expected
    # output must not follow the active dataset as IT-125 pairs/rescores it.
    expected = subprocess.check_output(
        [
            "git",
            "show",
            "5b45a21aba1283eb41ceaeff130837234c2c35b0:results/216436.jsonl",
        ],
        cwd=ROOT,
    )
    published = ROOT / "results/216436.jsonl"
    published_before = published.read_bytes()
    original_check_output = subprocess.check_output

    def pinned_baseline(command, **kwargs):
        if command == [
            "git",
            "show",
            "556913316ae04aeaca0b5332198975bc176d7bc1:results/216436.jsonl",
        ]:
            return "\n".join(baseline) + "\n"
        return original_check_output(command, **kwargs)

    sandbox = tmp_path / "offline-replay"
    for relative in ("docs/runs", "results", "data/216436-additions"):
        (sandbox / relative).mkdir(parents=True, exist_ok=True)
    for name in ("216436-source-corrections.json", "216436-gemini-additions.json"):
        shutil.copy2(ROOT / "docs/runs" / name, sandbox / "docs/runs" / name)
    (sandbox / "results/216436.jsonl").write_text("\n".join(baseline) + "\n")
    pdf = sandbox / "data/Wilfred_Prest_Survey_Data/216436" / additions.PDF_NAME
    pdf.parent.mkdir(parents=True)
    shutil.copy2(additions.PDF, pdf)
    for kind, page in [*additions.jobs(), ("identity", 551)]:
        source = additions.cache(kind, page)
        destination = sandbox / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    monkeypatch.setattr(additions, "ROOT", sandbox)
    monkeypatch.setattr(additions, "RUN", sandbox / "data/216436-additions")
    monkeypatch.setattr(additions, "PDF", pdf)
    monkeypatch.setattr(additions, "isolated", lambda: None)
    monkeypatch.setattr(additions.subprocess, "check_output", pinned_baseline)
    raw_paths = sorted((sandbox / "data/runs/216436").rglob("*.json"))
    raw_before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in raw_paths}
    output = sandbox / "results/216436.jsonl"
    additions.build()
    assert output.read_bytes() == expected
    report_path = sandbox / "docs/runs/216436-gemini-additions.json"
    first_report = report_path.read_bytes()
    additions.build()
    assert output.read_bytes() == expected
    assert report_path.read_bytes() == first_report
    assert published.read_bytes() == published_before
    assert all(
        hashlib.sha256(p.read_bytes()).hexdigest() == digest
        for p, digest in raw_before.items()
    )
    assert set(baseline) <= set(output.read_text().splitlines())
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 146
    report = json.loads(
        (sandbox / "docs/runs/216436-gemini-additions.json").read_text()
    )
    assert report["unattached_front_pages"] == report["new_unplaced_coding_pages"] == []
    assert report["null_record_id_pages"] == report["omitted_coding_fields"] == []
    assert report["source_corrections"] == 19
    by_page = {
        h["cards"][0]["page"]: h for r in records for h in r["dwelling"]["households"]
    }
    assert by_page[551]["record_id"] == "14-0209-01"
    assert (
        len(by_page[531]["persons"]) == 13
    )  # 12 resident columns plus "Another expected"
    assert all(
        h["cards"][0]["page"] != 570
        for r in records
        for h in r["dwelling"]["households"]
    )


def test_existing_review_and_manual_correction_payloads_cannot_be_overwritten():
    old = build_record(
        {"Municipality": "14", "Number of Dwelling": "209", "Number of Household": "1"},
        region="216436",
        image=additions.PDF_NAME,
        page=551,
    )
    old["dwelling"]["dwelling_no"].update(
        origin="corrected", original_value="209522", review={"state": "accepted"}
    )
    additions.protect_published_corrections([old], [deepcopy(old)])
    changed = deepcopy(old)
    changed["dwelling"]["dwelling_no"].pop("review")
    with pytest.raises(ValueError, match="overwrite a published correction or review"):
        additions.protect_published_corrections([old], [changed])
    with pytest.raises(ValueError, match="overwrite a published correction or review"):
        additions.protect_published_corrections([old], [])


def test_rebuild_refuses_main_before_changing_active_results(monkeypatch):
    output = ROOT / "results/216436.jsonl"
    before = output.read_bytes()
    monkeypatch.setattr(
        additions.subprocess, "check_output", lambda *args, **kwargs: "main\n"
    )
    monkeypatch.chdir(ROOT)
    with pytest.raises(RuntimeError, match="not the isolated additions branch"):
        additions.build()
    assert output.read_bytes() == before

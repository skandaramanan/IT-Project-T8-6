import json
import runpy
from pathlib import Path

import pytest
from review_support import git, setup_review, synthetic_record

from survey.records import Reference, read_records, resolve_field

SAMPLE = runpy.run_path(str(Path(__file__).parents[1] / "scripts/review_sample.py"))


def test_sample_preserves_originals_and_uses_only_local_remote(tmp_path):
    _, settings = setup_review(tmp_path / "source")
    source = settings.data_checkout / "results/demo.jsonl"
    pdf = settings.scan_root / "demo/synthetic.pdf"
    before = source.read_bytes(), pdf.read_bytes()
    destination = tmp_path / "local test with spaces"
    checkout, flags = SAMPLE["prepare_sample"](
        source, settings.scan_root, destination, ["Weekly Rent", "Garden"]
    )
    assert (source.read_bytes(), pdf.read_bytes()) == before
    assert git(checkout, "remote", "get-url", "origin") == str(
        destination / "remote.git"
    )
    assert git(checkout, "status", "--porcelain") == ""
    records, _ = read_records(checkout / "results/demo.jsonl", "demo")
    entries = [json.loads(line) for line in flags.read_text().splitlines()]
    assert (
        len(entries) == 4
    )  # every card owns its building fields, including explicit omissions
    for entry in entries:
        resolve_field(records, Reference(**entry))
    assert len(records[0]["dwelling"]["households"]) == 2


def test_selecting_second_card_retains_indexes_and_excludes_shared_fields():
    records, flags, count = SAMPLE["select_sample"](
        [synthetic_record()], "demo", ["Weekly Rent", "Garden"], 1, pages=[2]
    )
    assert count == 1 and len(flags) == 1
    assert flags[0]["field_path"] == "/dwelling/households/1/coding/weekly_rent"
    assert (
        resolve_field(records, Reference(**flags[0])).household["record_id"]
        == "27-0006-02"
    )
    assert len(records[0]["dwelling"]["households"]) == 2


def test_existing_destination_is_never_replaced(tmp_path):
    _, settings = setup_review(tmp_path / "source")
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("existing work")
    with pytest.raises(ValueError, match="existing work"):
        SAMPLE["prepare_sample"](
            settings.data_checkout / "results/demo.jsonl",
            settings.scan_root,
            destination,
            ["Weekly Rent"],
        )
    assert marker.read_text() == "existing work"

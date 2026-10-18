"""FR-11 against a labelled example batch: "fields below threshold appear in
the queue; fields above it do not." ``expected.json`` labels every field by
hand, so a change to the rule shows up here as a failure."""

import json
from pathlib import Path

from survey.records import card_index, current_fields, read_dataset, resolve_field
from survey.review.flags import build_flags
from survey.review.queue import load_queue

FIXTURES = Path(__file__).parent / "fixtures" / "review_flags"
# The shared reader also checks each record against the schema.
REGIONS = {
    region: records
    for region, (records, _) in read_dataset(sorted(FIXTURES.glob("*.jsonl"))).items()
}
RECORDS = [r for records in REGIONS.values() for r in records]
LABELS = json.loads((FIXTURES / "expected.json").read_text())


def owner(record, path):
    """The household a field belongs to; dwelling-level fields, the first."""
    households = record["dwelling"]["households"]
    return households[path[2] if path[1] == "households" else 0]


def test_queue_matches_the_labels_exactly():
    cards = {
        (r["region"], c["image"], c["page"]): h["record_id"]
        for r in RECORDS
        for h in r["dwelling"]["households"]
        for c in h["cards"]
    }
    queue, skipped = build_flags(REGIONS)
    assert skipped == []
    queued = set()
    for flag in queue:
        parts = flag["field_path"][1:].split("/")
        path = tuple(int(p) if p.isdigit() else p for p in parts)
        queued.add((cards[flag["region"], flag["pdf"], flag["page"]], path))
    flagged = {(x["record_id"], tuple(x["path"])) for x in LABELS if x["flagged"]}
    assert queued - flagged == set(), "queued but labelled clear"
    assert flagged - queued == set(), "labelled flagged but not queued"


def test_every_field_is_labelled_once():
    fields = {
        (owner(r, p)["record_id"], p) for r in RECORDS for p, _ in current_fields(r)
    }
    labels = [(x["record_id"], tuple(x["path"])) for x in LABELS]
    assert sorted(labels) == sorted(fields)


def test_batch_covers_every_status_and_score_band():
    seen = [f for r in RECORDS for _, f in current_fields(r)]
    statuses = {"ok", "no_data", "illegible", "damaged", "omitted"}
    assert {f["status"] for f in seen} == statuses
    assert any(f.get("origin") == "corrected" for f in seen)
    scores = {f["confidence"] for f in seen if f["status"] == "ok"}
    # none, zero, D016's classes, just under and above the cutoff
    assert {None, 0.0, 0.14, 0.45, 0.74, 0.75, 0.91, 0.969, 0.97, 1.0} <= scores


def test_every_flag_opens_in_the_review_tool(tmp_path):
    queue, _ = build_flags(REGIONS)
    path = tmp_path / "flags.jsonl"
    path.write_text("".join(json.dumps(flag) + "\n" for flag in queue))
    references, diagnostics = load_queue(path)
    assert diagnostics == []
    assert len(references) == len(queue)
    for ref in references:
        records = REGIONS[ref.region]
        resolve_field(records, ref, card_index(records))  # raises if it can't

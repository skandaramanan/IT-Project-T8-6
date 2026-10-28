"""Independent regressions for identity changes across persisted extraction data."""

from copy import deepcopy
from dataclasses import replace

import pytest
from review_support import (
    decide,
    per_card,
    refs,
    setup_review,
    synthetic_record,
    write_record,
)

from survey.pipeline import _merge
from survey.records import RecordStore, ReviewError
from survey.review.relinking import finish_records, refresh_identities
from survey.review.service import ReviewService


def install(service, record):
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()


def restart(service, settings, ref):
    return ReviewService(
        RecordStore(settings.data_checkout / "results"), [ref], [], service.scans
    )


@pytest.mark.parametrize(
    "pointer,value",
    [
        ("/dwelling/dwelling_no", "7"),
        ("/dwelling/households/1/household_no", "3"),
        ("/dwelling/municipality", "29"),
    ],
)
def test_legacy_identity_edits_retain_other_card_municipality(tmp_path, pointer, value):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["schema_version"] = "0.5.0"
    for household in record["dwelling"]["households"]:
        household.pop("municipality")
    record["dwelling"]["households"][1]["record_id"] = "28-0006-02"
    record["dwelling"]["flags"] = ["municipality_mismatch"]
    install(service, record)
    ref = replace(refs()[3], page=2 if "/1/" in pointer else 1, field_path=pointer)
    service.replace_queue([ref], [])
    assert "municipality_mismatch" in {
        i["code"] for i in service.item(ref.item_id)["review_issues"]
    }
    decide(service, ref, value=value)
    second = service.store.regions["demo"][0][0]["dwelling"]["households"][1]
    assert second["record_id"].startswith("28-")


def test_legacy_ambiguous_missing_municipality_cannot_be_guessed(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["schema_version"] = "0.5.0"
    record["dwelling"]["households"][1].pop("municipality")
    record["dwelling"]["households"][1]["record_id"] = None
    record["dwelling"]["flags"] = ["municipality_mismatch"]
    install(service, record)
    ref = replace(refs()[3], field_path="/dwelling/dwelling_no")
    service.replace_queue([ref], [])
    before = (service.store.directory / "demo.jsonl").read_bytes()
    with pytest.raises(ReviewError, match="lost its municipality"):
        decide(service, ref, value="7")
    assert (service.store.directory / "demo.jsonl").read_bytes() == before


def test_missing_legacy_id_can_inherit_unambiguous_shared_reading(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["schema_version"] = "0.5.0"
    record["dwelling"]["households"][1].pop("municipality")
    record["dwelling"]["households"][1]["record_id"] = None
    install(service, record)
    decide(service, refs()[3], value="28")
    assert (
        service.store.regions["demo"][0][0]["dwelling"]["households"][1]["record_id"]
        == "28-0006-02"
    )


# A rerun merges onto per-card 0.7.0 results only (the pipeline's rule).
@pytest.mark.parametrize("shape", ["0.7.0"], indirect=True)
def test_alias_evidence_and_undo_survive_extraction_rerun(tmp_path, shape):
    service, settings = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["households"][0]["municipality"].update(
        value="26", confidence=0.4
    )
    refresh_identities([record])  # the card's own reading derives its ID
    install(service, record)
    # Agreeing with card 2 keeps the group whole, so the rebuild still merges.
    decision = decide(service, refs()[3], value="27")
    alias_before = deepcopy(
        service.store.regions["demo"][0][0]["dwelling"]["households"][0]["municipality"]
    )
    [merged] = _merge(deepcopy(service.store.regions["demo"][0]), [synthetic_record()])
    assert merged["dwelling"]["households"][0]["municipality"] == alias_before
    install(service, merged)
    service = restart(service, settings, refs()[3])
    service.undo_latest(
        decision["decision"]["id"],
        "Audit",
        service.item(refs()[3].item_id)["version"],
        "undo",
    )
    assert (
        service.store.regions["demo"][0][0]["dwelling"]["households"][0][
            "municipality"
        ]["value"]
        == "26"
    )


@pytest.mark.parametrize("shape", ["0.7.0"], indirect=True)
@pytest.mark.parametrize("change", ["insert", "remove", "reorder"])
def test_identity_undo_refuses_changed_note_topology_after_rerun(
    tmp_path, change, shape
):
    service, settings = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["households"].pop()
    record["dwelling"]["notes"][0]["household_id"] = "27-0006-01"
    finish_records([record])  # links the note to its card
    install(service, record)
    ref = replace(refs()[3], field_path=per_card("/dwelling/dwelling_no"))
    service.replace_queue([ref], [])
    decision = decide(service, ref, value="7")
    rebuilt = deepcopy(record)
    rebuilt["dwelling"]["cards"] += [
        {"role": "survey-front", "image": "synthetic.pdf", "page": 5},
        {"role": "survey-back", "image": "synthetic.pdf", "page": 6},
    ]
    new_note = deepcopy(rebuilt["dwelling"]["notes"][0])
    new_note.update(page=6, front_page=5)
    if change == "insert":
        rebuilt["dwelling"]["notes"].insert(0, new_note)
    elif change == "remove":
        rebuilt["dwelling"]["notes"] = []
    else:
        # Two original notes change position without changing their ownership.
        old = deepcopy(service.store.regions["demo"][0][0])
        old["dwelling"]["cards"] = deepcopy(rebuilt["dwelling"]["cards"])
        extra = deepcopy(old["dwelling"]["notes"][0])
        extra.update(page=6, front_page=5)
        old["dwelling"]["notes"].append(extra)
        install(service, old)
        decision = decide(service, ref, value="8", request_id="second")
        rebuilt = deepcopy(service.store.regions["demo"][0][0])
        rebuilt["dwelling"]["notes"].reverse()
    [merged] = _merge(deepcopy(service.store.regions["demo"][0]), [rebuilt])
    install(service, merged)
    service = restart(service, settings, ref)
    undo = (
        decision["decision"]["id"],
        "Audit",
        service.item(ref.item_id)["version"],
        "undo",
    )
    if change == "reorder":
        # 0.7.0 notes are owned by card ID, so a pure reorder is not a change.
        service.undo_latest(*undo)
        notes = service.store.regions["demo"][0][0]["dwelling"]["notes"]
        assert len({n["household_card_id"] for n in notes}) == 1
        return
    before = (service.store.directory / "demo.jsonl").read_bytes()
    with pytest.raises(ReviewError, match="evidence association changed"):
        service.undo_latest(*undo)
    assert (service.store.directory / "demo.jsonl").read_bytes() == before


def test_single_household_identity_repair_links_null_notes_and_undo_restores_null(
    tmp_path,
):
    service, settings = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["households"].pop()
    record["dwelling"]["dwelling_no"].update(value=None, status="illegible")
    record["dwelling"]["households"][0]["record_id"] = None
    install(service, record)
    ref = replace(refs()[3], field_path="/dwelling/dwelling_no")
    service.replace_queue([ref], [])
    decision = decide(service, ref, value="7")
    assert (
        service.store.regions["demo"][0][0]["dwelling"]["notes"][0]["household_id"]
        == "27-0007-01"
    )
    service = restart(service, settings, ref)
    service.undo_latest(
        decision["decision"]["id"],
        "Audit",
        service.item(ref.item_id)["version"],
        "undo",
    )
    assert (
        service.store.regions["demo"][0][0]["dwelling"]["notes"][0]["household_id"]
        is None
    )
    assert (
        service.store.regions["demo"][0][0]["dwelling"]["households"][0]["record_id"]
        is None
    )

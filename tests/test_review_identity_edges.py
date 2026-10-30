"""Adversarial checks for identity side effects across related fields."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from review_support import decide, refs, setup_review, synthetic_pdf, write_record

from survey.records import ReviewError


@pytest.mark.usefixtures("published")
@pytest.mark.parametrize("edit_shared", [True, False])
def test_municipality_correction_cannot_bypass_negated_mirror(tmp_path, edit_shared):
    service, _ = setup_review(tmp_path)
    shared = refs()[3]
    alias = replace(shared, field_path="/dwelling/households/0/municipality")
    record = deepcopy(service.store.regions["demo"][0][0])
    mirror = (
        record["dwelling"]["households"][0]["municipality"]
        if edit_shared
        else record["dwelling"]["municipality"]
    )
    mirror["negated"] = True
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    service.replace_queue([shared, alias], [])
    selected, protected = (shared, alias) if edit_shared else (alias, shared)
    assert service.item(protected.item_id)["allowed_actions"] == ["accept"]
    before = (service.store.directory / "demo.jsonl").read_bytes()
    with pytest.raises(ReviewError):
        decide(service, selected, value="28")
    assert (service.store.directory / "demo.jsonl").read_bytes() == before


@pytest.mark.usefixtures("published")
@pytest.mark.parametrize("legacy_event", [False, True])
def test_undo_can_restore_preexisting_duplicate_identity_after_restart(
    tmp_path, legacy_event
):
    from survey.records import RecordStore
    from survey.review.service import ReviewService

    service, settings = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    first = record["dwelling"]["households"][0]
    first["household_no"]["value"] = "2"
    first["record_id"] = "27-0006-02"
    record["dwelling"]["flags"] = ["duplicate_record_id"]
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    ref = replace(refs()[3], field_path="/dwelling/households/0/household_no")
    service.replace_queue([ref], [])
    correction = decide(service, ref, value="3")
    if legacy_event:
        changed = deepcopy(service.store.regions["demo"][0][0])
        history = changed["dwelling"]["households"][0]["household_no"]["review"][
            "history"
        ]
        history[0].pop("identity_conflicts")
        write_record(service.store.directory / "demo.jsonl", changed)
    service = ReviewService(
        RecordStore(settings.data_checkout / "results"), [ref], [], service.scans
    )
    if legacy_event:
        with pytest.raises(ReviewError, match="already belongs"):
            service.undo_latest(
                correction["decision"]["id"],
                "Reviewer",
                service.item(ref.item_id)["version"],
                "conservative-legacy-undo",
            )
        return
    service.undo_latest(
        correction["decision"]["id"],
        "Reviewer",
        service.item(ref.item_id)["version"],
        "undo-duplicate-repair",
    )
    restored = service.store.regions["demo"][0][0]
    assert restored["dwelling"]["households"][0]["household_no"]["value"] == "2"
    assert [
        household["record_id"] for household in restored["dwelling"]["households"]
    ] == [
        "27-0006-02",
        "27-0006-02",
    ]


@pytest.mark.usefixtures("published")
def test_duplicate_repair_undo_rejects_later_replacement_collision_owner(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    households = record["dwelling"]["households"]
    households[0]["household_no"]["value"] = "2"
    households[0]["record_id"] = "27-0006-02"
    third = deepcopy(households[1])
    third["household_no"]["value"] = "4"
    third["record_id"] = "27-0006-04"
    third["cards"][0].update(image="third.pdf", page=1)
    synthetic_pdf(tmp_path / "scans" / "demo" / "third.pdf")
    households.append(third)
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    first = replace(refs()[3], field_path="/dwelling/households/0/household_no")
    second = replace(first, page=2, field_path="/dwelling/households/1/household_no")
    third_ref = replace(
        first, pdf="third.pdf", page=1, field_path="/dwelling/households/2/household_no"
    )
    service.replace_queue([first, second, third_ref], [])
    repaired = decide(service, first, value="3")
    decide(service, second, value="5", request_id="free-original-owner")
    decide(service, third_ref, value="2", request_id="replacement-owner")
    before = (service.store.directory / "demo.jsonl").read_bytes()
    with pytest.raises(ReviewError, match="already belongs"):
        service.undo_latest(
            repaired["decision"]["id"],
            "Reviewer",
            service.item(first.item_id)["version"],
            "undo-with-new-owner",
        )
    assert (service.store.directory / "demo.jsonl").read_bytes() == before


@pytest.mark.usefixtures("published")
def test_collision_guard_includes_other_records_stored_ids(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    other = deepcopy(record)
    other["dwelling"]["dwelling_no"]["value"] = "8"
    for index, household in enumerate(other["dwelling"]["households"]):
        household["cards"][0]["image"] = "other.pdf"
        household["record_id"] = f"27-0008-0{index + 1}"
    # A stale stored ID is schema-valid and must not be silently reused.
    other["dwelling"]["households"][0]["record_id"] = "27-0007-01"
    path = service.store.directory / "demo.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in [record, other]))
    service.store.reload()
    ref = replace(refs()[3], field_path="/dwelling/dwelling_no")
    service.replace_queue([ref], [])
    before = path.read_bytes()
    with pytest.raises(ReviewError, match="already belongs"):
        decide(service, ref, value="7")
    assert path.read_bytes() == before

from copy import deepcopy

import pytest
from review_support import decide, refs, setup_review, synthetic_record, write_record

from survey.extraction.record import SCHEMA_VERSION
from survey.pipeline import MergeRefused, _corrected_fields, _merge
from survey.records import validate_records


@pytest.mark.parametrize("action", ["accept", "correct", "no_data", "illegible"])
def test_active_review_values_and_history_survive_rerun(tmp_path, action):
    service, _ = setup_review(tmp_path)
    decision = decide(service, action=action)
    old = service.store.regions["demo"][0][0]
    rebuilt = synthetic_record()
    rebuilt["dwelling"]["households"][1]["coding"]["weekly_rent"]["value"] = "99"
    [merged] = _merge([old], [rebuilt])
    assert (
        merged["dwelling"]["households"][1]["coding"]["weekly_rent"]
        == decision["item"]["field"]
    )
    assert len(list(_corrected_fields(merged))) == 1


def test_pending_undo_history_survives_but_new_reading_can_change(tmp_path):
    service, _ = setup_review(tmp_path)
    decision = decide(service)
    undone = service.undo_latest(
        decision["decision"]["id"], "Reviewer", decision["item"]["version"], "undo"
    )
    old = service.store.regions["demo"][0][0]
    rebuilt = synthetic_record()
    rebuilt["schema_version"] = "0.2.0"
    rebuilt["dwelling"]["households"][1]["coding"]["weekly_rent"]["value"] = "25"
    [merged] = _merge([old], [rebuilt])
    field = merged["dwelling"]["households"][1]["coding"]["weekly_rent"]
    assert (
        field["value"] == "25" and field["review"] == undone["item"]["field"]["review"]
    )
    assert merged["schema_version"] == SCHEMA_VERSION
    validate_records([merged], "demo")
    write_record(service.store.directory / "demo.jsonl", merged)
    service.store.reload()
    service.reindex_history()
    accepted = decide(service, action="accept", request_id="after-rerun")
    assert accepted["decision"]["before"]["value"] == "25"
    restored = service.undo_latest(
        accepted["decision"]["id"],
        "Reviewer",
        accepted["item"]["version"],
        "undo-after-rerun",
    )
    assert restored["item"]["field"]["value"] == "25"
    assert restored["item"]["review_state"] == "pending"


def test_any_retained_history_refuses_regrouping_and_partial_rebuild_keeps_whole(
    tmp_path,
):
    service, _ = setup_review(tmp_path)
    decision = decide(service)
    service.undo_latest(
        decision["decision"]["id"], "Reviewer", decision["item"]["version"], "undo"
    )
    old = service.store.regions["demo"][0][0]
    reordered = synthetic_record()
    reordered["dwelling"]["households"].reverse()
    with pytest.raises(MergeRefused, match="regrouped"):
        _merge([old], [reordered])
    partial = synthetic_record()
    partial["dwelling"]["households"].pop()
    assert _merge([old], [partial]) == [old]


def test_acceptance_of_identity_preserves_display_identity(tmp_path):
    service, _ = setup_review(tmp_path)
    decide(service, refs()[3], action="accept")
    old = service.store.regions["demo"][0][0]
    rebuilt = synthetic_record()
    rebuilt["dwelling"]["municipality"]["value"] = "29"
    [merged] = _merge([old], [rebuilt])
    assert all(
        h["record_id"].startswith("27-") for h in merged["dwelling"]["households"]
    )


def test_undo_to_legacy_corrected_field_does_not_unprotect_it(tmp_path):
    service, _ = setup_review(tmp_path)
    old = synthetic_record()
    field = old["dwelling"]["households"][1]["coding"]["weekly_rent"]
    field.update(value="22", origin="corrected", original_value="12")
    write_record(service.store.directory / "demo.jsonl", old)
    service.store.reload()
    decision = decide(service, action="accept")
    undone = service.undo_latest(
        decision["decision"]["id"], "Reviewer", decision["item"]["version"], "undo"
    )
    [merged] = _merge(service.store.regions["demo"][0], [deepcopy(synthetic_record())])
    assert (
        merged["dwelling"]["households"][1]["coding"]["weekly_rent"]
        == undone["item"]["field"]
    )


@pytest.mark.parametrize("pending", [False, True])
def test_it89_note_front_matching_and_review_history_survive_same_rerun(
    tmp_path, pending
):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["cards"] = [
        {"role": "survey-front", "image": "synthetic.pdf", "page": 3},
        {"role": "survey-back", "image": "synthetic.pdf", "page": 4},
    ]
    note = {
        "text": {
            "value": "Corrected verbatim note",
            "status": "ok",
            "confidence": None,
            "source": "survey-back",
            "origin": "corrected",
            "original_value": "Machine note",
        },
        "page": 4,
        "front_page": 3,
        "household_id": None,
    }
    record["dwelling"]["notes"] = [deepcopy(note)]
    service.store.save("demo", service.store.regions["demo"][1], [record])
    decision = decide(service, action="accept")
    if pending:
        service.undo_latest(
            decision["decision"]["id"],
            "Reviewer",
            decision["item"]["version"],
            "combined-undo",
        )
    old = deepcopy(service.store.regions["demo"][0][0])
    reviewed = deepcopy(old["dwelling"]["households"][1]["coding"]["weekly_rent"])
    rebuilt = synthetic_record()
    rebuilt["dwelling"]["cards"] = deepcopy(record["dwelling"]["cards"]) + [
        {"role": "survey-front", "image": "synthetic.pdf", "page": 5},
        {"role": "survey-back", "image": "synthetic.pdf", "page": 6},
    ]
    rebuilt["dwelling"]["notes"] = [
        {
            "text": {
                "value": "New front note",
                "status": "ok",
                "confidence": None,
                "source": "survey-back",
            },
            "page": 6,
            "front_page": 5,
            "household_id": None,
        },
        {
            **deepcopy(note),
            "text": {
                "value": "Reread old front note",
                "status": "ok",
                "confidence": None,
                "source": "survey-back",
            },
        },
    ]
    rebuilt["dwelling"]["households"][1]["coding"]["weekly_rent"]["value"] = "99"
    [merged] = _merge([old], [rebuilt])
    assert merged["schema_version"] == SCHEMA_VERSION
    assert merged["dwelling"]["notes"][0]["front_page"] == 5
    kept_note = merged["dwelling"]["notes"][1]
    assert kept_note["text"] == note["text"]
    assert (kept_note["front_page"], kept_note["page"], kept_note["household_id"]) == (
        3,
        4,
        None,
    )
    assert "household_ambiguous" in kept_note["flags"]
    field = merged["dwelling"]["households"][1]["coding"]["weekly_rent"]
    assert field["review"] == reviewed["review"]
    assert field["value"] == ("99" if pending else reviewed["value"])
    validate_records([merged], "demo")

from copy import deepcopy
from dataclasses import replace

import pytest
from review_support import decide, refs, setup_review, write_record

from survey import records
from survey.records import RecordStore, ReviewError, current_fields, schema_errors
from survey.review.service import ReviewService


@pytest.mark.parametrize(
    ("action", "value", "status", "review"),
    [
        ("accept", None, "ok", "accepted"),
        ("correct", "009", "ok", "corrected"),
        ("no_data", None, "no_data", "corrected"),
        ("illegible", None, "illegible", "corrected"),
    ],
)
def test_actions_persist_and_only_change_second_household(
    tmp_path, action, value, status, review
):
    service, settings = setup_review(tmp_path)
    before = deepcopy(service.store.regions["demo"][0][0])
    result = decide(service, action=action, value=value)
    field = result["item"]["field"]
    assert field["status"] == status and field["review"]["state"] == review
    if action == "accept":
        assert "origin" not in field
        assert field["value"] == "12"
    else:
        assert field["origin"] == "corrected" and field["original_value"] == "12"
        assert field["value"] == (value if action == "correct" else None)
    event = result["decision"]
    assert event["reviewer"] == "Test Reviewer" and event["timestamp"].endswith(
        "+00:00"
    )
    assert "review" not in event["before"] and "review" not in event["after"]
    after = deepcopy(service.store.regions["demo"][0][0])
    after["dwelling"]["households"][1]["coding"]["weekly_rent"] = before["dwelling"][
        "households"
    ][1]["coding"]["weekly_rent"]
    assert after == before
    restarted = ReviewService(
        RecordStore(settings.data_checkout / "results"), refs(), [], service.scans
    )
    assert restarted.item(refs()[1].item_id)["field"] == field
    assert restarted.queue()["resolved"] == 1


def test_exact_digits_unknown_codes_sentinels_and_confidence(tmp_path):
    service, _ = setup_review(tmp_path)
    unknown = decide(service, refs()[2], value="0008")
    assert unknown["item"]["field"]["value"] == "0008"
    assert unknown["item"]["field"]["code"] == "0008"
    assert unknown["item"]["field"]["label"] is None
    assert any("Unknown" in w for w in unknown["item"]["warnings"])
    result = decide(service, value="02", request_id="sentinel")
    assert (
        result["item"]["field"]["label"] and result["item"]["field"]["status"] == "ok"
    )
    assert result["item"]["field"]["confidence"] is None
    assert "negated" not in result["item"]["field"]


@pytest.mark.parametrize(
    "value", ["O4", " 04", "04 ", "-1", "1.2", "", "１", "1" * 65, 4]
)
def test_reviewer_digits_are_not_ocr_normalized(tmp_path, value):
    service, _ = setup_review(tmp_path)
    with pytest.raises(ReviewError, match="ASCII"):
        decide(service, value=value)
    assert service.item(refs()[1].item_id)["review_state"] == "pending"


@pytest.mark.parametrize("action", ["correct", "no_data", "illegible"])
def test_identity_and_negated_fields_are_accept_only(tmp_path, action):
    service, _ = setup_review(tmp_path)
    with pytest.raises(ReviewError, match="unsupported"):
        decide(service, refs()[3], action=action)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["households"][1]["coding"]["weekly_rent"]["negated"] = True
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    with pytest.raises(ReviewError, match="unsupported"):
        decide(service, action=action)
    assert service.queue()["complete"] is False
    assert decide(service, action="accept")["item"]["review_state"] == "accepted"


def test_accepting_illegible_resolves_without_recovering_value(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    field = record["dwelling"]["households"][1]["coding"]["weekly_rent"]
    field.update(status="illegible", value=None, code=None, label=None)
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    result = decide(service, action="accept")
    assert result["item"]["resolved"] and result["item"]["field"]["value"] is None


@pytest.mark.parametrize("action", ["no_data", "illegible"])
@pytest.mark.parametrize("accept_before_amend", [False, True])
def test_empty_decision_can_be_amended_after_acceptance_and_restart(
    tmp_path, action, accept_before_amend
):
    service, settings = setup_review(tmp_path)
    decide(service, action=action)
    if accept_before_amend:
        decide(service, action="accept", request_id="accept-empty")
    service = ReviewService(
        RecordStore(settings.data_checkout / "results"), refs(), [], service.scans
    )
    amended = decide(service, value="04", request_id="amend-empty")
    field = amended["item"]["field"]
    assert field["value"] == "04" and field["status"] == "ok"
    assert field["review"]["state"] == "corrected"
    assert field["original_value"] == "12"
    history = field["review"]["history"]
    assert len(history) == (3 if accept_before_amend else 2)
    assert history[-1]["before"]["value"] is None
    assert history[-1]["after"]["value"] == "04"
    undone = service.undo_latest(
        amended["decision"]["id"], "Reviewer", amended["item"]["version"], "undo-amend"
    )
    assert undone["item"]["field"]["value"] is None
    assert undone["item"]["field"]["status"] == action


def test_idempotent_retry_after_restart_and_conflicting_reuse(tmp_path):
    service, settings = setup_review(tmp_path)
    version = service.item(refs()[1].item_id)["version"]
    first = decide(service, version=version)
    restarted = ReviewService(
        RecordStore(settings.data_checkout / "results"), refs(), [], service.scans
    )
    second = decide(restarted, version=version)
    assert second["replayed"] and second["decision"] == first["decision"]
    assert len(second["item"]["field"]["review"]["history"]) == 1
    for change in [{"value": "22"}, {"ref": refs()[0]}]:
        with pytest.raises(ReviewError, match="Request ID"):
            decide(restarted, version=version, **change)


def test_repeated_correction_original_value_and_latest_undo(tmp_path):
    service, _ = setup_review(tmp_path)
    first = decide(service)
    second = decide(service, value="002", request_id="second")
    assert second["item"]["field"]["original_value"] == "12"
    with pytest.raises(ReviewError, match="latest"):
        service.undo_latest(
            first["decision"]["id"], "Reviewer", second["item"]["version"], "undo-old"
        )
    undo = service.undo_latest(
        second["decision"]["id"], "Reviewer", second["item"]["version"], "undo-second"
    )
    assert (
        undo["item"]["field"]["value"] == "09"
        and len(undo["item"]["field"]["review"]["history"]) == 3
    )
    last = service.undo_latest(
        first["decision"]["id"], "Reviewer", undo["item"]["version"], "undo-first"
    )
    assert last["item"]["review_state"] == "pending"
    assert {k: v for k, v in last["item"]["field"].items() if k != "review"} == first[
        "decision"
    ]["before"]
    assert len(last["item"]["field"]["review"]["history"]) == 4
    assert service.undo_latest(
        first["decision"]["id"], "Reviewer", undo["item"]["version"], "undo-first"
    )["replayed"]


def test_noop_and_stale_rejected_without_history(tmp_path):
    service, _ = setup_review(tmp_path)
    version = service.item(refs()[1].item_id)["version"]
    result = decide(service, action="accept")
    with pytest.raises(ReviewError, match="already recorded"):
        decide(service, action="accept", request_id="noop")
    with pytest.raises(ReviewError, match="Region changed"):
        decide(service, version=version, request_id="stale")
    assert len(service.item(refs()[1].item_id)["field"]["review"]["history"]) == len(
        result["item"]["field"]["review"]["history"]
    )


def test_failed_save_keeps_index_and_jsonl(tmp_path, monkeypatch):
    service, _ = setup_review(tmp_path)
    before = (service.store.directory / "demo.jsonl").read_bytes()

    def fail(*args):
        raise PermissionError("disk denied")

    monkeypatch.setattr(records, "write_atomic", fail)
    with pytest.raises(ReviewError, match="previous local data"):
        decide(service)
    assert (service.store.directory / "demo.jsonl").read_bytes() == before
    assert service.item(refs()[1].item_id)["review_state"] == "pending"
    assert not service.requests


def test_direct_lookup_never_reads_source_batch(tmp_path, monkeypatch):
    service, _ = setup_review(tmp_path)

    def fail(*args):
        pytest.fail("Source JSONL was reread")

    monkeypatch.setattr(type(service.store.directory), "read_bytes", fail)
    assert service.item(refs()[1].item_id)["field"]["value"] == "12"


def test_input_errors_and_missing_scans_stay_in_completion(tmp_path):
    service, settings = setup_review(tmp_path)
    service.diagnostics = [{"code": "invalid_reference", "message": "malformed flag"}]
    service.references[replace(refs()[0], page=999).item_id] = replace(
        refs()[0], page=999
    )
    queue = service.queue("demo")
    assert (
        queue["total"] == 7
        and queue["unresolved"] == 7
        and len(queue["diagnostics"]) == 2
    )
    (settings.scan_root / "demo" / "synthetic.pdf").unlink()
    item = service.item(refs()[1].item_id)
    assert item["allowed_actions"] == [] and item["diagnostics"]
    with pytest.raises(ReviewError, match="original readable scan"):
        decide(service)


def test_schema_rejects_nested_and_malformed_audit(tmp_path):
    service, _ = setup_review(tmp_path)
    decide(service)
    record = deepcopy(service.store.regions["demo"][0][0])
    field = record["dwelling"]["households"][1]["coding"]["weekly_rent"]
    assert not schema_errors(record)
    field["review"]["history"][0]["before"]["review"] = {}
    assert schema_errors(record)
    field["review"]["history"][0]["before"].pop("review")
    field["review"]["history"][0]["timestamp"] = "yesterday"
    assert schema_errors(record)
    field["review"]["history"][0]["timestamp"] = "2026-10-11T00:00:00Z"
    record["schema_version"] = "0.2.0"
    assert schema_errors(record)
    assert len(list(current_fields(field))) == 1


def test_queue_refresh_preserves_progress_and_stale_collisions(tmp_path):
    service, _ = setup_review(tmp_path)
    result = decide(service)
    stale = replace(refs()[1], field_path=refs()[0].field_path)
    service.replace_queue([refs()[1], stale], [])
    queue = service.queue()
    assert queue["total"] == 2 and queue["resolved"] == 1 and not queue["complete"]
    assert len(queue["diagnostics"]) == 1
    assert service.item(refs()[1].item_id)["field"] == result["item"]["field"]


def test_non_null_confidence_is_preserved_through_review(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["households"][1]["coding"]["weekly_rent"]["confidence"] = 0.41
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    assert decide(service)["item"]["field"]["confidence"] == 0.41


def test_batch_counter_tracks_decisions_undo_and_queue_replacement(tmp_path):
    service, _ = setup_review(tmp_path)
    service.replace_queue([refs()[0], refs()[1]], [])
    assert not service.batch_complete("demo", "synthetic.pdf")
    decide(service, refs()[0], action="accept", request_id="first")
    last = decide(service, refs()[1], action="accept", request_id="second")
    assert service.batch_complete("demo", "synthetic.pdf")
    service.undo_latest(
        last["decision"]["id"], "Test Reviewer", last["item"]["version"], "undo-counter"
    )
    assert not service.batch_complete("demo", "synthetic.pdf")
    service.replace_queue([refs()[0]], [])
    assert service.batch_complete("demo", "synthetic.pdf")
    service.replace_queue(
        [refs()[0]],
        [
            {
                "code": "invalid_reference",
                "message": "Bad row",
                "region": None,
                "batch": None,
            }
        ],
    )
    assert not service.batch_complete("demo", "synthetic.pdf")


def test_batch_counter_invalidates_when_previously_reviewed_page_disappears(tmp_path):
    from PIL import Image
    from review_support import synthetic_pdf

    service, settings = setup_review(tmp_path)
    service.replace_queue([refs()[0], refs()[1]], [])
    decide(service, refs()[0], action="accept", request_id="first")
    decide(service, refs()[1], action="accept", request_id="second")
    assert service.batch_complete("demo", "synthetic.pdf")
    path = settings.scan_root / "demo/synthetic.pdf"
    Image.new("RGB", (100, 100), "white").save(path)
    assert not service.batch_complete("demo", "synthetic.pdf")
    synthetic_pdf(path)
    assert service.batch_complete("demo", "synthetic.pdf")

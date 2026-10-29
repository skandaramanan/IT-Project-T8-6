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


@pytest.mark.usefixtures("shape")
@pytest.mark.parametrize("action", ["correct", "no_data", "illegible"])
def test_negated_fields_are_accept_only(tmp_path, action):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["households"][1]["coding"]["weekly_rent"]["negated"] = True
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    with pytest.raises(ReviewError, match="unsupported"):
        decide(service, action=action)
    assert service.queue()["complete"] is False
    assert decide(service, action="accept")["item"]["review_state"] == "accepted"


@pytest.mark.usefixtures("published")
def test_both_municipality_copies_are_editable_with_safe_undo(tmp_path):
    service, settings = setup_review(tmp_path)
    shared = refs()[3]
    household = replace(shared, field_path="/dwelling/households/0/municipality")
    service.replace_queue([shared, household], [])
    for ref in (shared, household):
        item = service.item(ref.item_id)
        assert item["allowed_actions"] == ["accept", "correct"]
        assert item["identity_kind"] == "municipality"
        assert (
            len(
                [
                    field
                    for field in item["card_fields"]
                    if field["label"] == "Municipality"
                ]
            )
            == 2
        )
    corrected = decide(service, shared, value="28")
    record = service.store.regions["demo"][0][0]
    assert record["dwelling"]["municipality"]["value"] == "28"
    assert record["dwelling"]["households"][0]["municipality"]["value"] == "28"
    assert record["dwelling"]["households"][0]["record_id"] == "28-0006-01"
    assert record["dwelling"]["households"][1]["record_id"] == "27-0006-02"
    assert corrected["item"]["id"] == shared.item_id
    service = ReviewService(
        RecordStore(settings.data_checkout / "results"),
        [shared, household],
        [],
        service.scans,
    )
    undone = service.undo_latest(
        corrected["decision"]["id"],
        "Reviewer",
        service.item(shared.item_id)["version"],
        "undo-municipality",
    )
    assert undone["item"]["field"]["value"] == "27"
    record = service.store.regions["demo"][0][0]
    assert record["dwelling"]["households"][0]["municipality"]["value"] == "27"
    assert record["dwelling"]["households"][0]["record_id"] == "27-0006-01"


@pytest.mark.usefixtures("published")
@pytest.mark.parametrize("edit_alias", [False, True])
def test_shared_municipality_preserves_later_legacy_card_evidence(tmp_path, edit_alias):
    service, settings = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["schema_version"] = "0.5.0"
    for index, household in enumerate(record["dwelling"]["households"]):
        if index != 0 or not edit_alias:
            household.pop("municipality")
    record["dwelling"]["notes"][0]["household_id"] = "27-0006-02"
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    ref = (
        replace(refs()[3], field_path="/dwelling/households/0/municipality")
        if edit_alias
        else refs()[3]
    )
    service.replace_queue([ref], [])
    result = decide(service, ref, value="28")
    changed = service.store.regions["demo"][0][0]
    assert [
        household["record_id"] for household in changed["dwelling"]["households"]
    ] == ["28-0006-01", "27-0006-02"]
    assert changed["dwelling"]["notes"][0]["household_id"] == "27-0006-02"
    assert len(result["decision"]["identity_ids"]) == 1
    service = ReviewService(
        RecordStore(settings.data_checkout / "results"), [ref], [], service.scans
    )
    service.undo_latest(
        result["decision"]["id"],
        "Reviewer",
        service.item(ref.item_id)["version"],
        "undo-legacy-municipality",
    )
    restored = service.store.regions["demo"][0][0]
    assert [
        household["record_id"] for household in restored["dwelling"]["households"]
    ] == ["27-0006-01", "27-0006-02"]
    assert restored["dwelling"]["notes"][0]["household_id"] == "27-0006-02"
    assert "municipality" not in restored["dwelling"]["households"][1]


@pytest.mark.usefixtures("published")
def test_municipality_mirror_preserves_each_machine_reading(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["households"][0]["municipality"].update(
        value="26", confidence=0.4
    )
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    corrected = decide(service, refs()[3], value="28")
    alias = service.store.regions["demo"][0][0]["dwelling"]["households"][0][
        "municipality"
    ]
    assert alias["original_value"] == "26"
    assert alias["confidence"] == 0.4
    assert corrected["item"]["field"]["original_value"] == "27"


@pytest.mark.usefixtures("published")
def test_municipality_alias_history_is_not_overwritten(tmp_path):
    service, _ = setup_review(tmp_path)
    shared = refs()[3]
    alias = replace(shared, field_path="/dwelling/households/0/municipality")
    service.replace_queue([shared, alias], [])
    corrected = decide(service, shared, value="28")
    accepted = decide(service, alias, action="accept", request_id="accept-alias")
    with pytest.raises(ReviewError, match="changed later"):
        service.undo_latest(
            corrected["decision"]["id"],
            "Reviewer",
            accepted["item"]["version"],
            "undo-shared",
        )
    with pytest.raises(ReviewError, match="review history"):
        decide(service, shared, value="29", request_id="correct-again")
    service.undo_latest(
        accepted["decision"]["id"],
        "Reviewer",
        accepted["item"]["version"],
        "undo-alias",
    )
    restored = service.undo_latest(
        corrected["decision"]["id"],
        "Reviewer",
        service.item(shared.item_id)["version"],
        "undo-after-alias",
    )
    assert restored["item"]["field"]["value"] == "27"
    assert len(service.item(alias.item_id)["field"]["review"]["history"]) == 2


@pytest.mark.usefixtures("published")
@pytest.mark.parametrize(
    ("pointer", "value", "expected"),
    [
        ("/dwelling/dwelling_no", "7a", ["27-0007A-01", "27-0007A-02"]),
        ("/dwelling/households/0/household_no", "03", ["27-0006-03", "27-0006-02"]),
        ("/dwelling/households/1/municipality", "28", ["27-0006-01", "28-0006-02"]),
    ],
)
def test_identity_corrections_rebuild_ids_and_undo(tmp_path, pointer, value, expected):
    service, _ = setup_review(tmp_path)
    original = deepcopy(service.store.regions["demo"][0][0])
    page = 2 if "/1/" in pointer else 1
    ref = replace(refs()[3], page=page, field_path=pointer)
    service.replace_queue([ref], [])
    corrected = decide(service, ref, value=value)
    record = service.store.regions["demo"][0][0]
    assert [h["record_id"] for h in record["dwelling"]["households"]] == expected
    assert record["dwelling"]["cards"] == original["dwelling"]["cards"]
    assert corrected["item"]["source"]["page"] == page
    service.undo_latest(
        corrected["decision"]["id"],
        "Reviewer",
        corrected["item"]["version"],
        "undo-identity",
    )
    assert [
        h["record_id"]
        for h in service.store.regions["demo"][0][0]["dwelling"]["households"]
    ] == ["27-0006-01", "27-0006-02"]


@pytest.mark.usefixtures("published")
@pytest.mark.parametrize(
    ("pointer", "value"),
    [
        ("/dwelling/municipality", "123"),
        ("/dwelling/municipality", "２"),
        ("/dwelling/dwelling_no", "12345"),
        ("/dwelling/dwelling_no", "1AB"),
        ("/dwelling/households/0/household_no", "100"),
    ],
)
def test_identity_validation_rejects_invalid_input_atomically(tmp_path, pointer, value):
    service, _ = setup_review(tmp_path)
    ref = replace(refs()[3], field_path=pointer)
    service.replace_queue([ref], [])
    before = (service.store.directory / "demo.jsonl").read_bytes()
    with pytest.raises(ReviewError, match="ASCII"):
        decide(service, ref, value=value)
    assert (service.store.directory / "demo.jsonl").read_bytes() == before


@pytest.mark.usefixtures("published")
def test_identity_collision_rejected_atomically(tmp_path):
    service, _ = setup_review(tmp_path)
    ref = replace(refs()[3], field_path="/dwelling/households/0/household_no")
    service.replace_queue([ref], [])
    before = (service.store.directory / "demo.jsonl").read_bytes()
    with pytest.raises(ReviewError, match="already belongs"):
        decide(service, ref, value="2")
    assert (service.store.directory / "demo.jsonl").read_bytes() == before


@pytest.mark.usefixtures("published")
def test_identity_note_links_and_null_ids_restore_after_restart(tmp_path):
    service, settings = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    # Legacy data can have a valid-looking value but a deliberately withheld ID.
    record["dwelling"]["households"][0]["record_id"] = None
    record["dwelling"]["notes"][0]["household_id"] = "27-0006-02"
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    ref = replace(refs()[3], field_path="/dwelling/dwelling_no")
    service.replace_queue([ref], [])
    corrected = decide(service, ref, value="7A")
    assert (
        service.store.regions["demo"][0][0]["dwelling"]["notes"][0]["household_id"]
        == "27-0007A-02"
    )
    service = ReviewService(
        RecordStore(settings.data_checkout / "results"), [ref], [], service.scans
    )
    service.undo_latest(
        corrected["decision"]["id"],
        "Reviewer",
        service.item(ref.item_id)["version"],
        "undo-notes",
    )
    restored = service.store.regions["demo"][0][0]
    assert restored["dwelling"]["households"][0]["record_id"] is None
    assert restored["dwelling"]["notes"][0]["household_id"] == "27-0006-02"


@pytest.mark.usefixtures("published")
def test_identity_undo_preserves_later_other_field_corrections(tmp_path):
    service, _ = setup_review(tmp_path)
    dwelling = replace(refs()[3], field_path="/dwelling/dwelling_no")
    household = replace(refs()[3], field_path="/dwelling/households/0/household_no")
    service.replace_queue([dwelling, household, refs()[1]], [])
    first = decide(service, dwelling, value="7")
    later = decide(service, household, value="3", request_id="later-identity")
    with pytest.raises(ReviewError, match="changed later"):
        service.undo_latest(
            first["decision"]["id"], "Reviewer", later["item"]["version"], "undo-first"
        )
    service.undo_latest(
        later["decision"]["id"], "Reviewer", later["item"]["version"], "undo-later"
    )
    rent = decide(service, value="08", request_id="later-rent")
    service.undo_latest(
        first["decision"]["id"], "Reviewer", rent["item"]["version"], "undo-first-after"
    )
    record = service.store.regions["demo"][0][0]
    assert record["dwelling"]["households"][1]["coding"]["weekly_rent"]["value"] == "08"
    assert record["dwelling"]["households"][0]["record_id"] == "27-0006-01"


@pytest.mark.usefixtures("published")
def test_survey_front_identity_edits_do_not_change_coding_identity(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["handwritten"]["dwelling_no"] = {
        "value": "6",
        "status": "ok",
        "confidence": None,
        "source": "survey-front",
    }
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    ref = replace(refs()[3], page=3, field_path="/dwelling/handwritten/dwelling_no")
    service.replace_queue([ref], [])
    before = (service.store.directory / "demo.jsonl").read_bytes()
    for value in ["7A as written", "12 see back", "12345", " 7"]:
        with pytest.raises(ReviewError, match="ASCII") as error:
            decide(service, ref, value=value)
        assert error.value.code == "invalid_value"
    assert (service.store.directory / "demo.jsonl").read_bytes() == before
    result = decide(service, ref, value="7A")
    assert result["item"]["identity_kind"] is None
    after = service.store.regions["demo"][0][0]
    assert after["dwelling"]["dwelling_no"]["value"] == "6"
    assert [h["record_id"] for h in after["dwelling"]["households"]] == [
        "27-0006-01",
        "27-0006-02",
    ]


@pytest.mark.usefixtures("published")
def test_live_identity_issues_leave_historical_flags_unchanged(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["flags"] = [
        "identity_reread",
        "paired_by_position",
        "persons_unassigned",
        "fronts_disagree",
    ]
    record["dwelling"]["households"][1]["municipality"]["value"] = "28"
    record["dwelling"]["households"][1]["record_id"] = "28-0006-02"
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    ref = replace(refs()[3], page=2, field_path="/dwelling/households/1/municipality")
    service.replace_queue([ref], [])
    before_codes = {
        issue["code"] for issue in service.item(ref.item_id)["review_issues"]
    }
    assert before_codes == {"municipality_mismatch", "persons_unassigned"}
    result = decide(service, ref, value="27")
    assert [issue["code"] for issue in result["item"]["review_issues"]] == [
        "persons_unassigned"
    ]
    assert (
        service.store.regions["demo"][0][0]["dwelling"]["flags"]
        == record["dwelling"]["flags"]
    )


@pytest.mark.usefixtures("shape")
@pytest.mark.parametrize("action", ["no_data", "illegible"])
def test_coding_identity_requires_an_explicit_corrected_value(tmp_path, action):
    service, _ = setup_review(tmp_path)
    with pytest.raises(ReviewError, match="unsupported"):
        decide(service, refs()[3], action=action)


@pytest.mark.usefixtures("published")
def test_identity_conflicts_include_sibling_with_withheld_id(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["households"][1]["record_id"] = None
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    ref = replace(refs()[3], field_path="/dwelling/households/0/household_no")
    service.replace_queue([ref], [])
    with pytest.raises(ReviewError, match="already belongs"):
        decide(service, ref, value="2")


@pytest.mark.usefixtures("published")
def test_undo_null_identity_dependency_blocks_later_id_creation(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["dwelling_no"].update(value=None, status="omitted")
    for household in record["dwelling"]["households"]:
        household["record_id"] = None
    write_record(service.store.directory / "demo.jsonl", record)
    service.store.reload()
    municipality = refs()[3]
    dwelling = replace(municipality, field_path="/dwelling/dwelling_no")
    service.replace_queue([municipality, dwelling], [])
    first = decide(service, municipality, value="28")
    assert first["decision"]["identity_ids"] == [
        {"index": 0, "before": None, "after": None}
    ]
    second = decide(service, dwelling, value="7", request_id="repair-dwelling")
    with pytest.raises(ReviewError, match="changed later"):
        service.undo_latest(
            first["decision"]["id"],
            "Reviewer",
            second["item"]["version"],
            "undo-earlier",
        )


@pytest.mark.usefixtures("published")
def test_identity_counts_cache_invalidates_after_correction(tmp_path, monkeypatch):
    service, _ = setup_review(tmp_path)
    from survey.review import service as review_module

    original = review_module.identity_ids
    calls = []

    def count(record, *args):
        calls.append(record)
        return original(record, *args)

    monkeypatch.setattr(review_module, "identity_ids", count)
    service.item(refs()[3].item_id)
    first_count = len(calls)
    service.item(refs()[3].item_id)
    # One local check remains; the region's duplicate-ID index is reused.
    assert len(calls) == first_count + 1
    decide(service, refs()[3], value="28")
    assert (
        service.region_identity_counts(
            "demo", service.item(refs()[3].item_id)["version"]
        )["28-0006-01"]
        == 1
    )


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
    with pytest.raises(ReviewError, match="latest|later decision"):
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


@pytest.mark.usefixtures("published")
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

import json
from copy import deepcopy
from dataclasses import replace

import pytest
from review_support import decide, refs, setup_review, synthetic_record, write_record

from survey import records
from survey.records import (
    Reference,
    ReviewError,
    read_records,
    resolve_field,
    schema_errors,
    validate_records,
)
from survey.review.queue import load_queue


def test_old_and_new_schema_records_are_readable(tmp_path):
    record = synthetic_record()
    record["schema_version"] = "0.2.0"
    path = tmp_path / "demo.jsonl"
    write_record(path, record)
    loaded, version = read_records(path, "demo")
    assert loaded == [record] and version
    record["schema_version"] = "0.4.0"
    assert not schema_errors(record)


def test_physical_identity_and_shared_ownership():
    record = synthetic_record()
    resolved = resolve_field([record], refs()[1])
    assert resolved.household["record_id"] == "27-0006-02"
    assert resolved.field["value"] == "12"
    assert resolve_field([record], refs()[2]).label == "Garden"
    for ref in [
        replace(refs()[1], field_path=refs()[0].field_path),
        replace(refs()[2], page=2),
        replace(refs()[1], field_path="/dwelling/address"),
    ]:
        with pytest.raises(ReviewError):
            resolve_field([record], ref)


def test_missing_and_ambiguous_card():
    record = synthetic_record()
    with pytest.raises(ReviewError, match="uniquely"):
        resolve_field([record], replace(refs()[0], page=3))
    with pytest.raises(ReviewError, match="uniquely"):
        resolve_field([record, deepcopy(record)], refs()[0])


@pytest.mark.parametrize(
    "args",
    [
        ("../demo", "synthetic.pdf", 1, "/dwelling/municipality"),
        ("demo", "../synthetic.pdf", 1, "/dwelling/municipality"),
        ("demo", "C:\\scan.pdf", 1, "/dwelling/municipality"),
        ("demo", "synthetic.pdf", 0, "/dwelling/municipality"),
        ("demo", "synthetic.pdf", True, "/dwelling/municipality"),
    ],
)
def test_bad_reference_rejected(args):
    with pytest.raises(ReviewError):
        Reference(*args)


def test_queue_deduplicates_and_reports_bad_rows(tmp_path):
    good = {
        "region": "demo",
        "pdf": "synthetic.pdf",
        "page": 1,
        "field_path": refs()[0].field_path,
    }
    path = tmp_path / "flags.jsonl"
    path.write_text(
        json.dumps(good)
        + "\n"
        + json.dumps(good)
        + "\nno json\n"
        + json.dumps({**good, "page": 0})
        + "\n[]\n"
    )
    references, diagnostics = load_queue(path)
    assert len(references) == 1 and len(diagnostics) == 3
    assert diagnostics[0]["line"] == 3


def test_record_validation_rejects_duplicates_and_wrong_region(tmp_path):
    record = synthetic_record()
    record["dwelling"]["households"][1]["cards"][0]["page"] = 1
    path = tmp_path / "demo.jsonl"
    write_record(path, record)
    with pytest.raises(ReviewError, match="duplicate"):
        read_records(path, "demo")
    write_record(path, synthetic_record())
    with pytest.raises(ReviewError, match="belong"):
        read_records(path, "other")


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_atomic_failure_keeps_original_and_cleans_temp(tmp_path, monkeypatch, failure):
    path = tmp_path / "demo.jsonl"
    path.write_text("original")

    def fail(*args):
        raise PermissionError("simulated Windows permission error")

    monkeypatch.setattr(records.os, failure, fail)
    with pytest.raises(PermissionError):
        records.write_atomic(path, "replacement")
    assert path.read_text() == "original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["demo.jsonl"]


def test_stale_or_external_change_cannot_overwrite(tmp_path):
    service, _ = setup_review(tmp_path)
    store = service.store
    old = store.regions["demo"][1]
    with pytest.raises(ReviewError, match="changed"):
        store.save("demo", "stale", deepcopy(store.regions["demo"][0]))
    path = store.directory / "demo.jsonl"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ReviewError, match="external writer"):
        store.save("demo", old, deepcopy(store.regions["demo"][0]))


def test_item_id_survives_household_index_change():
    assert (
        replace(
            refs()[1], field_path="/dwelling/households/0/coding/weekly_rent"
        ).item_id
        == refs()[1].item_id
    )


def test_validator_rejects_inconsistent_audit_state(tmp_path):
    from review_support import decide

    service, _ = setup_review(tmp_path)
    decide(service)
    record = deepcopy(service.store.regions["demo"][0][0])
    field = record["dwelling"]["households"][1]["coding"]["weekly_rent"]
    field["review"]["state"] = "accepted"
    write_record(service.store.directory / "demo.jsonl", record)
    with pytest.raises(ReviewError, match="disagrees"):
        read_records(service.store.directory / "demo.jsonl", "demo")


@pytest.mark.parametrize(
    ("part", "key", "value"),
    [
        ("request", "value", "888"),
        ("request", "value", "not digits"),
        ("after", "confidence", 0.8),
        ("after", "original_value", "99"),
        ("after", "source", "survey-front"),
        ("after", "negated", True),
    ],
)
def test_validator_rejects_request_or_provenance_mismatch(tmp_path, part, key, value):
    service, _ = setup_review(tmp_path)
    decide(service)
    record = deepcopy(service.store.regions["demo"][0][0])
    field = record["dwelling"]["households"][1]["coding"]["weekly_rent"]
    event = field["review"]["history"][0]
    event[part][key] = value
    field.update(event["after"])
    with pytest.raises(ReviewError, match="request|digits"):
        validate_records([record], "demo")


@pytest.mark.parametrize("action", ["no_data", "illegible"])
def test_validator_rejects_empty_status_decision_with_numeric_payload(tmp_path, action):
    service, _ = setup_review(tmp_path)
    decide(service)
    record = deepcopy(service.store.regions["demo"][0][0])
    event = record["dwelling"]["households"][1]["coding"]["weekly_rent"]["review"][
        "history"
    ][0]
    event["action"] = event["request"]["action"] = action
    event["request"]["value"] = None
    with pytest.raises(ReviewError, match="payload disagrees"):
        validate_records([record], "demo")


@pytest.mark.parametrize("part", ["before", "item_id"])
def test_validator_rejects_broken_active_history_chain(tmp_path, part):
    service, _ = setup_review(tmp_path)
    decide(service)
    decide(service, value="008", request_id="second")
    record = deepcopy(service.store.regions["demo"][0][0])
    event = record["dwelling"]["households"][1]["coding"]["weekly_rent"]["review"][
        "history"
    ][1]
    if part == "before":
        event["before"]["value"] = "99"
    else:
        event["item_id"] = "another-item"
    with pytest.raises(ReviewError, match="continuous|inconsistent"):
        validate_records([record], "demo")


@pytest.mark.parametrize("key", ["id", "request_id"])
def test_validator_rejects_duplicate_audit_ids_across_fields(tmp_path, key):
    service, _ = setup_review(tmp_path)
    first = decide(service, refs()[0], action="accept")
    decide(service, request_id="second")
    record = deepcopy(service.store.regions["demo"][0][0])
    event = record["dwelling"]["households"][1]["coding"]["weekly_rent"]["review"][
        "history"
    ][0]
    event[key] = first["decision"][key]
    with pytest.raises(ReviewError, match="Duplicate audit"):
        validate_records([record], "demo")


@pytest.mark.parametrize("key", ["id", "request_id"])
def test_dataset_duplicate_is_rejected_by_cli_reload_and_save(
    tmp_path, monkeypatch, key
):
    from uuid import uuid4

    from survey import cli
    from survey.records import RecordStore

    monkeypatch.chdir(tmp_path)
    service, settings = setup_review(tmp_path / "source")
    decide(service)
    before = deepcopy(service.store.regions)
    original_bytes = (service.store.directory / "demo.jsonl").read_bytes()
    other = deepcopy(before["demo"][0][0])
    other["region"] = "other"
    event = other["dwelling"]["households"][1]["coding"]["weekly_rent"]["review"][
        "history"
    ][0]
    event["item_id"] = replace(refs()[1], region="other").item_id
    event["request_id" if key == "id" else "id"] = str(uuid4())
    write_record(service.store.directory / "other.jsonl", other)
    assert cli.main(["validate-results", str(service.store.directory)]) == 1
    with pytest.raises(ReviewError, match="demo.jsonl.*other.jsonl"):
        service.store.reload()
    assert service.store.regions == before
    # A valid multi-region dataset passes and can be indexed.
    event[key] = str(uuid4())
    write_record(service.store.directory / "other.jsonl", other)
    assert cli.main(["validate-results", str(service.store.directory)]) == 0
    service.store.reload()
    changed = deepcopy(service.store.regions["other"][0])
    changed[0]["dwelling"]["households"][1]["coding"]["weekly_rent"]["review"][
        "history"
    ][0][key] = before["demo"][0][0]["dwelling"]["households"][1]["coding"][
        "weekly_rent"
    ]["review"]["history"][0][key]
    other_bytes = (service.store.directory / "other.jsonl").read_bytes()
    with pytest.raises(ReviewError, match="Duplicate audit"):
        service.store.save("other", service.store.regions["other"][1], changed)
    assert (service.store.directory / "other.jsonl").read_bytes() == other_bytes
    assert (service.store.directory / "demo.jsonl").read_bytes() == original_bytes
    assert (
        RecordStore(settings.data_checkout / "results").regions == service.store.regions
    )


def test_decision_validates_only_changed_dwelling_and_does_not_copy_others(
    tmp_path, monkeypatch
):
    service, _ = setup_review(tmp_path)
    extra = synthetic_record()
    for household in extra["dwelling"]["households"]:
        household["cards"][0]["page"] += 2
    store = service.store
    store.save("demo", store.regions["demo"][1], [store.regions["demo"][0][0], extra])
    untouched = store.regions["demo"][0][1]
    original = records.schema_errors
    calls = []

    def observed(record):
        calls.append(record)
        return original(record)

    monkeypatch.setattr(records, "schema_errors", observed)
    decide(service)
    assert len(calls) == 1
    assert store.regions["demo"][0][1] is untouched


def test_current_uses_card_index_without_scanning_region(tmp_path):
    service, _ = setup_review(tmp_path)

    class IndexedOnly(list):
        def __iter__(self):
            pytest.fail("Physical lookup scanned the whole region")

    rows, version = service.store.regions["demo"]
    service.store.regions["demo"] = IndexedOnly(rows), version
    assert service.store.current(refs()[1])[0].household["record_id"] == "27-0006-02"


@pytest.mark.parametrize("version", ["0.1.0", "0.2.0", "0.3.0"])
def test_legacy_versions_reject_review_metadata_in_python(tmp_path, version):
    service, _ = setup_review(tmp_path)
    decide(service)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["schema_version"] = version
    with pytest.raises(ReviewError, match="requires schema 0.4.0"):
        validate_records([record], "demo")


def test_it89_notes_and_review_metadata_coexist(tmp_path):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["schema_version"] = "0.3.0"
    record["dwelling"]["notes"] = [
        {
            "text": {
                "value": "Verbatim notes",
                "status": "ok",
                "confidence": None,
                "source": "survey-back",
            },
            "page": 3,
            "front_page": 2,
            "household_id": None,
        }
    ]
    validate_records([record], "demo")
    service.store.save("demo", service.store.regions["demo"][1], [record])
    decide(service)
    assert service.store.regions["demo"][0][0]["schema_version"] == "0.4.0"
    assert (
        service.store.regions["demo"][0][0]["dwelling"]["notes"]
        == record["dwelling"]["notes"]
    )
    validate_records(service.store.regions["demo"][0], "demo")


@pytest.mark.parametrize("version", ["0.1.0", "0.2.0"])
def test_legacy_household_notes_remain_readable_but_require_migration_before_review(
    tmp_path, version
):
    service, _ = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["schema_version"] = version
    record["dwelling"].pop("notes")
    legacy = {
        "text": "Legacy verbatim notes",
        "source": "survey-back",
        "confidence": None,
    }
    record["dwelling"]["households"][0]["notes"] = legacy
    service.store.save("demo", service.store.regions["demo"][1], [record])
    path = service.store.directory / "demo.jsonl"
    before = path.read_bytes()
    item = service.item(refs()[0].item_id)
    assert item["allowed_actions"] == [] and not item["resolved"]
    assert item["diagnostics"][0]["code"] == "legacy_notes"
    with pytest.raises(ReviewError, match="Migrate legacy household notes"):
        decide(service, refs()[0], action="accept")
    assert path.read_bytes() == before
    assert (
        service.store.current(refs()[0])[0].record["dwelling"]["households"][0]["notes"]
        == legacy
    )
    record["schema_version"] = "0.4.0"
    assert schema_errors(record)

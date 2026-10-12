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
    record["schema_version"] = "0.3.0"
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

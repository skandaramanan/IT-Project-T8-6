"""Per-card review operations against persisted JSONL and synthetic scans."""

import json
from copy import deepcopy

import pytest
from review_support import synthetic_pdf

from survey.extraction.record import build_record
from survey.records import RecordStore, Reference, ReviewError
from survey.review.fields import field_pointers
from survey.review.prepare import prepare_records
from survey.review.prepared_service import card_context, link, preview
from survey.review.relinking import inventory, owner
from survey.review.scans import LocalScanSource
from survey.review.service import ReviewService


def raw_record(page, number="6", household="1", municipality="27", rooms="6"):
    return build_record(
        {
            "Municipality": municipality,
            "Number of Dwelling": number,
            "Number of Household": household,
            "Total Number of Rooms": rooms,
            "Garden": "1",
            "Weekly Rent": "04",
        },
        region="demo",
        image="synthetic.pdf",
        batch="synthetic.pdf",
        page=page,
    )


def with_front(record, page, number):
    record["dwelling"].update(
        cards=[{"role": "survey-front", "image": "synthetic.pdf", "page": page}],
        handwritten={
            "dwelling_no": {
                "value": number,
                "status": "ok",
                "confidence": None,
                "source": "survey-front",
            }
        },
        address={
            "value": f"Synthetic {page}",
            "status": "ok",
            "confidence": None,
            "source": "survey-front",
        },
    )
    return record


def start(tmp_path, records=None):
    records = records or [
        raw_record(1),
        raw_record(2, household="2", rooms="7"),
        with_front(raw_record(3, "7"), 4, "7"),
    ]
    prepared, _ = prepare_records(records)
    directory = tmp_path / "results"
    directory.mkdir(exist_ok=True)
    (directory / "demo.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in prepared)
    )
    scans = tmp_path / "scans"
    synthetic_pdf(scans / "demo" / "synthetic.pdf")
    refs = []
    for r in prepared:
        for hi, h in enumerate(r["dwelling"]["households"]):
            for _, pointer, group in field_pointers(hi, review=True):
                if group != "front" and (
                    pointer.endswith(
                        (
                            "municipality",
                            "dwelling_no",
                            "household_no",
                            "garden",
                            "weekly_rent",
                            "total_number_of_rooms",
                        )
                    )
                ):
                    refs.append(
                        Reference(
                            "demo", "synthetic.pdf", h["cards"][0]["page"], pointer
                        )
                    )
    return ReviewService(
        RecordStore(directory), refs, [], LocalScanSource(scans, tmp_path / "cache")
    )


def ref_for(service, page, suffix):
    return next(
        r
        for r in [*service.references.values(), *service.voluntary_references.values()]
        if r.page == page and r.field_path.endswith("/" + suffix)
    )


def correct(service, page, suffix, value, request_id="change"):
    ref = ref_for(service, page, suffix)
    version = service.item(ref.item_id)["version"]
    analysis = preview(service, ref.item_id, "correct", value, version)
    return service.apply_decision(
        ref.item_id,
        "correct",
        "Reviewer",
        version,
        request_id,
        value,
        duplicate_confirmation=analysis["duplicate_confirmation"],
    )


def current(service, page):
    return next(
        x
        for x in inventory(service.store.regions["demo"][0]).values()
        if x[3]["cards"][0]["page"] == page
    )


def restart(service):
    return ReviewService(
        RecordStore(service.store.directory),
        service.assignment_references,
        service.assignment_diagnostics,
        service.scans,
    )


def undo(service, saved, request_id="undo"):
    return service.undo_latest(
        saved["decision"]["id"],
        "Reviewer",
        service.store.regions["demo"][1],
        request_id,
    )


def test_auto_move_keeps_own_readings_and_undo_preserves_later_edits(tmp_path):
    service = start(tmp_path)
    saved = correct(service, 1, "dwelling_no", "7")
    assert saved["structural_change"]
    assert len(current(service, 1)[2]["dwelling"]["households"]) == 2
    correct(service, 1, "total_number_of_rooms", "9", "rooms")
    correct(service, 2, "garden", "2", "other")
    service = restart(service)
    undo(service, saved)
    assert current(service, 1)[3]["dwelling_no"]["value"] == "6"
    assert current(service, 1)[3]["house"]["total_number_of_rooms"]["value"] == "9"
    assert current(service, 2)[3]["house"]["garden"]["value"] == "2"
    assert len(inventory(service.store.regions["demo"][0])) == 3


def test_duplicate_confirmation_is_required_and_all_peers_clear_on_resolution(tmp_path):
    service = start(tmp_path)
    ref = ref_for(service, 1, "dwelling_no")
    version = service.item(ref.item_id)["version"]
    before = (service.store.directory / "demo.jsonl").read_bytes()
    with pytest.raises(ReviewError, match="Save anyway"):
        service.apply_decision(
            ref.item_id, "correct", "Reviewer", version, "unconfirmed", "7"
        )
    assert (service.store.directory / "demo.jsonl").read_bytes() == before
    saved = correct(service, 1, "dwelling_no", "7")
    assert all("duplicate_record_id" in current(service, p)[3]["flags"] for p in (1, 3))
    assert saved["item"]["duplicate_peers"][0]["page"] == 3
    before_members = [
        r["dwelling"]["households"] for r in service.store.regions["demo"][0]
    ]
    correct(service, 1, "household_no", "2", "household")
    assert all(
        "duplicate_record_id" not in current(service, p)[3]["flags"] for p in (1, 3)
    )
    assert [len(x) for x in before_members] == [
        len(r["dwelling"]["households"]) for r in service.store.regions["demo"][0]
    ]


def test_identity_normalization_scopes_duplicates_to_pdf(tmp_path):
    a, b = raw_record(1, "0006a", "01", "01"), raw_record(2, "6A", "1", "1")
    third = raw_record(3, "6A", "1", "1")
    third["dwelling"]["households"][0]["cards"][0]["image"] = "other.pdf"
    a["dwelling"]["households"][0]["record_id"] = None
    b["dwelling"]["households"][0]["record_id"] = None
    rows, receipt = prepare_records([a, b, third])
    assert len(receipt["derived_identity_changes"]) == 2
    assert len(receipt["preserved_cards"]) == 3
    assert all(
        change["before"] is None and change["after"] == "01-0006A-01"
        for change in receipt["derived_identity_changes"]
    )
    assert "duplicate_record_id" in rows[0]["dwelling"]["households"][0]["flags"]
    assert "duplicate_record_id" in rows[1]["dwelling"]["households"][0]["flags"]
    assert "duplicate_record_id" not in rows[2]["dwelling"]["households"][0]["flags"]


def test_ambiguous_destination_saves_correction_and_duplicate_without_moving(tmp_path):
    service = start(
        tmp_path,
        [
            raw_record(1),
            with_front(raw_record(2, "7"), 3, "7"),
            with_front(raw_record(4, "7"), 5, "7"),
        ],
    )
    saved = correct(service, 1, "dwelling_no", "7")
    assert saved["membership"]["outcome"] == "ambiguous"
    assert not saved["structural_change"]
    assert current(service, 1)[3]["relink"]["state"] == "pending"
    assert len(saved["item"]["duplicate_peers"]) == 2


def test_last_card_retains_evidence_and_link_undo_keeps_number_correction(tmp_path):
    source = with_front(raw_record(1), 2, "6")
    source["dwelling"]["households"][0]["persons"] = [
        {"relationship": {"value": "Head", "status": "ok", "confidence": None}}
    ]
    source["dwelling"]["notes"] = [
        {
            "front_page": 2,
            "page": None,
            "household_id": "27-0006-01",
            "text": {
                "value": "Preserve notes",
                "status": "ok",
                "confidence": None,
                "source": "survey-back",
            },
        }
    ]
    service = start(tmp_path, [source, with_front(raw_record(3, "7"), 4, "7")])
    saved = correct(service, 1, "dwelling_no", "7")
    assert saved["membership"]["outcome"] == "supplementary_pending"
    assert not saved["structural_change"]
    cid = owner("demo", current(service, 1)[3])
    tid = owner("demo", current(service, 3)[3])
    version = service.store.regions["demo"][1]
    with pytest.raises(ReviewError, match="Confirm retention"):
        link(service, cid, tid, False, "Reviewer", version, "no-retain")
    linked = link(service, cid, tid, True, "Reviewer", version, "link")
    context = card_context(service, cid)
    assert context["fronts"][0]["page"] == 4
    assert context["retained_supplements"][0]["scans"][0]["page"] == 2
    assert (
        context["retained_supplements"][0]["payload"]["notes"][0]["text"]["value"]
        == "Preserve notes"
    )
    assert not current(service, 1)[3].get("persons")
    correct(service, 1, "garden", "3", "later-field")
    service = restart(service)
    undo(service, linked)
    assert current(service, 1)[3]["dwelling_no"]["value"] == "7"
    assert current(service, 1)[3]["house"]["garden"]["value"] == "3"
    assert current(service, 1)[3]["persons"][0]["relationship"]["value"] == "Head"
    assert current(service, 1)[2]["dwelling"]["cards"][0]["page"] == 2
    assert not current(service, 1)[3].get("retained_supplements")


def test_move_retry_after_restart_does_not_repeat_or_duplicate_history(tmp_path):
    service = start(tmp_path)
    ref = ref_for(service, 1, "dwelling_no")
    version = service.store.regions["demo"][1]
    token = preview(service, ref.item_id, "correct", "7", version)[
        "duplicate_confirmation"
    ]
    first = service.apply_decision(
        ref.item_id,
        "correct",
        "Reviewer",
        version,
        "replay",
        "7",
        duplicate_confirmation=token,
    )
    service = restart(service)
    replayed = service.apply_decision(
        ref.item_id,
        "correct",
        "Reviewer",
        version,
        "replay",
        "7",
        duplicate_confirmation=token,
    )
    assert (
        replayed["replayed"] and replayed["decision"]["id"] == first["decision"]["id"]
    )
    assert len(current(service, 1)[3]["dwelling_no"]["review"]["history"]) == 1


def test_stale_confirmation_and_failed_save_are_atomic(tmp_path, monkeypatch):
    service = start(tmp_path)
    ref = ref_for(service, 1, "dwelling_no")
    version = service.store.regions["demo"][1]
    token = preview(service, ref.item_id, "correct", "7", version)[
        "duplicate_confirmation"
    ]
    correct(service, 2, "garden", "2", "other")
    with pytest.raises(ReviewError, match="Region changed"):
        service.apply_decision(
            ref.item_id,
            "correct",
            "Reviewer",
            version,
            "stale",
            "7",
            duplicate_confirmation=token,
        )
    import survey.records

    before = (service.store.directory / "demo.jsonl").read_bytes()
    monkeypatch.setattr(
        survey.records,
        "write_atomic",
        lambda *args: (_ for _ in ()).throw(OSError("failed")),
    )
    with pytest.raises(ReviewError, match="previous local data retained"):
        correct(service, 1, "dwelling_no", "7", "failure")
    assert (service.store.directory / "demo.jsonl").read_bytes() == before
    assert current(service, 1)[3]["dwelling_no"]["value"] == "6"


def test_later_independent_household_number_survives_structural_undo(tmp_path):
    service = start(tmp_path)
    saved = correct(service, 1, "dwelling_no", "7")
    correct(service, 1, "household_no", "3", "household")
    undo(service, saved)
    assert current(service, 1)[3]["record_id"] == "27-0006-03"


def test_missing_per_card_fields_are_not_borrowed(tmp_path):
    record = raw_record(1, rooms="6")
    record["dwelling"]["households"].append(
        raw_record(2, rooms="7")["dwelling"]["households"][0]
    )
    prepared, report = prepare_records([record])
    second = prepared[0]["dwelling"]["households"][1]
    assert second["house"]["total_number_of_rooms"]["status"] == "omitted"
    assert second["dwelling_no"]["value"] is None
    assert "missing_card_reading" in second["flags"]
    assert len(report["missing_fields"]) == 21


def test_recovered_fields_use_own_primary_reading_and_no_borrowed_confidence(tmp_path):
    record = raw_record(1, rooms="6")
    record["dwelling"]["house"]["total_number_of_rooms"]["confidence"] = 0.98
    record["dwelling"]["households"].append(
        raw_record(2, rooms="7")["dwelling"]["households"][0]
    )
    rows, _ = prepare_records(
        [record],
        {
            ("demo", "synthetic.pdf", 2): {
                "fields": {"Number of Dwelling": "6", "Total Number of Rooms": "7"}
            }
        },
    )
    hs = rows[0]["dwelling"]["households"]
    assert hs[0]["house"]["total_number_of_rooms"]["confidence"] == 0.98
    assert hs[1]["house"]["total_number_of_rooms"]["value"] == "7"
    assert hs[1]["house"]["total_number_of_rooms"]["confidence"] is None


def test_wrong_membership_dependency_blocks_undo(tmp_path):
    service = start(tmp_path)
    saved = correct(service, 1, "dwelling_no", "7")
    cid = owner("demo", current(service, 2)[3])
    # Correct a third card into the affected destination, changing its membership.
    correct(service, 2, "dwelling_no", "7", "join")
    with pytest.raises(
        ReviewError, match="membership or supplementary ownership changed"
    ):
        undo(service, saved)
    assert cid in inventory(service.store.regions["demo"][0])


def test_undoing_intervening_move_makes_earlier_undo_eligible(tmp_path):
    service = start(tmp_path)
    first = correct(service, 1, "dwelling_no", "7")
    second = correct(service, 2, "dwelling_no", "7", "join")
    with pytest.raises(ReviewError, match="membership"):
        undo(service, first, "too-early")
    undo(service, second, "undo-second")
    undo(service, first, "undo-first")
    assert current(service, 1)[3]["dwelling_no"]["value"] == "6"


def test_stale_undo_reload_and_retry_and_changed_bundle(tmp_path):
    service = start(
        tmp_path,
        [with_front(raw_record(1), 2, "6"), with_front(raw_record(3, "7"), 4, "7")],
    )
    correct(service, 1, "dwelling_no", "7")
    cid, tid = (owner("demo", current(service, p)[3]) for p in (1, 3))
    version = service.store.regions["demo"][1]
    saved = link(service, cid, tid, True, "Reviewer", version, "link")
    stale = service.store.regions["demo"][1]
    correct(service, 3, "garden", "3", "other")
    with pytest.raises(ReviewError, match="Region changed"):
        service.undo_latest(saved["decision"]["id"], "Reviewer", stale, "stale-undo")
    service = restart(service)
    undo_version = service.store.regions["demo"][1]
    result = service.undo_latest(
        saved["decision"]["id"], "Reviewer", undo_version, "undo-link"
    )
    service = restart(service)
    replayed = service.undo_latest(
        saved["decision"]["id"], "Reviewer", undo_version, "undo-link"
    )
    assert (
        replayed["replayed"] and replayed["decision"]["id"] == result["decision"]["id"]
    )
    assert current(service, 3)[3]["house"]["garden"]["value"] == "3"


def test_retained_field_history_is_preserved_suspended_and_restored(tmp_path):
    service = start(
        tmp_path,
        [with_front(raw_record(1), 2, "6"), with_front(raw_record(3, "7"), 4, "7")],
    )
    address_ref = Reference("demo", "synthetic.pdf", 2, "/dwelling/address")
    service.replace_queue([*service.assignment_references, address_ref], [])
    address_saved = service.apply_decision(
        address_ref.item_id,
        "correct",
        "Reviewer",
        service.store.regions["demo"][1],
        "address",
        "Human corrected address",
    )
    correct(service, 1, "dwelling_no", "7")
    cid, tid = (owner("demo", current(service, p)[3]) for p in (1, 3))
    saved = link(
        service, cid, tid, True, "Reviewer", service.store.regions["demo"][1], "link"
    )
    assert address_ref.item_id not in service.references
    service = restart(service)
    assert address_saved["decision"]["id"] in service.decisions
    with pytest.raises(ReviewError, match="Restore the retained evidence"):
        undo(service, address_saved, "retained-field")
    undo(service, saved)
    assert address_ref.item_id in service.references
    assert (
        service.item(address_ref.item_id)["field"]["value"] == "Human corrected address"
    )


def test_link_request_replay_does_not_duplicate_retained_bundle(tmp_path):
    service = start(
        tmp_path,
        [with_front(raw_record(1), 2, "6"), with_front(raw_record(3, "7"), 4, "7")],
    )
    correct(service, 1, "dwelling_no", "7")
    cid, tid = (owner("demo", current(service, p)[3]) for p in (1, 3))
    version = service.store.regions["demo"][1]
    first = link(service, cid, tid, True, "Reviewer", version, "link")
    service = restart(service)
    second = link(service, cid, tid, True, "Reviewer", version, "link")
    assert second["replayed"] and second["decision"]["id"] == first["decision"]["id"]
    assert len(current(service, 1)[3]["retained_supplements"]) == 1
    with pytest.raises(ReviewError, match="different input"):
        link(service, cid, None, True, "Reviewer", version, "link")


def test_preparation_refuses_review_history_and_is_deterministic(tmp_path):
    original = raw_record(1)
    original["dwelling"]["dwelling_no"].update(origin="corrected", original_value="5")
    first, receipt = prepare_records([original])
    second, repeated = prepare_records([original])
    assert first == second and receipt == repeated and receipt["protected_fields"] == 1
    assert original["schema_version"] == "0.6.0"
    original["dwelling"]["dwelling_no"]["review"] = {
        "state": "corrected",
        "history": [],
    }
    with pytest.raises(ValueError, match="review history"):
        prepare_records([original])


def test_corpus_independent_room_readings_and_protected_mapping():
    from pathlib import Path

    root = Path(__file__).parents[1]
    row = json.loads((root / "results/216421.jsonl").read_text().splitlines()[40])
    pdf = row["dwelling"]["households"][1]["cards"][0]["image"]
    rows, report = prepare_records(
        [row],
        {
            ("216421", pdf, 175): {
                "fields": {
                    "Number of Dwelling": "56",
                    "Total Number of Rooms": "7",
                    "Garden": "3",
                    "Structural Material": "2",
                }
            }
        },
    )
    hs = rows[0]["dwelling"]["households"]
    assert hs[0]["house"]["total_number_of_rooms"]["value"] == "6"
    assert hs[1]["house"]["total_number_of_rooms"]["value"] == "7"
    assert report["preserved_fields"]


@pytest.fixture
def prepared_api(tmp_path):
    from fastapi.testclient import TestClient
    from review_support import git

    from survey.review.api import Settings, create_app

    service = start(tmp_path)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    service.store.directory.rename(checkout / "results")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    git(checkout, "init", "-b", "review-data")
    git(checkout, "config", "user.name", "Test")
    git(checkout, "config", "user.email", "test@example.invalid")
    git(checkout, "add", "results")
    git(checkout, "commit", "-m", "Synthetic prepared seed")
    git(checkout, "remote", "add", "origin", str(remote))
    git(checkout, "push", "-u", "origin", "review-data")
    ref = ref_for(service, 1, "dwelling_no")
    flags = tmp_path / "flags.jsonl"
    flags.write_text(
        json.dumps(
            {
                "region": ref.region,
                "pdf": ref.pdf,
                "page": ref.page,
                "field_path": ref.field_path,
            }
        )
        + "\n"
    )
    settings = Settings(
        tmp_path / "scans", checkout, flags, tmp_path / "cache", sync_interval=3600
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/health").json()["ready"]
        yield client, settings


def test_http_duplicate_confirmation_unqueued_peer_edit_and_progress(prepared_api):
    client, _ = prepared_api
    item = client.get("/api/queue").json()["items"][0]
    body = {"action": "correct", "value": "7", "expected_version": item["version"]}
    path = f"/api/review-items/{item['id']}"
    assert client.post(path + "/preview", json=body).status_code == 401
    client.post("/api/session", json={"name": "Reviewer"})
    analysis = client.post(path + "/preview", json=body).json()
    assert analysis["duplicate_confirmation"]
    assert (
        client.post(path + "/decisions", json={**body, "request_id": "reject"}).json()[
            "error"
        ]["code"]
        == "duplicate_confirmation_required"
    )
    saved = client.post(
        path + "/decisions",
        json={
            **body,
            "request_id": "save",
            "duplicate_confirmation": analysis["duplicate_confirmation"],
        },
    )
    assert saved.status_code == 200, saved.text
    peer = saved.json()["item"]["duplicate_peers"][0]
    context = client.get(f"/api/cards/{peer['card_id']}").json()
    assert client.get(peer["scan_url"]).status_code == 200
    fix = next(
        f for f in context["fields"] if f["field_path"].endswith("/household_no")
    )
    volunteered = client.get(f"/api/review-items/{fix['id']}").json()
    assert volunteered["assigned"] is False
    corrected = client.post(
        f"/api/review-items/{fix['id']}/decisions",
        json={
            "action": "correct",
            "value": "3",
            "request_id": "voluntary",
            "expected_version": volunteered["version"],
        },
    )
    assert corrected.status_code == 200, corrected.text
    queue = client.get("/api/dwellings?region=demo").json()
    assert queue["total"] == 1 and queue["complete"]
    assert queue["association_summary"]["duplicate_cards"] == 0


def test_normal_http_app_requires_prepared_data(tmp_path):
    from fastapi.testclient import TestClient
    from review_support import setup_review

    from survey.review.api import create_app

    _, settings = setup_review(tmp_path, with_git=True)
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        assert (
            client.get("/api/health").json()["diagnostics"][0]["code"]
            == "review_preparation_required"
        )


def test_staging_is_deterministic_pins_evidence_and_preserves_inputs(tmp_path):
    from survey.review.prepare import prepare_dataset

    record = raw_record(1, rooms="6")
    record["dwelling"]["households"].append(
        raw_record(2, rooms="7")["dwelling"]["households"][0]
    )
    source = tmp_path / "published"
    source.mkdir()
    original = json.dumps(record) + "\n"
    (source / "demo.jsonl").write_text(original)
    cache = tmp_path / "cache" / "demo" / "gemini-3.5-flash-lite"
    cache.mkdir(parents=True)
    (cache / "synthetic_p0002.json").write_text(
        json.dumps(
            {"fields": {"Number of Dwelling": "6", "Total Number of Rooms": "7"}}
        )
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            [
                {
                    "region": "demo",
                    "pdf": "synthetic.pdf",
                    "page": 2,
                    "fields": {
                        "Total Number of Rooms": {"value": "7", "confidence": 0.75}
                    },
                }
            ]
        )
    )
    a, b = tmp_path / "stage-a", tmp_path / "stage-b"
    first = prepare_dataset(source, a, tmp_path / "cache", evidence)
    repeated = prepare_dataset(source, b, tmp_path / "cache", evidence)
    assert first == repeated and first["field_evidence_sha256"]
    assert (a / "demo.jsonl").read_bytes() == (b / "demo.jsonl").read_bytes()
    assert (source / "demo.jsonl").read_text() == original
    rows = RecordStore(a).regions["demo"][0]
    assert (
        rows[0]["dwelling"]["households"][1]["house"]["total_number_of_rooms"][
            "confidence"
        ]
        == 0.75
    )
    with pytest.raises(ValueError, match="separate"):
        prepare_dataset(source, source / "nested")
    with pytest.raises(ValueError, match="new or empty"):
        prepare_dataset(source, a)


def test_every_published_corrected_mapping_is_preserved():
    from pathlib import Path

    from survey.records import current_fields

    root = Path(__file__).parents[1]
    protected = []
    for path in sorted((root / "results").glob("*.jsonl")):
        protected.extend(
            row
            for line in path.read_text().splitlines()
            if line
            for row in [json.loads(line)]
            if any(f.get("origin") == "corrected" for _, f in current_fields(row))
        )
    _, receipt = prepare_records(protected)
    assert receipt["protected_fields"] == 34


def test_changed_retained_bundle_refuses_unsafe_undo(tmp_path):
    source = with_front(raw_record(1), 2, "6")
    service = start(tmp_path, [source, with_front(raw_record(3, "7"), 4, "7")])
    correct(service, 1, "dwelling_no", "7")
    cid, tid = (owner("demo", current(service, p)[3]) for p in (1, 3))
    saved = link(
        service, cid, tid, True, "Reviewer", service.store.regions["demo"][1], "link"
    )
    rows = deepcopy(service.store.regions["demo"][0])
    inventory(rows)[cid][3]["retained_supplements"][0]["payload"]["address"][
        "value"
    ] = "Changed by another writer"
    service.store.save("demo", service.store.regions["demo"][1], rows)
    service.reindex_history({"demo"})
    with pytest.raises(ReviewError, match="bundle is missing or changed"):
        undo(service, saved)


def test_departing_card_cannot_leave_its_owned_note_in_a_multi_card_group(tmp_path):
    source = with_front(raw_record(1), 4, "6")
    second = raw_record(2, household="2")["dwelling"]["households"][0]
    source["dwelling"]["households"].append(second)
    source["dwelling"]["notes"] = [
        {
            "front_page": 4,
            "page": None,
            "household_id": "27-0006-01",
            "text": {
                "value": "Owned note",
                "status": "ok",
                "confidence": None,
                "source": "survey-back",
            },
        }
    ]
    service = start(tmp_path, [source, with_front(raw_record(3, "7"), 5, "7")])
    saved = correct(service, 1, "dwelling_no", "7")
    assert saved["membership"]["outcome"] == "notes_pending"
    assert len(current(service, 1)[2]["dwelling"]["households"]) == 2
    cid, tid = (owner("demo", current(service, p)[3]) for p in (1, 3))
    with pytest.raises(ReviewError, match="source note explicitly belongs"):
        link(
            service,
            cid,
            tid,
            True,
            "Reviewer",
            service.store.regions["demo"][1],
            "unsafe",
        )


def test_region_refresh_does_not_resolve_unaffected_assignments(tmp_path, monkeypatch):
    service = start(tmp_path)
    rows, _ = prepare_records([raw_record(1)])
    rows[0]["region"] = "other"
    # Physical IDs are region-scoped; derive flags in this independent region.
    from survey.review.relinking import refresh_identities

    refresh_identities(rows)
    (service.store.directory / "other.jsonl").write_text(json.dumps(rows[0]) + "\n")
    service.store.reload()
    other = Reference("other", "synthetic.pdf", 1, "/dwelling/households/0/dwelling_no")
    service.replace_queue([*service.assignment_references, other], [])
    original = service.store.current

    def scoped(ref):
        assert ref.region != "other", (
            "Unchanged regional assignment was unnecessarily resolved"
        )
        return original(ref)

    monkeypatch.setattr(service.store, "current", scoped)
    service.reindex_history({"demo"})
    assert other.item_id in service.references


def test_primary_alias_recovery_uses_saved_reply_without_extraction():
    record = raw_record(1)
    record["dwelling"]["households"].append(raw_record(2)["dwelling"]["households"][0])
    rows, _ = prepare_records(
        [record],
        {
            ("demo", "synthetic.pdf", 2): {
                "fields": {"Number of Dwelling": "6"},
                "raw_text": '{"Washhouse": "2"}',
            }
        },
    )
    assert rows[0]["dwelling"]["households"][1]["house"]["washouse"]["value"] == "2"


def test_preparation_has_no_pipeline_model_or_scoring_dependency(monkeypatch):
    import sys

    for module in (
        "survey.pipeline",
        "survey.merge_runs",
        "survey.extraction.gemini",
        "survey.extraction.qwen",
        "survey.extraction.qwen_server",
    ):
        monkeypatch.setitem(sys.modules, module, None)
    rows, _ = prepare_records([raw_record(1)])
    assert rows[0]["schema_version"] == "0.7.0"


def test_later_explicit_provisional_link_blocks_prior_automatic_undo(tmp_path):
    source = raw_record(1)
    source["dwelling"]["households"].append(
        raw_record(2, household="2")["dwelling"]["households"][0]
    )
    service = start(tmp_path, [source, with_front(raw_record(3, "7"), 4, "7")])
    # No matching dwelling 8 exists: split this card to a provisional group.
    saved = correct(service, 1, "dwelling_no", "8")
    assert saved["structural_change"]
    cid = owner("demo", current(service, 1)[3])
    later = link(
        service,
        cid,
        None,
        False,
        "Reviewer",
        service.store.regions["demo"][1],
        "provisional",
    )
    with pytest.raises(ReviewError, match="later link decision"):
        undo(service, saved, "before-later-link")
    undo(service, later, "undo-later-link")
    undo(service, saved, "undo-first")
    assert current(service, 1)[3]["dwelling_no"]["value"] == "6"

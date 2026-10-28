"""Established front fields and IT-89 physical note ownership, without extraction."""

from copy import deepcopy
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from review_support import decide, refs, setup_review, write_record

from survey.pipeline import MergeRefused, _keep_corrections
from survey.records import RecordStore, Reference, ReviewError, schema_errors
from survey.review.api import create_app
from survey.review.service import ReviewService

FRONT = Reference("demo", "synthetic.pdf", 3, "/dwelling/address")
NOTE = Reference("demo", "synthetic.pdf", 4, "/dwelling/notes/0/text")
TEXT = "  Café — 王\nSecond line: 009\n"


def text_service(tmp_path, transform=lambda record: None):
    service, settings = setup_review(tmp_path)
    record = deepcopy(service.store.regions["demo"][0][0])
    transform(record)
    write_record(service.store.directory / "demo.jsonl", record)
    service = ReviewService(
        RecordStore(service.store.directory), [*refs(), FRONT, NOTE], [], service.scans
    )
    return service, settings


def note_ref(service):
    return next(
        ref
        for ref in service.references.values()
        if ref.field_path.startswith("/dwelling/notes/")
    )


@pytest.mark.parametrize("source", ["front", "note"])
@pytest.mark.parametrize("action", ["accept", "correct", "no_data", "illegible"])
def test_text_decisions_restart_replay_stale_undo(tmp_path, source, action):
    service, _ = text_service(tmp_path)
    ref = FRONT if source == "front" else note_ref(service)
    original = deepcopy(service.item(ref.item_id)["field"])
    version = service.item(ref.item_id)["version"]
    saved = decide(service, ref, action, TEXT, version=version)
    field = saved["item"]["field"]
    if action == "correct":
        assert (
            field["value"] == TEXT and field["code"] is None and field["label"] is None
        )
        assert field["original_value"] == original["value"]
    if action == "accept":
        assert {k: v for k, v in field.items() if k != "review"} == original
    if action in {"no_data", "illegible"}:
        assert field["value"] is None and field["status"] == action
    assert (
        field["confidence"] == original["confidence"]
        and field["source"] == original["source"]
    )
    restarted = ReviewService(
        RecordStore(service.store.directory),
        list(service.references.values()),
        [],
        service.scans,
    )
    assert decide(restarted, ref, action, TEXT, version=version)["replayed"]
    with pytest.raises(ReviewError, match="Region changed"):
        decide(restarted, ref, "correct", TEXT, request_id="stale", version=version)
    undone = restarted.undo_latest(
        saved["decision"]["id"], "Test Reviewer", saved["item"]["version"], "undo"
    )
    assert {
        k: v for k, v in undone["item"]["field"].items() if k != "review"
    } == original
    assert undone["item"]["review_state"] == "pending"
    assert len(undone["item"]["field"]["review"]["history"]) == 2


@pytest.mark.parametrize("source", [FRONT, NOTE, refs()[0]])
def test_damaged_accept_preserves_and_illegible_is_explicit(tmp_path, source):
    def damage(record):
        node = record
        for part in source.field_path.split("/")[1:]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        node.update(status="damaged", value=None)

    service, _ = text_service(tmp_path, damage)
    ref = note_ref(service) if source == NOTE else source
    accepted = decide(service, ref, "accept")
    assert accepted["item"]["field"]["status"] == "damaged"
    illegible = decide(service, ref, "illegible", request_id="illegible")
    assert illegible["item"]["field"]["status"] == "illegible"
    with pytest.raises(ReviewError):
        decide(service, ref, "damaged", request_id="unsupported")


def add_second_front(record):
    d = record["dwelling"]
    d["cards"] += [
        {"role": "survey-front", "image": "synthetic.pdf", "page": 5},
        {"role": "survey-back", "image": "synthetic.pdf", "page": 6},
    ]
    other = deepcopy(d["notes"][0])
    other.update(front_page=5, page=6)
    other["text"]["value"] = "Another note"
    d["notes"].append(other)


def test_note_reorder_stable_identity_and_stale_pointer_never_redirects(tmp_path):
    service, _ = text_service(tmp_path, add_second_front)
    ref = note_ref(service)
    saved = decide(service, ref, value=TEXT)
    record = deepcopy(service.store.regions["demo"][0][0])
    record["dwelling"]["notes"].reverse()
    write_record(service.store.directory / "demo.jsonl", record)
    restarted = ReviewService(
        RecordStore(service.store.directory), [ref], [], service.scans
    )
    assert not restarted.references
    assert restarted.diagnostics[0]["code"] == "stale_pointer"
    fresh = replace(NOTE, field_path="/dwelling/notes/1/text")
    restarted.replace_queue([fresh], [])
    rebound = note_ref(restarted)
    assert rebound.item_id == ref.item_id
    assert restarted.item(rebound.item_id)["field"]["value"] == TEXT
    assert (
        restarted.undo_latest(
            saved["decision"]["id"],
            "Test Reviewer",
            restarted.item(ref.item_id)["version"],
            "undo",
        )["item"]["field"]["value"]
        == "Synthetic reverse notes"
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r["dwelling"]["cards"].pop(),
        lambda r: r["dwelling"]["notes"][0].update(page=None),
        lambda r: r["dwelling"]["notes"][0].update(front_page=99),
        lambda r: r["dwelling"]["notes"].append(deepcopy(r["dwelling"]["notes"][0])),
        lambda r: r["dwelling"]["notes"][0]["text"].pop("source"),
    ],
)
def test_unverified_notes_are_unresolved_and_bytes_unchanged(tmp_path, change):
    service, _ = text_service(tmp_path, change)
    path = service.store.directory / "demo.jsonl"
    before = path.read_bytes()
    assert not any(
        ref.field_path.startswith("/dwelling/notes/")
        for ref in service.references.values()
    )
    assert service.diagnostics
    with pytest.raises(ReviewError):
        decide(service, NOTE, value=TEXT)
    assert path.read_bytes() == before
    assert not service.dwellings("demo")["complete"]


def test_ambiguous_front_and_person_grid_stay_unresolved(tmp_path):
    service, _ = text_service(tmp_path, add_second_front)
    assert FRONT.item_id not in service.references
    assert any(d["code"] == "ambiguous_source" for d in service.diagnostics)
    assert note_ref(service)  # multiple households do not prevent dwelling notes
    person = replace(FRONT, field_path="/dwelling/households/1/persons/0/relationship")
    service.replace_queue([person], [])
    assert service.diagnostics[0]["code"] == "unsupported_field"
    assert not service.references


def test_front_identity_editable_and_negated_text_accept_only(tmp_path):
    def setup(record):
        record["dwelling"]["handwritten"]["dwelling_no"] = {
            "value": "006",
            "status": "ok",
            "confidence": None,
            "source": "survey-front",
        }
        record["dwelling"]["address"]["negated"] = True

    service, _ = text_service(tmp_path, setup)
    identity = replace(FRONT, field_path="/dwelling/handwritten/dwelling_no")
    service.replace_queue([identity, FRONT], [])
    corrected = decide(service, identity, value="006B")
    assert corrected["item"]["field"]["value"] == "006B"
    assert corrected["item"]["allowed_actions"] == [
        "accept",
        "correct",
        "no_data",
        "illegible",
    ]
    for ref in [FRONT]:
        assert service.item(ref.item_id)["allowed_actions"] == ["accept"]
        before = (service.store.directory / "demo.jsonl").read_bytes()
        with pytest.raises(ReviewError):
            decide(service, ref, value=TEXT)
        assert (service.store.directory / "demo.jsonl").read_bytes() == before


def test_text_invalid_and_scan_failure_leave_bytes_unchanged(tmp_path, monkeypatch):
    service, _ = text_service(tmp_path)
    before = (service.store.directory / "demo.jsonl").read_bytes()
    for value in ["", " \n", None, 12]:
        with pytest.raises(ReviewError):
            decide(service, FRONT, value=value)
    monkeypatch.setattr(
        service.scans,
        "get_scan",
        lambda ref: (_ for _ in ()).throw(ReviewError("scan_failed", "Cannot decode")),
    )
    with pytest.raises(ReviewError, match="Cannot decode"):
        decide(service, FRONT, value=TEXT)
    assert (service.store.directory / "demo.jsonl").read_bytes() == before


def test_rerun_review_protection_and_front_ownership_guard(tmp_path):
    service, _ = text_service(tmp_path)
    decide(service, FRONT, value=TEXT)
    decide(service, note_ref(service), value=TEXT, request_id="note")
    old = deepcopy(service.store.regions["demo"][0][0])
    new = deepcopy(old)
    for node in [new["dwelling"]["address"], new["dwelling"]["notes"][0]["text"]]:
        node.pop("review")
        node["value"] = "Fresh reading"
    _keep_corrections(old, new)
    assert new["dwelling"]["address"] == old["dwelling"]["address"]
    assert new["dwelling"]["notes"][0]["text"] == old["dwelling"]["notes"][0]["text"]
    add_second_front(new)
    with pytest.raises(MergeRefused):
        _keep_corrections(old, new)


def test_schema_05_contract_and_review_preserves_version(tmp_path):
    def corpus(record):
        record["schema_version"] = "0.5.0"
        record["dwelling"]["flags"] = ["missing_record_id"]
        record["dwelling"]["households"][0]["record_id"] = None
        record["dwelling"]["households"][1]["record_id"] = "27-0006A-02"

    service, _ = text_service(tmp_path, corpus)
    decide(service, FRONT, value=TEXT)
    record = service.store.regions["demo"][0][0]
    assert record["schema_version"] == "0.5.0" and not schema_errors(record)
    old = deepcopy(record)
    old["schema_version"] = "0.4.0"
    assert schema_errors(old)
    record["dwelling"]["households"][0]["notes"] = {"text": "legacy"}
    assert schema_errors(record)


def test_api_notes_dwelling_navigation_and_scan_gate(tmp_path):
    _service, settings = setup_review(tmp_path, with_git=True)
    settings.flags.write_text(
        '{"region":"demo","pdf":"synthetic.pdf","page":4,"field_path":"/dwelling/notes/0/text"}\n'
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        client.post("/api/session", json={"name": "Text Reviewer"})
        queue = client.get("/api/queue").json()
        item = queue["items"][0]
        assert item["field_kind"] == "text" and item["record_id"] is None
        detail = client.get("/api/review-items/" + item["id"]).json()
        assert any(
            c["role"] == "survey-back" and c["first_item_id"] == item["id"]
            for c in detail["cards"]
        )
        assert client.get(item["scan_url"]).status_code == 200
        assert (
            client.get(
                "/api/dwellings/" + item["dwelling_id"] + "/items?region=demo"
            ).status_code
            == 200
        )
        response = client.post(
            "/api/review-items/" + item["id"] + "/decisions",
            json={
                "action": "correct",
                "value": TEXT,
                "expected_version": item["version"],
                "request_id": "api-text",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["item"]["field"]["value"] == TEXT


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r["dwelling"]["notes"][0].update(page=6),
        lambda r: r["dwelling"]["cards"][0].update(image="changed.pdf"),
        lambda r: r["dwelling"]["notes"].append(deepcopy(r["dwelling"]["notes"][0])),
    ],
)
def test_reviewed_note_rerun_refuses_changed_or_ambiguous_provenance(tmp_path, change):
    service, _ = text_service(tmp_path)
    decide(service, note_ref(service), value=TEXT)
    old = deepcopy(service.store.regions["demo"][0][0])
    new = deepcopy(old)
    change(new)
    with pytest.raises(MergeRefused):
        _keep_corrections(old, new)


def test_reviewed_note_rerun_follows_front_when_another_front_is_added(tmp_path):
    service, _ = text_service(tmp_path)
    decide(service, note_ref(service), value=TEXT)
    old = deepcopy(service.store.regions["demo"][0][0])
    new = deepcopy(old)
    add_second_front(new)
    new["dwelling"]["notes"].reverse()
    new["dwelling"]["notes"][1]["text"].pop("review")
    new["dwelling"]["notes"][1]["text"]["value"] = "New extraction"
    _keep_corrections(old, new)
    assert new["dwelling"]["notes"][1]["text"] == old["dwelling"]["notes"][0]["text"]


def test_note_with_out_of_bounds_front_cannot_be_decided(tmp_path):
    def invalid_front(record):
        record["dwelling"]["cards"][0]["page"] = 99
        record["dwelling"]["notes"][0]["front_page"] = 99

    service, _ = text_service(tmp_path, invalid_front)
    ref = note_ref(service)
    before = (service.store.directory / "demo.jsonl").read_bytes()
    assert service.item(ref.item_id)["allowed_actions"] == []
    with pytest.raises(ReviewError):
        decide(service, ref, value=TEXT)
    assert (service.store.directory / "demo.jsonl").read_bytes() == before


@pytest.mark.parametrize("restart", [False, True])
def test_reviewed_note_progress_requires_readable_front(tmp_path, restart):
    service, settings = text_service(tmp_path)
    ref = note_ref(service)
    service.replace_queue([ref], [])
    decide(service, ref, value=TEXT)
    assert service.batch_complete(ref.region, ref.pdf)
    saved = (service.store.directory / "demo.jsonl").read_bytes()

    pdf = settings.scan_root / ref.region / ref.pdf
    original = pdf.read_bytes()
    reader, writer = PdfReader(pdf), PdfWriter()
    for page_number, page in enumerate(reader.pages, 1):
        if page_number == ref.front_page:
            writer.add_blank_page(
                width=float(page.mediabox.width), height=float(page.mediabox.height)
            )
        else:
            writer.add_page(page)
    replacement = tmp_path / "unreadable-front.pdf"
    writer.write(replacement)
    replacement.replace(pdf)

    if restart:
        service = ReviewService(
            RecordStore(service.store.directory), [ref], [], service.scans
        )
    assert not service.batch_complete(ref.region, ref.pdf)
    queue = service.dwellings(ref.region)
    assert queue["dwellings"][0]["status"] == "blocked"
    assert queue["resolved"] == 0
    assert queue["diagnostics"][0]["code"] == "unreadable_scan"
    assert not service.item(ref.item_id)["resolved"]
    assert (service.store.directory / "demo.jsonl").read_bytes() == saved

    pdf.write_bytes(original)
    assert service.batch_complete(ref.region, ref.pdf)
    assert service.dwellings(ref.region)["dwellings"][0]["status"] == "complete"
    assert service.item(ref.item_id)["field"]["value"] == TEXT


@pytest.mark.parametrize("page", [3, 4, 99])
def test_front_note_diagnostics_block_only_their_dwelling(tmp_path, page):
    service, _ = text_service(tmp_path)
    service.replace_queue([refs()[0]], [])
    decide(service, refs()[0], "accept")
    service.diagnostics = [
        {
            "region": "demo",
            "batch": "synthetic.pdf",
            "page": page,
            "code": "test_block",
            "message": "Source needs reconciliation",
        }
    ]
    queue = service.dwellings("demo")
    blocked = page in {3, 4}
    assert (queue["dwellings"][0]["status"] == "blocked") == blocked
    assert queue["summary"]["completed_dwellings"] == (0 if blocked else 1)
    assert queue["all_regions"]["completed_dwellings"] == (0 if blocked else 1)


@pytest.mark.parametrize("ref", [FRONT, NOTE])
@pytest.mark.parametrize("value", ["x" * 10_001, "text\x00text"])
def test_text_limits_reject_without_writing(tmp_path, ref, value):
    service, _ = text_service(tmp_path)
    ref = note_ref(service) if ref == NOTE else ref
    path = service.store.directory / "demo.jsonl"
    before = path.read_bytes()
    with pytest.raises(ReviewError):
        decide(service, ref, value=value)
    assert path.read_bytes() == before


@pytest.mark.parametrize("ref", [FRONT, NOTE])
def test_text_limit_unicode_boundary_survives_restart(tmp_path, ref):
    service, _ = text_service(tmp_path)
    ref = note_ref(service) if ref == NOTE else ref
    value = "王\n😀 " * 2500
    decide(service, ref, value=value)
    store = RecordStore(service.store.directory)
    assert store.current(ref)[0].field["value"] == value


@pytest.mark.parametrize("value", ["x" * 10_001, "text\x00text"])
def test_history_rejects_invalid_text_correction(tmp_path, value):
    from survey.records import validate_history
    from survey.review.fields import descriptor

    service, _ = text_service(tmp_path)
    saved = decide(service, FRONT, value=TEXT)
    field = deepcopy(saved["item"]["field"])
    event = field["review"]["history"][0]
    event["request"]["value"] = value
    event["after"]["value"] = field["value"] = value
    with pytest.raises(ReviewError, match="established field type"):
        validate_history(field, descriptor(FRONT.field_path))


def test_api_rejects_oversized_correction():
    from pydantic import ValidationError

    from survey.review.api import DecisionBody

    with pytest.raises(ValidationError):
        DecisionBody(
            action="correct",
            value="x" * 10_001,
            expected_version="v",
            request_id="too-long",
        )

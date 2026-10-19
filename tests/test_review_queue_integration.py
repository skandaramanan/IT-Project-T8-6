"""Generated assignments through HTTP review, persistence and local Git sharing.

Scored benchmark cards are adapted to D007 here, not by a production corpus
merger. Scan pages are synthetic evidence; no test certifies a transcription.
"""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from review_support import git, setup_review, synthetic_record, write_record

from dual_extract import pair_cards
from survey import cli
from survey.confidence.agreement import compare_fields
from survey.confidence.card import card_confidence
from survey.confidence.field import score_fields
from survey.extraction.card_fields import FIELD_SCHEMA
from survey.extraction.record import FIELD_MAP, build_record
from survey.records import current_fields, field_pointer
from survey.review.api import create_app

BASE = "http://127.0.0.1:8765"
MODELS = {"a": "gemini-3.5-flash-lite", "b": "qwen2.5-vl"}


def at(record, pointer):
    node = record
    for part in pointer.split("/")[1:]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def scored_record(scored, page=1):
    record = build_record(
        {name: field["value"] for name, field in scored.items()},
        region="demo",
        image="synthetic.pdf",
        page=page,
    )
    for name, field in scored.items():
        key, group = FIELD_MAP[name]
        at(record, field_pointer(key, group, 0))["confidence"] = field["confidence"]
    household = record["dwelling"]["households"][0]
    household["municipality"] = deepcopy(record["dwelling"]["municipality"])
    household["cards"][0]["confidence"] = card_confidence(
        field["confidence"] for field in scored.values()
    )
    return record


def generate(settings, capsys, target=None):
    assert cli.main(["flags", str(settings.data_checkout / "results")]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    (target or settings.flags).write_text(output.out, encoding="utf-8")
    return [json.loads(line) for line in output.out.splitlines()]


def prepare(tmp_path, capsys, record):
    _, settings = setup_review(tmp_path, with_git=True)
    write_record(settings.data_checkout / "results/demo.jsonl", record)
    git(settings.data_checkout, "add", "results/demo.jsonl")
    git(settings.data_checkout, "commit", "--allow-empty", "-m", "Seed scored cards")
    git(settings.data_checkout, "push", "origin", "review-data")
    flags = generate(settings, capsys)
    return settings, flags


@pytest.fixture
def assignment(tmp_path, capsys):
    # Two complete synthetic extractor readings, not manually assigned scores.
    first = {spec.name: "1" for spec in FIELD_SCHEMA} | {
        "Municipality": "27",
        "Number of Dwelling": "6",
        "Number of Household": "1",
        "Weekly Rent": "04",
        "Age of Head": "",
        "Sex of Head": "",
    }
    second = first | {"Weekly Rent": "05", "Sex of Head": "1", "Garden": "2"}
    raw_root = tmp_path / "raw-readings"
    for arm, fields in (("a", first), ("b", second)):
        raw = raw_root / MODELS[arm] / "raw"
        raw.mkdir(parents=True)
        (raw / "synthetic.txt").write_text(json.dumps(fields), encoding="utf-8")
    paired = pair_cards(MODELS["a"], MODELS["b"], raw_root)[0]
    record = scored_record(paired["scored"])
    context = synthetic_record()["dwelling"]
    for key in ("cards", "address", "handwritten", "notes"):
        record["dwelling"][key] = deepcopy(context[key])
    other_first = first | {"Number of Household": "2", "Age of Head": "50"}
    other_second = other_first | {"Weekly Rent": "12", "Municipality": "28"}
    other = scored_record(
        score_fields(compare_fields(other_first, other_second), MODELS), page=2
    )
    record["dwelling"]["households"].append(other["dwelling"]["households"][0])
    settings, flags = prepare(tmp_path, capsys, record)
    assert len(flags) == 7
    return settings, flags


def sign_in(client):
    assert (
        client.post("/api/session", json={"name": "Queue Reviewer"}).status_code == 200
    )


def decide(client, item, action, request_id):
    body = {
        "action": action,
        "expected_version": item["version"],
        "request_id": request_id,
    }
    if action == "correct":
        body["value"] = "009"
    response = client.post(f"/api/review-items/{item['id']}/decisions", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_generated_assignment_navigation_decisions_restart_undo_and_share(
    assignment, tmp_path, capsys
):
    settings, flags = assignment
    original_flags = settings.flags.read_bytes()
    with TestClient(create_app(settings), base_url=BASE) as client:
        assert client.get("/api/health").json()["ready"]
        sign_in(client)
        queue = client.get("/api/queue").json()
        assert queue["diagnostics"] == []
        assert [i["field_path"] for i in queue["items"]] == [
            f["field_path"] for f in flags
        ]
        summary = client.get("/api/dwellings?region=demo").json()
        dwelling_id = summary["dwellings"][0]["id"]
        items = client.get(f"/api/dwellings/{dwelling_id}/items?region=demo").json()
        assert {i["id"] for i in items["items"]} == {i["id"] for i in queue["items"]}
        assert [i["label"] for i in items["items"]] == [
            "Weekly Rent",
            "Age of Head",
            "Sex of Head",
            "Garden",
            "Municipality",
            "Weekly Rent",
            "Sex of Head",
        ]
        # Shared building fields have one owner; later municipality has its own.
        assert sum(i["label"] == "Garden" for i in items["items"]) == 1
        assert (
            next(i for i in items["items"] if i["label"] == "Municipality")[
                "field_path"
            ]
            == "/dwelling/households/1/municipality"
        )
        original_confidence = items["items"][0]["field"]["confidence"]
        saved = []
        for position, action in enumerate(
            ("correct", "accept", "no_data", "illegible")
        ):
            item = client.get(
                f"/api/review-items/{items['items'][position]['id']}"
            ).json()
            assert client.get(item["scan_url"]).status_code == 200
            saved.append(decide(client, item, action, f"decision-{position}"))
            progress = client.get("/api/dwellings?region=demo").json()
            assert (progress["total"], progress["resolved"]) == (
                len(flags),
                position + 1,
            )
        corrected = saved[0]
        # Repeating an uncertain request replays exactly one audit event.
        replay = decide(client, items["items"][0], "correct", "decision-0")
        assert replay["replayed"]
        assert len(replay["item"]["field"]["review"]["history"]) == 1
        assert corrected["item"]["field"]["value"] == "009"
        assert corrected["item"]["field"]["original_value"] == "04"
        assert corrected["item"]["field"]["confidence"] == original_confidence
        assert corrected["decision"]["reviewer"] == "Queue Reviewer"
        assert client.post("/api/sync", json={}).json()["state"] == "uploaded"
    assert settings.flags.read_bytes() == original_flags

    # Another checkout resumes from shared records with the original assignment.
    clone = tmp_path / "second checkout"
    git(
        tmp_path,
        "clone",
        "--branch",
        "review-data",
        str(tmp_path / "remote.git"),
        str(clone),
    )
    git(clone, "config", "user.name", "Second test reviewer")
    git(clone, "config", "user.email", "second@example.invalid")
    with TestClient(
        create_app(replace(settings, data_checkout=clone)), base_url=BASE
    ) as client:
        sign_in(client)
        assert client.get("/api/queue").json()["resolved"] == 4
        item = client.get(f"/api/review-items/{corrected['item']['id']}").json()
        assert item["review_state"] == "corrected"
        # Old editor versions cannot overwrite the shared decision.
        conflict = client.post(
            f"/api/review-items/{item['id']}/decisions",
            json={
                "action": "accept",
                "expected_version": items["items"][0]["version"],
                "request_id": "stale-editor",
            },
        )
        assert conflict.status_code == 409
        undo = client.post(
            f"/api/decisions/{corrected['decision']['id']}/undo",
            json={"expected_version": item["version"], "request_id": "undo-shared"},
        )
        assert undo.status_code == 200
        assert undo.json()["item"]["field"]["value"] == "04"
        assert undo.json()["item"]["review_state"] == "pending"
        assert len(undo.json()["item"]["field"]["review"]["history"]) == 2
        assert client.get("/api/queue").json()["resolved"] == 3
        assert client.post("/api/sync", json={}).json()["state"] == "uploaded"
    with TestClient(create_app(settings), base_url=BASE) as client:
        sign_in(client)
        assert client.post("/api/sync", json={}).json()["state"] == "uploaded"
        assert client.get("/api/dwellings?region=demo").json()["resolved"] == 3
    assert settings.flags.read_bytes() == original_flags
    regenerated = generate(settings, capsys, tmp_path / "new-assignment.jsonl")
    assert len(regenerated) == len(flags) - 3
    assert corrected["item"]["field_path"] in {f["field_path"] for f in regenerated}
    assert cli.main(["validate-results", str(settings.data_checkout / "results")]) == 0


def test_valid_empty_generated_assignment_is_ready(tmp_path, capsys):
    first = {spec.name: "1" for spec in FIELD_SCHEMA}
    record = scored_record(score_fields(compare_fields(first, first), MODELS))
    settings, flags = prepare(tmp_path, capsys, record)
    assert flags == []
    with TestClient(create_app(settings), base_url=BASE) as client:
        assert client.get("/api/health").json()["ready"]
        for route in ("/api/queue", "/api/dwellings?region=demo"):
            queue = client.get(route).json()
            assert queue["total"] == queue["resolved"] == queue["unresolved"] == 0
            assert not queue["complete"] and not queue["diagnostics"]


def test_generated_identity_warnings_with_nullable_display_id(tmp_path, capsys):
    fields = {spec.name: "1" for spec in FIELD_SCHEMA}
    record = scored_record(score_fields(compare_fields(fields, fields), MODELS))
    record["dwelling"]["flags"] = ["identity_reread"]
    record["dwelling"]["households"][0]["record_id"] = None
    settings, flags = prepare(tmp_path, capsys, record)
    assert {flag["field_path"] for flag in flags} == {
        "/dwelling/municipality",
        "/dwelling/dwelling_no",
        "/dwelling/households/0/household_no",
    }
    with TestClient(create_app(settings), base_url=BASE) as client:
        sign_in(client)
        summary = client.get("/api/dwellings?region=demo").json()
        assert summary["dwellings"][0]["record_id"] is None
        for queued in client.get("/api/queue").json()["items"]:
            item = client.get(f"/api/review-items/{queued['id']}").json()
            assert item["allowed_actions"] == ["accept"]
            assert item["dwelling_flags"] == ["identity_reread"]
            context = next(
                field
                for field in item["card_fields"]
                if field["field_path"] == item["field_path"]
            )
            assert context["id"] == item["id"]


def test_generated_assignment_without_scans_cannot_be_decided(assignment):
    settings, _ = assignment
    (settings.scan_root / "demo/synthetic.pdf").unlink()
    with TestClient(create_app(settings), base_url=BASE) as client:
        assert client.get("/api/health").json()["ready"]
        sign_in(client)
        item = client.get("/api/queue").json()["items"][0]
        assert item["diagnostics"] and not item["resolved"]
        before = (settings.data_checkout / "results/demo.jsonl").read_bytes()
        response = client.post(
            f"/api/review-items/{item['id']}/decisions",
            json={
                "action": "accept",
                "expected_version": item["version"],
                "request_id": "missing-scan",
            },
        )
        assert response.status_code == 404
        assert (settings.data_checkout / "results/demo.jsonl").read_bytes() == before
        assert not client.get("/api/dwellings?region=demo").json()["complete"]


def test_cached_real_dual_readings_generate_actionable_assignment(tmp_path, capsys):
    root = Path(__file__).parents[1] / "data/benchmark/results"
    available = [
        p.stem
        for p in sorted((root / MODELS["a"] / "raw").glob("*.txt"))
        if (root / MODELS["b"] / "raw" / p.name).is_file()
    ]
    if not available:
        pytest.skip("Optional real Gemini/Qwen benchmark readings are not installed")
    # The first common saved card is reproducible; never fetch model output.
    paired = pair_cards(MODELS["a"], MODELS["b"], root, page_ids=available[:1])[0]
    settings, flags = prepare(tmp_path, capsys, scored_record(paired["scored"]))
    assert flags, f"Expected review cases in cached benchmark card {paired['page_id']}"
    with TestClient(create_app(settings), base_url=BASE) as client:
        sign_in(client)
        queue = client.get("/api/queue").json()
        assert len(queue["items"]) == len(flags) and not queue["diagnostics"]
        for item in queue["items"]:
            detail = client.get(f"/api/review-items/{item['id']}").json()
            assert detail["allowed_actions"] and not detail["diagnostics"]
        saved = decide(client, queue["items"][0], "accept", "cached-real-reading")
    with TestClient(create_app(settings), base_url=BASE) as client:
        sign_in(client)
        item = client.get(f"/api/review-items/{saved['item']['id']}").json()
        assert item["review_state"] == "accepted"
        assert (
            client.post(
                f"/api/decisions/{saved['decision']['id']}/undo",
                json={"expected_version": item["version"], "request_id": "undo-cached"},
            ).json()["item"]["review_state"]
            == "pending"
        )
    assert all(
        "confidence" in field
        for _, field in current_fields(
            json.loads((settings.data_checkout / "results/demo.jsonl").read_text())
        )
    )

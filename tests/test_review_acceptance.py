"""Real producer/HTTP/persistence contract on disposable copies and local Git."""

import json
import runpy
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from review_support import git, setup_review

from survey.records import read_records
from survey.review.api import Settings, create_app
from survey.review.flags import build_flags

PREPARE = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts/review_acceptance.py")
)["prepare_acceptance"]
BASE = "http://127.0.0.1:8877"


def test_generated_queue_decisions_restart_export_regeneration_and_undo(tmp_path):
    _, original = setup_review(tmp_path / "original")
    source = original.data_checkout / "results/demo.jsonl"
    scan = original.scan_root / "demo/synthetic.pdf"
    before = source.read_bytes(), scan.read_bytes()
    root = tmp_path / "acceptance with spaces"
    checkout, flags = PREPARE(source, original.scan_root, root)
    settings = Settings(root / "scans", checkout, flags, root / "cache", port=8877)
    supplied = [json.loads(line) for line in flags.read_text().splitlines()]
    assert len(supplied) > 3  # Not the handpicked setup_review assignment.
    assert git(checkout, "remote", "get-url", "origin") == str(root / "remote.git")
    original_records, _ = read_records(source, "demo")
    with TestClient(create_app(settings), base_url=BASE) as client:
        assert client.get("/api/health").json()["ready"]
        queue = client.get("/api/queue").json()
        assert queue["diagnostics"] == []
        assert len(queue["items"]) == len(supplied)
        for summary in queue["items"]:
            item = client.get(f"/api/review-items/{summary['id']}").json()
            assert item["allowed_actions"]
            assert {"value", "status", "confidence"} <= item["field"].keys()
            assert any(row["id"] == item["id"] for row in item["card_fields"])
        rent = next(i for i in queue["items"] if i["label"] == "Weekly Rent")
        assert client.get(rent["scan_url"]).headers["content-type"] == "image/png"
        client.post("/api/session", json={"name": "Integration Reviewer"})
        body = {
            "action": "correct",
            "value": "009",
            "expected_version": rent["version"],
            "request_id": "production-correct",
        }
        endpoint = f"/api/review-items/{rent['id']}/decisions"
        response = client.post(endpoint, json=body)
        assert response.status_code == 200, response.text
        decision = response.json()["decision"]
        assert client.post(endpoint, json=body).json()["decision"] == decision
        assert (
            client.post(endpoint, json={**body, "request_id": "stale"}).status_code
            == 409
        )
        second = next(
            i
            for i in queue["items"]
            if i["label"] == "Weekly Rent" and i["id"] != rent["id"]
        )
        current = client.get(f"/api/review-items/{second['id']}").json()
        assert (
            client.post(
                f"/api/review-items/{second['id']}/decisions",
                json={
                    "action": "accept",
                    "expected_version": current["version"],
                    "request_id": "production-accept",
                },
            ).status_code
            == 200
        )
        assert client.post("/api/sync", json={}).json()["state"] == "uploaded"
    with TestClient(create_app(settings), base_url=BASE) as client:
        item = client.get(f"/api/review-items/{rent['id']}").json()
        assert item["field"]["value"] == "009"
        assert item["review_state"] == "corrected"
        assert len(item["field"]["review"]["history"]) == 1
        assert (
            item["field"]["review"]["history"][0]["reviewer"] == "Integration Reviewer"
        )
        exported, _ = read_records(checkout / "results/demo.jsonl", "demo")
        field = exported[0]["dwelling"]["households"][0]["coding"]["weekly_rent"]
        assert field["review"]["history"][0]["before"]["value"] == "04"
        # Unflagged front/person/notes and every other field remain byte-equivalent
        # as values; only the two intended coding fields and schema may differ.
        restored = json.loads(json.dumps(exported))
        restored[0]["schema_version"] = original_records[0]["schema_version"]
        for index in (0, 1):
            restored[0]["dwelling"]["households"][index]["coding"]["weekly_rent"] = (
                original_records[0]["dwelling"]["households"][index]["coding"][
                    "weekly_rent"
                ]
            )
        assert restored == original_records
        regenerated, skipped = build_flags({"demo": exported})
        assert not skipped and len(regenerated) == len(supplied) - 2
        client.post("/api/session", json={"name": "Integration Reviewer"})
        result = client.post(
            f"/api/decisions/{decision['id']}/undo",
            json={"expected_version": item["version"], "request_id": "production-undo"},
        )
        assert result.status_code == 200, result.text
        assert result.json()["item"]["field"]["value"] == "04"
    assert (source.read_bytes(), scan.read_bytes()) == before
    assert (root / "scans/demo/synthetic.pdf").read_bytes() == before[1]


def test_empty_generated_assignment_can_reopen_and_missing_assignment_still_blocks(
    tmp_path,
):
    _, settings = setup_review(tmp_path, with_git=True)
    settings = replace(settings, port=8877)
    settings.flags.write_text("")
    with TestClient(create_app(settings), base_url=BASE) as client:
        assert client.get("/api/health").json()["ready"]
        assert client.get("/api/queue").json()["items"] == []
        assert client.get("/api/dwellings").json()["dwellings"] == []
    settings.flags.unlink()
    with TestClient(create_app(settings), base_url=BASE) as client:
        health = client.get("/api/health").json()
        assert (
            not health["ready"] and health["diagnostics"][0]["code"] == "missing_flags"
        )


def test_acceptance_refuses_existing_or_overlapping_destination(tmp_path):
    _, settings = setup_review(tmp_path / "original")
    source = settings.data_checkout / "results/demo.jsonl"
    for destination in (
        settings.scan_root / "test",
        source.parent / "test",
        tmp_path / "original",
    ):
        with pytest.raises(ValueError):
            PREPARE(source, settings.scan_root, destination)


def test_source_change_during_parse_is_rejected_before_destination_creation(
    tmp_path, monkeypatch
):
    _, settings = setup_review(tmp_path / "original")
    source = settings.data_checkout / "results/demo.jsonl"
    destination = tmp_path / "acceptance"
    original_reader = PREPARE.__globals__["read_records"]

    def changed_after_read(path, region):
        result = original_reader(path, region)
        # Simulate an external producer replacing input immediately after parsing.
        source.write_bytes(source.read_bytes() + b"\n")
        return result

    monkeypatch.setitem(PREPARE.__globals__, "read_records", changed_after_read)
    with pytest.raises(ValueError, match="changed during validation"):
        PREPARE(source, settings.scan_root, destination)
    assert not destination.exists()

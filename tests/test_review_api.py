from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from review_support import git, setup_review
from review_support import historical_app as create_app

from survey import cli, records
from survey.review.launch import open_when_ready

BASE = "http://127.0.0.1:8765"


def setup_client(tmp_path):
    _, settings = setup_review(tmp_path, with_git=True)
    return settings, TestClient(create_app(settings), base_url=BASE)


def test_api_decision_restart_and_undo(tmp_path):
    settings, client = setup_client(tmp_path)
    with client:
        assert client.get("/api/health").json()["ready"]
        assert client.get("/").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").json()["paths"]["/api/queue"]
        queue = client.get("/api/queue?region=demo").json()
        item = queue["items"][1]
        assert client.get(item["scan_url"]).headers["content-type"] == "image/png"
        body = {
            "action": "correct",
            "value": "009",
            "expected_version": item["version"],
            "request_id": "api-correction",
        }
        assert (
            client.post(
                f"/api/review-items/{item['id']}/decisions", json=body
            ).status_code
            == 401
        )
        assert (
            client.post("/api/session", json={"name": "  Reviewer  "}).json()[
                "reviewer"
            ]
            == "Reviewer"
        )
        response = client.post(f"/api/review-items/{item['id']}/decisions", json=body)
        assert response.status_code == 200
        result = response.json()
        assert result["saved_locally"] and result["item"]["field"]["value"] == "009"
        assert result["decision"]["reviewer"] == "Reviewer"
        assert (
            client.get(f"/api/review-items/{item['id']}/history").json()["history"][0][
                "id"
            ]
            == result["decision"]["id"]
        )
        assert client.post("/api/sync", json={}).json()["state"] == "uploaded"
    with TestClient(create_app(settings), base_url=BASE) as reopened:
        item = reopened.get("/api/queue").json()["items"][1]
        assert item["field"]["value"] == "009" and item["review_state"] == "corrected"
        reopened.post("/api/session", json={"name": "Reviewer"})
        undo = reopened.post(
            f"/api/decisions/{result['decision']['id']}/undo",
            json={"expected_version": item["version"], "request_id": "api-undo"},
        )
        assert undo.status_code == 200 and undo.json()["item"]["field"]["value"] == "12"
        assert undo.json()["item"]["review_state"] == "pending"


def test_mutation_security_and_validation(tmp_path):
    _, client = setup_client(tmp_path)
    with client:
        assert client.post("/api/session", json={"name": " "}).status_code == 422
        assert (
            client.post(
                "/api/session",
                json={"name": "Reviewer"},
                headers={"origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/session",
                json={"name": "Reviewer"},
                headers={"host": "evil.example"},
            ).status_code
            == 403
        )
        assert client.post("/api/session", content="name=Reviewer").status_code == 422
        assert (
            client.post(
                "/api/session", json={"name": "Reviewer"}, headers={"origin": BASE}
            ).status_code
            == 200
        )
        item = client.get("/api/queue").json()["items"][1]
        path = f"/api/review-items/{item['id']}/decisions"
        body = {
            "action": "correct",
            "value": "09",
            "expected_version": item["version"],
            "request_id": "change",
        }
        assert client.post(path, json={**body, "reviewer": "Forged"}).status_code == 422
        assert client.post(path, json={**body, "value": 9}).status_code == 422
        assert (
            client.post(path, json={**body, "action": "crossed_out"}).status_code == 422
        )
        assert client.post(path, json=body).status_code == 200
        assert (
            client.post(path, json={**body, "request_id": "stale"}).status_code == 409
        )
        assert client.get("/api/review-items/missing").status_code == 404
        assert client.get("/api/scans/missing").status_code == 404


def test_save_failure_no_success_and_no_advance(tmp_path, monkeypatch):
    _, client = setup_client(tmp_path)
    with client:
        client.post("/api/session", json={"name": "Reviewer"})
        item = client.get("/api/queue").json()["items"][1]

        def fail(*args):
            raise PermissionError("denied")

        monkeypatch.setattr(records, "write_atomic", fail)
        response = client.post(
            f"/api/review-items/{item['id']}/decisions",
            json={
                "action": "accept",
                "expected_version": item["version"],
                "request_id": "failed",
            },
        )
        assert (
            response.status_code == 500
            and response.json()["error"]["code"] == "save_failed"
        )
        assert (
            client.get(f"/api/review-items/{item['id']}").json()["review_state"]
            == "pending"
        )


def test_startup_diagnostics_and_second_application(tmp_path):
    settings, client = setup_client(tmp_path)
    with client, TestClient(create_app(settings), base_url=BASE) as second:
        assert (
            second.get("/api/health").json()["diagnostics"][0]["code"] == "writer_busy"
        )
        assert second.post("/api/session", json={"name": "Reviewer"}).status_code == 503
    missing = replace(settings, flags=tmp_path / "not-present.jsonl")
    with TestClient(create_app(missing), base_url=BASE) as client:
        assert (
            client.get("/api/health").json()["diagnostics"][0]["code"]
            == "missing_flags"
        )


def test_batch_completion_sync_and_periodic_worker(tmp_path):
    settings, _ = setup_client(tmp_path)
    settings.flags.write_text(settings.flags.read_text().splitlines()[1] + "\n")
    with TestClient(create_app(settings), base_url=BASE) as client:
        client.post("/api/session", json={"name": "Reviewer"})
        item = client.get("/api/queue").json()["items"][0]
        result = client.post(
            f"/api/review-items/{item['id']}/decisions",
            json={
                "action": "accept",
                "expected_version": item["version"],
                "request_id": "complete",
            },
        )
        assert result.json()["sync"]["state"] == "uploaded"
        assert client.get("/api/queue").json()["complete"]
        assert git(settings.data_checkout, "rev-parse", "HEAD") == git(
            tmp_path / "remote.git", "rev-parse", "review-data"
        )


def test_review_cli_and_validation_do_not_require_model_key(tmp_path, monkeypatch):
    _, settings = setup_review(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert cli.main(["validate-results", str(settings.data_checkout / "results")]) == 0
    assert cli.main(["validate-results", str(tmp_path / "absent")]) == 1
    with pytest.raises(SystemExit):
        cli.main(["review"])
    import socket
    from contextlib import nullcontext
    from types import SimpleNamespace

    import uvicorn

    monkeypatch.setattr(
        socket,
        "socket",
        lambda: nullcontext(
            SimpleNamespace(bind=lambda address: None, setsockopt=lambda *args: None)
        ),
    )

    calls = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.update(kwargs))
    assert (
        cli.main(
            [
                "review",
                "--scan-root",
                str(settings.scan_root),
                "--data-checkout",
                str(settings.data_checkout),
                "--flags",
                str(settings.flags),
                "--cache",
                str(settings.cache),
            ]
        )
        == 0
    )
    assert calls["host"] == "127.0.0.1" and calls["workers"] == 1


def test_launch_reports_configuration_failure_without_opening_browser(monkeypatch):
    import urllib.request
    import webbrowser
    from io import BytesIO

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: BytesIO(
            b'{"ready":false,"diagnostics":["missing data"]}'
        ),
    )
    monkeypatch.setattr(
        webbrowser, "open", lambda *args: pytest.fail("Browser should not open")
    )
    assert open_when_ready(8765) == 1


def test_launch_waits_for_production_validation_and_remains_bounded(monkeypatch):
    from io import BytesIO

    from survey.review import launch

    elapsed, opened = [0.0], []

    def health(*args, **kwargs):
        if elapsed[0] < 34:
            raise OSError("Production validation still running")
        return BytesIO(b'{"ready":true}')

    monkeypatch.setattr(launch.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        launch.time, "sleep", lambda delay: elapsed.__setitem__(0, elapsed[0] + delay)
    )
    monkeypatch.setattr(launch.urllib.request, "urlopen", health)
    monkeypatch.setattr(launch.webbrowser, "open", opened.append)
    assert open_when_ready(8765) == 0
    assert elapsed[0] == 34 and opened == ["http://127.0.0.1:8765"]
    elapsed[0] = 0
    opened.clear()
    assert open_when_ready(8765, timeout=2) == 1
    assert elapsed[0] == 2 and opened == []


def test_periodic_worker_calls_sync_with_history_refresh(tmp_path, monkeypatch):
    from threading import Event

    from survey.review.sync import GitSync

    settings, _ = setup_client(tmp_path)
    app = create_app(replace(settings, sync_interval=0.1))
    invoked = Event()
    callbacks = []

    # Real commit/push behavior is covered in test_review_sync.py. This checks
    # scheduling independently of Git subprocess throughput on the CI runner.
    def observed(self, reload_callback=None):
        callbacks.append(reload_callback)
        invoked.set()

    monkeypatch.setattr(GitSync, "sync", observed)
    with TestClient(app, base_url=BASE):
        assert invoked.wait(30), "Periodic worker did not invoke synchronization"
    assert callbacks
    assert all(callback == app.state.service.reindex_history for callback in callbacks)


def test_review_cli_port_collision_leaves_existing_backend_alone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import socket
    from contextlib import nullcontext
    from types import SimpleNamespace

    import uvicorn

    _, settings = setup_review(tmp_path)

    def busy(*args):
        raise OSError("Address already in use")

    monkeypatch.setattr(
        socket,
        "socket",
        lambda: nullcontext(SimpleNamespace(bind=busy, setsockopt=lambda *args: None)),
    )
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda *args, **kwargs: pytest.fail("Should not launch on an occupied port"),
    )
    assert (
        cli.main(
            [
                "review",
                "--scan-root",
                str(settings.scan_root),
                "--data-checkout",
                str(settings.data_checkout),
                "--flags",
                str(settings.flags),
                "--cache",
                str(settings.cache),
            ]
        )
        == 1
    )


def test_missing_region_and_malformed_flags_remain_browsable(tmp_path):
    import json

    settings, _ = setup_client(tmp_path)
    extra = {
        "region": "missing",
        "pdf": "missing.pdf",
        "page": 1,
        "field_path": "/dwelling/municipality",
    }
    invalid = {**extra, "region": "../bad"}
    with settings.flags.open("a") as stream:
        stream.write(json.dumps(extra) + "\n" + json.dumps(invalid) + "\n")
    with TestClient(create_app(settings), base_url=BASE) as client:
        regions = client.get("/api/regions").json()["regions"]
        missing = next(r for r in regions if r["region"] == "missing")
        assert not missing["has_records"] and missing["batches"] == ["missing.pdf"]
        queue = client.get("/api/queue?region=demo&batch=synthetic.pdf").json()
        assert any(d["code"] == "invalid_reference" for d in queue["diagnostics"])
        assert not queue["complete"]
        assert client.get("/api/queue?region=missing").json()["unresolved"] >= 1


def test_only_requested_scan_is_rendered(tmp_path):
    settings, client = setup_client(tmp_path)
    with client:
        queue = client.get("/api/queue").json()
        item = queue["items"][1]
        assert client.get(f"/api/review-items/{item['id']}").status_code == 200
        assert not list(settings.cache.glob("*.png"))
        assert client.get(item["scan_url"]).status_code == 200
        assert len(list(settings.cache.glob("*.png"))) == 1
        assert client.get(item["scan_url"]).status_code == 200
        assert len(list(settings.cache.glob("*.png"))) == 1


def test_undo_replay_after_response_is_lost(tmp_path):
    _, client = setup_client(tmp_path)
    with client:
        client.post("/api/session", json={"name": "Reviewer"})
        item = client.get("/api/queue").json()["items"][1]
        saved = client.post(
            f"/api/review-items/{item['id']}/decisions",
            json={
                "action": "correct",
                "value": "009",
                "expected_version": item["version"],
                "request_id": "correct",
            },
        ).json()
        body = {"expected_version": saved["item"]["version"], "request_id": "undo"}
        url = f"/api/decisions/{saved['decision']['id']}/undo"
        assert client.post(url, json=body).status_code == 200
        replay = client.post(url, json=body)
        assert replay.status_code == 200 and replay.json()["replayed"]
        assert len(replay.json()["item"]["field"]["review"]["history"]) == 2


def test_posix_port_probe_rejects_live_listener_but_allows_immediate_restart(
    tmp_path, monkeypatch
):
    import socket
    import sys

    import uvicorn

    if sys.platform == "win32":
        pytest.skip("POSIX TIME_WAIT reuse behavior; Windows probe is unchanged")
    monkeypatch.chdir(tmp_path)
    _, settings = setup_review(tmp_path)
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        argv = [
            "review",
            "--scan-root",
            str(settings.scan_root),
            "--data-checkout",
            str(settings.data_checkout),
            "--flags",
            str(settings.flags),
            "--cache",
            str(settings.cache),
            "--port",
            str(port),
        ]
        assert cli.main(argv) == 1 and not calls
        with socket.socket() as client:
            client.connect(("127.0.0.1", port))
            connection, _ = listener.accept()
            connection.close()  # Server initiates close and enters TIME_WAIT.
            assert client.recv(1) == b""
    assert cli.main(argv) == 0
    assert calls[0]["port"] == port


def test_startup_loads_dataset_once_after_writer_lock(tmp_path, monkeypatch):
    from survey import records
    from survey.review.sync import WriterLock

    _settings, client = setup_client(tmp_path)
    original_read = records.read_dataset
    original_acquire = WriterLock.acquire
    events = []

    def acquired(lock):
        original_acquire(lock)
        events.append("lock")

    def read(paths):
        events.append("read")
        return original_read(paths)

    monkeypatch.setattr(WriterLock, "acquire", acquired)
    monkeypatch.setattr(records, "read_dataset", read)
    with client:
        assert client.get("/api/health").json()["ready"]
    assert events == ["lock", "read"]


def test_decision_completion_does_not_rebuild_queue(tmp_path, monkeypatch):
    _settings, client = setup_client(tmp_path)
    with client:
        service = client.app.state.service
        item = service.item(next(iter(service.references)))
        client.post("/api/session", json={"name": "Counter reviewer"})
        monkeypatch.setattr(
            service, "queue", lambda *args: pytest.fail("Completion rebuilt the queue")
        )
        response = client.post(
            "/api/review-items/" + item["id"] + "/decisions",
            json={
                "action": "accept",
                "expected_version": item["version"],
                "request_id": "counter-api",
            },
        )
        assert response.status_code == 200

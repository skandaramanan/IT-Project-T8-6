"""Drive transfers use synthetic PDFs and a fake remote, never archive writes."""

import hashlib
import json
from dataclasses import replace
from threading import Event

import pytest
from fastapi.testclient import TestClient
from review_support import setup_review

from survey.records import ReviewError
from survey.review.api import create_app
from survey.review.drive import BatchDownloads, DriveClient

BASE = "http://127.0.0.1:8765"


def fixture(tmp_path, with_git=False):
    service, settings = setup_review(tmp_path, with_git=with_git)
    pdf = settings.scan_root / "demo/synthetic.pdf"
    data = pdf.read_bytes()
    batch = {
        "region": "demo",
        "pdf": "synthetic.pdf",
        "size": len(data),
        "md5": hashlib.md5(data).hexdigest(),
        "file_id": "synthetic-id",
        "resource_key": "synthetic-key",
    }
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps({"version": 1, "batches": [batch]}))
    pdf.unlink()
    downloads = BatchDownloads(service, "test-key", catalogue)
    return (
        downloads,
        data,
        replace(settings, scan_catalogue=catalogue, drive_api_key="test-key"),
    )


def remote(downloads, data):
    batch = downloads.batches["demo"]
    downloads.client.metadata = lambda b, c: {
        "name": b["pdf"],
        "mimeType": "application/pdf",
        "size": str(b["size"]),
        "md5Checksum": b["md5"],
        "capabilities": {"canDownload": True},
    }
    downloads.client.chunks = lambda b, c: iter([data[:100], data[100:]])
    return batch


def finish(downloads):
    downloads.worker.join(timeout=5)
    assert not downloads.worker.is_alive()
    return downloads.status("demo")


def test_download_publishes_original_and_refreshes_review(tmp_path):
    downloads, data, _ = fixture(tmp_path)
    remote(downloads, data)
    service = downloads.service
    ref = next(iter(service.references.values()))
    assert service.item(ref.item_id)["allowed_actions"] == []
    downloads.start("demo")
    assert finish(downloads)["state"] == "ready"
    assert downloads.target(downloads.batches["demo"]).read_bytes() == data
    assert service.item(ref.item_id)["allowed_actions"]
    assert service.scans.get_scan(ref).is_file()
    assert not list(downloads.root.rglob("*.part"))
    assert downloads.start("demo")["state"] == "ready"


@pytest.mark.parametrize(
    "problem",
    ["truncated", "checksum", "too_large", "changed_remote", "restricted", "disk"],
)
def test_transfer_failures_do_not_publish(tmp_path, problem):
    downloads, data, _ = fixture(tmp_path)
    batch = remote(downloads, data)
    if problem == "truncated":
        downloads.client.chunks = lambda b, c: iter([data[:-1]])
    elif problem == "checksum":
        downloads.client.chunks = lambda b, c: iter([b"x" + data[1:]])
    elif problem == "too_large":
        downloads.client.chunks = lambda b, c: iter([data + b"x"])
    elif problem == "changed_remote":
        downloads.client.metadata = lambda b, c: {"name": "different.pdf"}
    elif problem == "restricted":
        original = downloads.client.metadata
        downloads.client.metadata = lambda b, c: {
            **original(b, c),
            "capabilities": {"canDownload": False},
        }
    else:

        def denied(*args):
            raise PermissionError("synthetic denied")

        downloads.staging = denied
    downloads.start("demo")
    status = finish(downloads)
    assert status["state"] == "failed" and status["error"]
    assert not downloads.target(batch).exists()
    assert not list(downloads.root.rglob("*.part"))


def test_cancel_duplicate_click_and_single_transfer(tmp_path):
    downloads, data, _ = fixture(tmp_path)
    remote(downloads, data)
    entered = Event()

    def chunks(b, cancel):
        entered.set()
        cancel.wait(5)
        yield data

    downloads.client.chunks = chunks
    downloads.start("demo")
    assert entered.wait(3)
    worker = downloads.worker
    assert downloads.start("demo")["state"] == "downloading"
    assert downloads.worker is worker
    with pytest.raises(ReviewError, match="already running"):
        downloads.claim("demo", "importing")
    downloads.cancel("demo")
    assert finish(downloads)["state"] == "cancelled"
    assert not list(downloads.root.rglob("*.part"))
    remote(downloads, data)
    downloads.start("demo")
    assert finish(downloads)["state"] == "ready"


def test_existing_file_and_symlinks_are_not_overwritten(tmp_path):
    downloads, data, _ = fixture(tmp_path)
    batch = remote(downloads, data)
    target = downloads.target(batch)
    target.write_bytes(b"do not overwrite")
    downloads.start("demo")
    assert finish(downloads)["error"]["code"] == "scan_exists"
    assert target.read_bytes() == b"do not overwrite"
    target.unlink()
    external = tmp_path / "external.pdf"
    external.write_bytes(data)
    target.symlink_to(external)
    with pytest.raises(ReviewError, match="real region folder"):
        downloads.start("demo")
    assert external.read_bytes() == data


def test_racing_file_and_page_mismatch_do_not_publish(tmp_path):
    downloads, data, _ = fixture(tmp_path)
    remote(downloads, data)
    downloads.claim("demo", "importing")
    with downloads.staging(downloads.batches["demo"]) as (path, stream):
        downloads.write_chunk("demo", stream, data)
        stream.close()
        target = downloads.target(downloads.batches["demo"])
        target.write_bytes(b"racing file")
        with pytest.raises(ReviewError, match="not overwritten"):
            downloads.publish("demo", path)
        assert target.read_bytes() == b"racing file"
    downloads.release("demo")
    target.unlink()
    downloads.service.store.regions["demo"][0][0]["dwelling"]["cards"][0]["page"] = 999
    downloads.start("demo")
    assert finish(downloads)["error"]["code"] == "scan_page_mismatch"
    assert not target.exists()


def test_public_request_uses_key_and_resource_key():
    client = DriveClient("fake-key")
    request = client.request("files/fake", {"alt": "media"}, "resource", "fake")
    assert (
        request.full_url
        == "https://www.googleapis.com/drive/v3/files/fake?alt=media&key=fake-key"
    )
    assert request.headers["X-goog-drive-resource-keys"] == "fake/resource"
    assert "Authorization" not in request.headers


def test_manual_import_security_and_restart(tmp_path):
    _, data, settings = fixture(tmp_path, with_git=True)
    settings = replace(settings, drive_api_key=None)
    target = settings.scan_root / "demo/synthetic.pdf"
    with TestClient(create_app(settings), base_url=BASE) as client:
        path = "/api/scan-batches/demo/import"
        assert client.get("/api/scan-batches?region=demo").json()["state"] == "missing"
        assert (
            client.post(
                path, content=data, headers={"content-type": "application/pdf"}
            ).status_code
            == 401
        )
        client.post("/api/session", json={"name": "Reviewer"})
        assert (
            client.post(
                path,
                content=data,
                headers={
                    "content-type": "application/pdf",
                    "origin": "https://evil.example",
                },
            ).status_code
            == 403
        )
        assert client.post(path, json={}).status_code == 422
        assert (
            client.post("/api/scan-batches/demo/download", json={}).status_code == 503
        )
        assert (
            client.post(
                path, content=data[:-1], headers={"content-type": "application/pdf"}
            ).status_code
            == 422
        )
        assert not target.exists()
        response = client.post(
            path,
            content=data,
            headers={"content-type": "application/pdf", "origin": BASE},
        )
        assert response.status_code == 200 and response.json()["state"] == "ready"
        assert target.read_bytes() == data
        item = client.get("/api/queue?region=demo").json()["items"][0]
        assert client.get(item["scan_url"]).status_code == 200
        assert (
            client.post(
                "/api/session",
                content=data,
                headers={"content-type": "application/pdf"},
            ).status_code
            == 422
        )
        assert client.get("/api/scan-batches?region=unknown").status_code == 404
    with TestClient(create_app(settings), base_url=BASE) as reopened:
        assert reopened.get("/api/scan-batches?region=demo").json()["state"] == "ready"


def test_mapping_rejects_mismatched_records(tmp_path):
    downloads, _, _ = fixture(tmp_path)
    downloads.batches["demo"]["pdf"] = "wrong.pdf"
    with pytest.raises(ReviewError, match="matches this region"):
        downloads.status("demo")


def test_ready_status_rechecks_deleted_or_changed_source(tmp_path):
    downloads, data, _ = fixture(tmp_path)
    batch = remote(downloads, data)
    downloads.start("demo")
    assert finish(downloads)["state"] == "ready"
    target = downloads.target(batch)
    target.unlink()
    assert downloads.status("demo")["state"] == "missing"
    target.write_bytes(b"x" * len(data))
    assert downloads.status("demo")["state"] != "ready"


def test_approved_but_unreadable_pdf_is_rejected(tmp_path):
    downloads, data, _ = fixture(tmp_path)
    invalid = b"x" * len(data)
    downloads.batches["demo"]["md5"] = hashlib.md5(invalid).hexdigest()
    remote(downloads, invalid)
    downloads.start("demo")
    assert finish(downloads)["error"]["code"] == "unreadable_scan"
    assert not list(downloads.root.rglob("*.part"))


def test_connection_retries_and_permission_errors_do_not_leak_key(monkeypatch):
    from urllib.error import HTTPError

    from survey.review import drive

    calls = []
    cancel = Event()
    monkeypatch.setattr(cancel, "wait", lambda timeout: None)

    def limited(request, **kwargs):
        calls.append(request)
        raise HTTPError(request.full_url, 429, "limited", {}, None)

    monkeypatch.setattr(drive, "urlopen", limited)
    client = DriveClient("do-not-expose-this-key")
    request = client.request("files/fake", {"alt": "media"})
    with pytest.raises(ReviewError) as error:
        client.open(request, cancel)
    assert error.value.code == "drive_unavailable" and len(calls) == 3
    assert "do-not-expose" not in str(error.value)

    def denied(request, **kwargs):
        raise HTTPError(request.full_url, 404, "missing", {}, None)

    monkeypatch.setattr(drive, "urlopen", denied)
    with pytest.raises(ReviewError) as error:
        client.open(request, cancel)
    assert error.value.code == "drive_access_failed"
    assert "do-not-expose" not in str(error.value)


def test_catalogue_builder_paginates_and_checks_local_source(tmp_path):
    import io
    import runpy
    from pathlib import Path

    module = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts/build_drive_catalogue.py")
    )
    source = tmp_path / "216418" / "original.pdf"
    source.parent.mkdir()
    source.write_bytes(b"source bytes")
    pages = [
        {"files": [], "nextPageToken": "opaque-token"},
        {
            "files": [
                {
                    "id": "folder-id",
                    "name": "216418",
                    "mimeType": "application/vnd.google-apps.folder",
                    "resourceKey": "folder-key",
                },
                {
                    "id": "other",
                    "name": "results",
                    "mimeType": "application/vnd.google-apps.folder",
                },
            ]
        },
        {
            "files": [
                {
                    "id": "pdf-id",
                    "name": "original.pdf",
                    "mimeType": "application/pdf",
                    "size": "12",
                    "md5Checksum": hashlib.md5(b"source bytes").hexdigest(),
                    "resourceKey": "pdf-key",
                }
            ]
        },
    ]
    requests = []
    client = DriveClient("test")

    def opened(request, cancel):
        requests.append(request)
        return io.BytesIO(json.dumps(pages.pop(0)).encode())

    client.open = opened
    catalogue = module["build"](tmp_path, client)
    assert len(catalogue["batches"]) == 1
    assert catalogue["batches"][0]["resource_key"] == "pdf-key"
    assert "pageToken=opaque-token" in requests[1].full_url
    assert requests[2].headers["X-goog-drive-resource-keys"] == "folder-id/folder-key"

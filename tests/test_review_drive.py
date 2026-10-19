"""Drive transfers use synthetic PDFs and a fake remote, never archive writes."""

import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from review_support import setup_review

from survey.records import ReviewError
from survey.review.api import create_app
from survey.review.drive import MAX_IMPORT_BYTES, BatchDownloads, DriveClient

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
        "size": str(len(data)),
        "md5Checksum": hashlib.md5(data).hexdigest(),
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
    with pytest.raises(ReviewError, match="already exists"):
        downloads.start("demo")


def test_start_status_waits_for_scan_directory_creation(tmp_path, monkeypatch):
    downloads, data, _ = fixture(tmp_path)
    batch = remote(downloads, data)
    folder = downloads.target(batch).parent
    folder.rmdir()
    creating, release, checking, returned = (Event() for _ in range(4))
    mkdir, status = Path.mkdir, downloads.status

    def paused_mkdir(path, *args, **kwargs):
        if path == folder:
            creating.set()
            assert release.wait(timeout=5)
        return mkdir(path, *args, **kwargs)

    def concurrent_status(region):
        assert creating.wait(timeout=5)
        checking.set()
        result = status(region)
        returned.set()
        return result

    monkeypatch.setattr(Path, "mkdir", paused_mkdir)
    monkeypatch.setattr(downloads, "status", concurrent_status)
    with ThreadPoolExecutor(max_workers=1) as pool:
        started = pool.submit(downloads.start, "demo")
        try:
            assert checking.wait(timeout=5)
            # Resolving while mkdir is paused can spuriously fail on Windows.
            assert not returned.wait(timeout=0.1)
        finally:
            release.set()
        started.result(timeout=5)
    assert finish(downloads)["state"] == "ready"
    assert downloads.target(batch).read_bytes() == data


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


@pytest.mark.parametrize("usable", [True, False])
def test_existing_file_blocks_download_and_symlinks_are_not_overwritten(
    tmp_path, usable
):
    downloads, data, _ = fixture(tmp_path)
    batch = remote(downloads, data)
    target = downloads.target(batch)
    existing = data if usable else b"do not overwrite"
    target.write_bytes(existing)
    with pytest.raises(ReviewError, match="Move it out") as error:
        downloads.start("demo")
    assert error.value.code == "scan_exists" and error.value.status == 409
    assert downloads.worker is None and downloads.active is None
    assert target.read_bytes() == existing
    assert not (target.parent / ".scan-backups").exists()
    target.unlink()
    external = tmp_path / "external.pdf"
    external.write_bytes(data)
    target.symlink_to(external)
    with pytest.raises(ReviewError, match="real region folder"):
        downloads.start("demo")
    assert external.read_bytes() == data


@pytest.mark.parametrize("kind", ["download", "import"])
@pytest.mark.parametrize("usable", [True, False])
def test_transfer_endpoints_reject_existing_pdf(tmp_path, kind, usable):
    _, data, settings = fixture(tmp_path, with_git=True)
    target = settings.scan_root / "demo/synthetic.pdf"
    existing = data if usable else b"unreadable PDF"
    target.write_bytes(existing)
    backup = target.parent / ".scan-backups" / "previous.pdf"
    backup.parent.mkdir()
    backup.write_bytes(b"previous backup")
    with TestClient(create_app(settings), base_url=BASE) as client:
        client.post("/api/session", json={"name": "Reviewer"})
        if kind == "download":
            response = client.post("/api/scan-batches/demo/download", json={})
        else:
            response = client.post(
                "/api/scan-batches/demo/import",
                content=data,
                headers={
                    "Content-Type": "application/pdf",
                    "X-Scan-Size": str(len(data)),
                },
            )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "scan_exists"
        assert "Open scan folder" in response.json()["error"]["message"]
        status = client.get("/api/scan-batches?region=demo").json()
        assert status["local_file_exists"] and status["local_ready"] == usable
        assert status["active_region"] is None
    assert target.read_bytes() == existing
    assert backup.read_bytes() == b"previous backup"
    assert not list(target.parent.rglob("*.part"))


def test_racing_file_and_page_mismatch_do_not_publish(tmp_path):
    downloads, data, _ = fixture(tmp_path)
    remote(downloads, data)
    downloads.claim("demo", "importing", len(data))
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
                path,
                content=data[:-1],
                headers={
                    "content-type": "application/pdf",
                    "X-Scan-Size": str(len(data)),
                },
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


def changed_pdf(data, *, encrypted=False, pages=None):
    reader, writer = PdfReader(io.BytesIO(data)), PdfWriter()
    for page in list(reader.pages)[:pages]:
        writer.add_page(page)
    writer.add_metadata({"/Title": "Current authoritative Drive copy"})
    if encrypted:
        writer.encrypt("test-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("region", ["216413", "216414", "216415"])
def test_current_drive_metadata_supersedes_historical_catalogue(tmp_path, region):
    downloads, data, _ = fixture(tmp_path)
    remote(downloads, data)
    downloads.batches["demo"].update(size=123, md5="0" * 32)
    # Exercise each production region's policy without real scans or network calls.
    batch = downloads.batches.pop("demo")
    batch["region"] = region
    downloads.batches[region] = batch
    service = downloads.service
    service.store.regions[region] = service.store.regions.pop("demo")
    service.region_references[region] = service.region_references.pop("demo")
    downloads.start(region)
    downloads.worker.join(timeout=5)
    status = downloads.status(region)
    assert status["state"] == "ready" and status["size"] == len(data)
    assert downloads.target(batch).read_bytes() == data


def test_drive_changes_retry_once_with_fresh_metadata(tmp_path):
    downloads, old, _ = fixture(tmp_path)
    new = changed_pdf(old)
    remote(downloads, old)
    metadata = downloads.client.metadata
    current = {"data": old}
    calls = []

    def describe(batch, cancel):
        return {
            **metadata(batch, cancel),
            "size": str(len(current["data"])),
            "md5Checksum": hashlib.md5(current["data"]).hexdigest(),
        }

    def chunks(batch, cancel):
        calls.append(1)
        content = current["data"]
        current["data"] = new
        yield content

    downloads.client.metadata = describe
    downloads.client.chunks = chunks
    downloads.start("demo")
    assert finish(downloads)["state"] == "ready"
    assert len(calls) == 2
    assert downloads.target(downloads.batches["demo"]).read_bytes() == new
    assert not list(downloads.root.rglob("*.part"))


def test_drive_keeps_changing_reports_retryable_failure(tmp_path):
    downloads, old, _ = fixture(tmp_path)
    batch = remote(downloads, old)
    target = downloads.target(batch)
    count = []

    def metadata(b, c):
        count.append(1)
        return {
            "mimeType": "application/pdf",
            "size": str(len(old)),
            "md5Checksum": f"{len(count):032x}",
        }

    downloads.client.metadata = metadata
    downloads.start("demo")
    status = finish(downloads)
    assert status["state"] == "failed" and status["error"]["code"] == "source_changed"
    assert len(count) == 4
    assert not target.exists() and not status["local_ready"]
    assert not list(downloads.root.rglob("*.part"))


def test_file_appearing_during_download_is_preserved(tmp_path):
    downloads, data, _ = fixture(tmp_path)
    batch = remote(downloads, data)
    target = downloads.target(batch)
    raced = b"externally created file"

    def chunks(b, cancel):
        target.write_bytes(raced)
        yield data

    downloads.client.chunks = chunks
    downloads.start("demo")
    status = finish(downloads)
    assert status["state"] == "failed" and status["error"]["code"] == "scan_exists"
    assert target.read_bytes() == raced
    assert not list(downloads.root.rglob("*.part"))
    assert not (target.parent / ".scan-backups").exists()


def test_local_availability_is_offline_cached_and_not_historical(tmp_path, monkeypatch):
    downloads, data, _ = fixture(tmp_path)
    batch = downloads.batches["demo"]
    batch.update(size=1, md5="0" * 32)
    target = downloads.target(batch)
    target.write_bytes(data)
    calls = []
    original = downloads.page_count
    monkeypatch.setattr(
        downloads, "page_count", lambda path: (calls.append(path), original(path))[1]
    )
    monkeypatch.setattr(
        downloads.client, "metadata", lambda *a: pytest.fail("Status contacted Drive")
    )
    monkeypatch.setattr(
        hashlib, "file_digest", lambda *a: pytest.fail("Status hashed a PDF")
    )
    assert downloads.status("demo")["state"] == "ready"
    assert downloads.status("demo")["state"] == "ready"
    assert len(calls) == 1
    target.write_bytes(changed_pdf(data))
    assert downloads.status("demo")["state"] == "ready"
    assert len(calls) == 2
    downloads.service.store.regions["demo"][0][0]["dwelling"]["cards"][0]["page"] = 99
    assert not downloads.status("demo")["local_ready"]


@pytest.mark.parametrize(
    "problem",
    [
        "encrypted",
        "unreadable",
        "pages",
        "incomplete",
        "incomplete_chunked",
        "extra_chunked",
        "oversized",
        "size_missing",
    ],
)
def test_manual_import_validation_does_not_publish_invalid_pdf(tmp_path, problem):
    _, original, settings = fixture(tmp_path, with_git=True)
    settings = replace(settings, drive_api_key=None)
    target = settings.scan_root / "demo/synthetic.pdf"
    data = changed_pdf(original)
    headers = {"Content-Type": "application/pdf", "X-Scan-Size": str(len(data))}
    if problem == "encrypted":
        data = changed_pdf(original, encrypted=True)
        headers["X-Scan-Size"] = str(len(data))
    elif problem == "unreadable":
        data = b"not a PDF"
        headers["X-Scan-Size"] = str(len(data))
    elif problem == "pages":
        data = changed_pdf(original, pages=1)
        headers["X-Scan-Size"] = str(len(data))
    elif problem in {"incomplete", "incomplete_chunked"}:
        data = data[:-10]
    elif problem == "extra_chunked":
        data += b"extra bytes"
    elif problem == "oversized":
        headers["X-Scan-Size"] = str(MAX_IMPORT_BYTES + 1)
    with TestClient(create_app(settings), base_url=BASE) as client:
        client.post("/api/session", json={"name": "Reviewer"})
        if problem in {"size_missing", "incomplete_chunked", "extra_chunked"}:
            # A chunked client must explicitly declare its size.
            if problem == "size_missing":
                headers.pop("X-Scan-Size")
            response = client.post(
                "/api/scan-batches/demo/import", content=iter([data]), headers=headers
            )
        else:
            response = client.post(
                "/api/scan-batches/demo/import", content=data, headers=headers
            )
        assert response.status_code == 422, response.text
    assert not target.exists()
    assert not list(target.parent.rglob("*.part"))
    assert not list((target.parent / ".scan-backups").glob("*.pdf"))


def test_manual_import_requires_moving_existing_file_before_retry(tmp_path):
    _, original, settings = fixture(tmp_path, with_git=True)
    settings = replace(settings, drive_api_key=None)
    target = settings.scan_root / "demo/synthetic.pdf"
    target.write_bytes(original)
    new = changed_pdf(original)
    assert len(new) != len(original)
    with TestClient(create_app(settings), base_url=BASE) as client:
        client.post("/api/session", json={"name": "Reviewer"})
        item = client.get("/api/queue").json()["items"][0]
        assert client.get(item["scan_url"]).status_code == 200
        response = client.post(
            "/api/scan-batches/demo/import",
            content=new,
            headers={"Content-Type": "application/pdf", "X-Scan-Size": str(len(new))},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "scan_exists"
        assert "Move it out" in response.json()["error"]["message"]
        assert target.read_bytes() == original
        moved = tmp_path / "saved-original.pdf"
        target.rename(moved)
        response = client.post(
            "/api/scan-batches/demo/import",
            content=iter([new[:100], new[100:]]),
            headers={"Content-Type": "application/pdf", "X-Scan-Size": str(len(new))},
        )
        assert response.status_code == 200, response.text
        assert response.json()["size"] == len(new)
        assert client.get(item["scan_url"]).status_code == 200
    assert target.read_bytes() == new
    assert moved.read_bytes() == original
    assert not (target.parent / ".scan-backups").exists()


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


def test_catalogue_builder_paginates_and_ignores_outdated_local_source(tmp_path):
    import io
    import runpy
    from pathlib import Path

    module = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts/build_drive_catalogue.py")
    )
    source = tmp_path / "216418" / "original.pdf"
    source.parent.mkdir()
    source.write_bytes(b"different outdated bytes")
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


def test_open_scan_folder_requires_session_and_uses_configured_folder(
    tmp_path, monkeypatch
):
    from survey.review import drive

    _, _, settings = fixture(tmp_path, with_git=True)
    calls = []
    run = drive.subprocess.run

    def launch(*args, **kwargs):
        if args[0][0] == "git":
            return run(*args, **kwargs)
        calls.append((args, kwargs))

    monkeypatch.setattr(drive.subprocess, "run", launch)
    monkeypatch.setattr(
        drive.os, "startfile", lambda path: calls.append(path), raising=False
    )
    with TestClient(create_app(settings), base_url=BASE) as client:
        path = "/api/scan-batches/demo/open-folder"
        assert client.post(path, json={}).status_code == 401
        client.post("/api/session", json={"name": "Reviewer"})
        assert (
            client.post(
                path, json={}, headers={"origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert calls == []
        assert client.post(path, json={}).json() == {"opened": True}
        folder = str((settings.scan_root / "demo").resolve())
        if drive.sys.platform == "win32":
            assert calls == [folder]
        else:
            command = "open" if drive.sys.platform == "darwin" else "xdg-open"
            assert calls == [(([command, folder],), {"check": True, "timeout": 10})]
        assert (
            client.post("/api/scan-batches/unknown/open-folder", json={}).status_code
            == 404
        )


def test_open_scan_folder_rejects_symlinks_and_reports_launcher_failure(
    tmp_path, monkeypatch
):
    from survey.review import drive

    downloads, _, _ = fixture(tmp_path)
    folder = downloads.root / "demo"
    external = tmp_path / "external"
    external.mkdir()
    folder.rmdir()
    folder.symlink_to(external, target_is_directory=True)
    with pytest.raises(ReviewError, match="real region folder"):
        downloads.open_folder("demo")
    folder.unlink()
    folder.mkdir()

    def denied(*args, **kwargs):
        raise OSError("synthetic failure")

    monkeypatch.setattr(drive.subprocess, "run", denied)
    monkeypatch.setattr(drive.os, "startfile", denied, raising=False)
    with pytest.raises(ReviewError) as error:
        downloads.open_folder("demo")
    assert error.value.code == "scan_folder_open_failed"
    assert str(folder) in str(error.value)


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_open_scan_folder_launches_native_file_manager(tmp_path, monkeypatch, platform):
    from types import SimpleNamespace

    from survey.review import drive

    downloads, _, _ = fixture(tmp_path)
    # Treat the entire configured path as one argument, including shell characters.
    root = tmp_path / "scans with spaces & punctuation"
    (root / "demo").mkdir(parents=True)
    downloads.root = root
    calls = []
    monkeypatch.setattr(drive, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(drive.subprocess, "run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(
        drive.os, "startfile", lambda path: calls.append(path), raising=False
    )
    assert downloads.open_folder("demo") == {"opened": True}
    folder = str(root / "demo")
    if platform == "win32":
        assert calls == [folder]
    else:
        command = "open" if platform == "darwin" else "xdg-open"
        assert calls == [(([command, folder],), {"check": True, "timeout": 10})]
    (root / "demo").rmdir()
    calls.clear()
    with pytest.raises(ReviewError) as error:
        downloads.open_folder("demo")
    assert error.value.code == "missing_scan_folder"
    assert calls == []

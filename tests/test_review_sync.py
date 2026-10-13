from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from review_support import decide, git, refs, setup_review

from survey.records import RecordStore, ReviewError
from survey.review.sync import GitSync, WriterLock


def make_sync(tmp_path):
    service, settings = setup_review(tmp_path, with_git=True)
    return service, settings, GitSync(settings.data_checkout, service.store)


def test_sync_commit_push_noop_and_restart_pending(tmp_path):
    service, settings, sync = make_sync(tmp_path)
    assert sync.status()["state"] == "uploaded"
    decide(service)
    assert sync.status()["pending"]
    status = sync.sync()
    assert status["state"] == "uploaded" and not status["pending"]
    assert git(settings.data_checkout, "rev-parse", "HEAD") == git(
        tmp_path / "remote.git", "rev-parse", "review-data"
    )
    before = status["head"]
    assert sync.sync()["head"] == before
    decide(service, value="22", request_id="second")
    restarted = GitSync(
        settings.data_checkout, RecordStore(settings.data_checkout / "results")
    )
    assert restarted.status()["state"] == "waiting_to_upload"


def test_push_failure_keeps_commits_and_retries_after_restart(tmp_path, monkeypatch):
    service, settings, sync = make_sync(tmp_path)
    decide(service)
    original = sync.git

    def denied(*args, **kwargs):
        if args[0] == "push":
            raise ReviewError("git_failed", "Simulated auth failure", 503)
        return original(*args, **kwargs)

    monkeypatch.setattr(sync, "git", denied)
    status = sync.sync()
    assert status["state"] == "upload_failed" and status["pending"]
    assert not git(settings.data_checkout, "status", "--porcelain")
    assert status["head"] != git(tmp_path / "remote.git", "rev-parse", "review-data")
    restarted = GitSync(
        settings.data_checkout, RecordStore(settings.data_checkout / "results")
    )
    assert restarted.status()["pending"]
    assert restarted.sync()["state"] == "uploaded"


def test_unrelated_staged_work_and_unpushed_code_are_refused(tmp_path):
    service, settings, sync = make_sync(tmp_path)
    path = settings.data_checkout / "unrelated.txt"
    path.write_text("user work")
    git(settings.data_checkout, "add", "unrelated.txt")
    decide(service)
    assert sync.sync()["error"]["code"] == "unexpected_changes"
    git(settings.data_checkout, "commit", "-m", "Unrelated change")
    assert sync.sync()["error"]["code"] == "unexpected_commit"
    assert path.read_text() == "user work"


def other_clone(tmp_path):
    other = tmp_path / "another checkout"
    git(
        tmp_path,
        "clone",
        "--branch",
        "review-data",
        str(tmp_path / "remote.git"),
        str(other),
    )
    git(other, "config", "user.name", "Another writer")
    git(other, "config", "user.email", "another@example.invalid")
    path = other / "results" / "demo.jsonl"
    path.write_text(path.read_text() + "\n")
    git(other, "add", "results/demo.jsonl")
    git(other, "commit", "-m", "Another data change")
    git(other, "push", "origin", "review-data")
    return other


def test_remote_ahead_fast_forwards_only_when_clean(tmp_path):
    service, _settings, sync = make_sync(tmp_path)
    other = other_clone(tmp_path)
    status = sync.sync(service.reindex_history)
    assert status["state"] == "uploaded"
    assert status["head"] == git(other, "rev-parse", "HEAD")
    decide(service)
    path = other / "results" / "demo.jsonl"
    path.write_text(path.read_text() + "\n")
    git(other, "add", "results/demo.jsonl")
    git(other, "commit", "-m", "Another data change")
    git(other, "push", "origin", "review-data")
    assert sync.sync()["error"]["code"] == "remote_ahead"
    assert service.item(refs()[1].item_id)["field"]["value"] == "09"


def test_divergence_is_not_merged_or_discarded(tmp_path):
    service, settings, sync = make_sync(tmp_path)
    decide(service)
    git(settings.data_checkout, "add", "results/demo.jsonl")
    git(settings.data_checkout, "commit", "-m", "Local data commit")
    local = git(settings.data_checkout, "rev-parse", "HEAD")
    other_clone(tmp_path)
    assert sync.sync()["error"]["code"] == "diverged"
    assert git(settings.data_checkout, "rev-parse", "HEAD") == local


def test_saves_continue_during_push_and_new_changes_stay_pending(tmp_path, monkeypatch):
    service, _settings, sync = make_sync(tmp_path)
    decide(service)
    pushing, release = Event(), Event()
    original = sync.git

    def delayed(*args, **kwargs):
        if args[0] == "push":
            pushing.set()
            assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(sync, "git", delayed)
    with ThreadPoolExecutor() as executor:
        future = executor.submit(sync.sync)
        assert pushing.wait(10)
        decide(service, value="33", request_id="during-push")
        release.set()
        status = future.result(10)
    assert status["pending"] and status["state"] == "waiting_to_upload"
    assert service.item(refs()[1].item_id)["field"]["value"] == "33"
    assert sync.sync()["state"] == "uploaded"


def test_writer_lock_second_writer_and_crash_release(tmp_path):
    path = tmp_path / "writer.lock"
    first = WriterLock(path)
    second = WriterLock(path)
    first.acquire()
    try:
        with pytest.raises(ReviewError, match="Another review"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_windows_writer_lock_does_not_read_locked_byte_and_closes_failed_handle(
    monkeypatch,
):
    import errno
    import sys
    from types import SimpleNamespace

    from survey.review import sync

    streams, held = [], set()

    class Stream:
        def __init__(self):
            self.closed = False
            self.fd = len(streams)
            streams.append(self)

        def read(self, *args):
            if held:
                raise PermissionError(
                    errno.EACCES, "Windows denied reading locked byte"
                )
            return b"0"

        def write(self, *args):
            pytest.fail("Lock initialization must not write another owner's byte")

        def seek(self, offset):
            assert offset == 0

        def fileno(self):
            return self.fd

        def close(self):
            self.closed = True

    def locking(fd, mode, length):
        assert length == 1
        if mode == 1:
            if held:
                raise PermissionError(errno.EACCES, "Lock already owned")
            held.add(fd)
        else:
            held.remove(fd)

    monkeypatch.setattr(sync, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(
        sys.modules, "msvcrt", SimpleNamespace(locking=locking, LK_NBLCK=1, LK_UNLCK=2)
    )
    path = SimpleNamespace(
        parent=SimpleNamespace(mkdir=lambda **kwargs: None), open=lambda mode: Stream()
    )
    first, second = WriterLock(path), WriterLock(path)
    first.acquire()
    try:
        with pytest.raises(ReviewError) as error:
            second.acquire()
        assert error.value.code == "writer_busy"
        assert streams[1].closed and second.stream is None
    finally:
        first.release()
    second.acquire()
    second.release()
    assert not held and all(stream.closed for stream in streams)


def test_writer_lock_open_permission_failure_is_not_reported_as_contention():
    import errno
    from types import SimpleNamespace

    def denied(mode):
        raise PermissionError(errno.EACCES, "Cannot open lock file")

    path = SimpleNamespace(
        parent=SimpleNamespace(mkdir=lambda **kwargs: None), open=denied
    )
    lock = WriterLock(path)
    with pytest.raises(PermissionError, match="Cannot open"):
        lock.acquire()
    assert lock.stream is None


def test_writer_lock_unexpected_lock_failure_closes_handle_without_masking(monkeypatch):
    import errno
    import sys
    from types import SimpleNamespace

    from survey.review import sync

    stream = SimpleNamespace(seek=lambda offset: None, fileno=lambda: 1, closed=False)
    stream.close = lambda: setattr(stream, "closed", True)

    def broken(*args):
        raise OSError(errno.EBADF, "Invalid descriptor")

    monkeypatch.setattr(sync, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(
        sys.modules, "msvcrt", SimpleNamespace(locking=broken, LK_NBLCK=1)
    )
    path = SimpleNamespace(
        parent=SimpleNamespace(mkdir=lambda **kwargs: None), open=lambda mode: stream
    )
    with pytest.raises(OSError, match="Invalid descriptor"):
        WriterLock(path).acquire()
    assert stream.closed


def test_wrong_branch_and_missing_identity(tmp_path):
    service, settings, sync = make_sync(tmp_path)
    git(settings.data_checkout, "switch", "-c", "main")
    with pytest.raises(ReviewError, match="review-data"):
        GitSync(settings.data_checkout, service.store)
    git(settings.data_checkout, "switch", "review-data")
    git(settings.data_checkout, "config", "user.name", "")
    decide(service)
    assert sync.sync()["error"]["code"] == "missing_git_identity"


def test_git_errors_never_expose_stderr_or_remote_secrets(tmp_path, monkeypatch):
    _, _, sync = make_sync(tmp_path)
    import subprocess

    def fake(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, 1, "", "https://secret-token@github.com/"
        )

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(ReviewError) as error:
        sync.git("push", "origin", "review-data")
    assert "secret-token" not in str(error.value)


def test_fetch_failure_never_commits_and_local_decisions_remain(tmp_path, monkeypatch):
    service, settings, sync = make_sync(tmp_path)
    decide(service)
    before = git(settings.data_checkout, "rev-parse", "HEAD")
    original = sync.git

    def offline(*args, **kwargs):
        if args[0] == "fetch":
            raise ReviewError("git_failed", "Simulated network outage", 503)
        return original(*args, **kwargs)

    monkeypatch.setattr(sync, "git", offline)
    status = sync.sync()
    assert status["state"] == "upload_failed" and status["pending"]
    assert git(settings.data_checkout, "rev-parse", "HEAD") == before
    assert service.item(refs()[1].item_id)["field"]["value"] == "09"


def test_lock_is_released_when_owning_process_exits(tmp_path):
    import subprocess
    import sys

    from survey.review.sync import WriterLock

    path = tmp_path / "crash.lock"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from survey.review.sync import WriterLock; import os,sys; lock=WriterLock(Path(sys.argv[1])); lock.acquire(); os._exit(0)",
            str(path),
        ],
        check=True,
    )
    lock = WriterLock(path)
    lock.acquire()
    lock.release()


@pytest.mark.parametrize("corruption", ["id", "request_id", "invalid_utf8"])
def test_invalid_incoming_snapshot_keeps_checkout_and_active_index(
    tmp_path, corruption
):
    from copy import deepcopy
    from dataclasses import replace
    from uuid import uuid4

    from review_support import write_record

    service, settings, sync = make_sync(tmp_path)
    decide(service)
    assert sync.sync()["state"] == "uploaded"
    head = git(settings.data_checkout, "rev-parse", "HEAD")
    before = deepcopy(service.store.regions)
    source_bytes = (service.store.directory / "demo.jsonl").read_bytes()
    other = other_clone(tmp_path)
    path = other / "results/other.jsonl"
    if corruption == "invalid_utf8":
        path.write_bytes(b"\xff")
    else:
        record = deepcopy(before["demo"][0][0])
        record["region"] = "other"
        event = record["dwelling"]["households"][1]["coding"]["weekly_rent"]["review"][
            "history"
        ][0]
        event["item_id"] = replace(refs()[1], region="other").item_id
        event["request_id" if corruption == "id" else "id"] = str(uuid4())
        write_record(path, record)
    git(other, "add", "results/other.jsonl")
    git(other, "commit", "-m", "Invalid incoming test dataset")
    git(other, "push", "origin", "review-data")
    status = sync.sync(service.reindex_history)
    assert status["state"] == "upload_failed"
    assert status["error"]["code"] in {"invalid_records", "invalid_history"}
    assert git(settings.data_checkout, "rev-parse", "HEAD") == head
    assert service.store.regions == before
    assert (service.store.directory / "demo.jsonl").read_bytes() == source_bytes
    assert not (service.store.directory / "other.jsonl").exists()


def test_duplicate_across_local_regions_is_not_committed_or_uploaded(tmp_path):
    from copy import deepcopy

    from review_support import write_record

    service, settings, sync = make_sync(tmp_path)
    decide(service)
    assert sync.sync()["state"] == "uploaded"
    head = git(settings.data_checkout, "rev-parse", "HEAD")
    record = deepcopy(service.store.regions["demo"][0][0])
    record["region"] = "other"
    write_record(service.store.directory / "other.jsonl", record)
    status = sync.sync()
    assert status["error"]["code"] == "invalid_history"
    assert "demo.jsonl" in status["error"]["message"]
    assert "other.jsonl" in status["error"]["message"]
    assert git(settings.data_checkout, "rev-parse", "HEAD") == head
    assert git(tmp_path / "remote.git", "rev-parse", "review-data") == head

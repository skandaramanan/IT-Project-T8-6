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


@pytest.mark.parametrize(
    ("stdout", "stderr", "code"),
    [
        (
            (
                "!\tHEAD:refs/heads/review-data\t[remote rejected] "
                "(cannot lock ref 'refs/heads/review-data': is at abc but expected def)"
            ),
            "error: failed to push some refs",
            "push_rejected",
        ),
        (
            "!\tHEAD:refs/heads/review-data\t[remote rejected] (failed to update ref)",
            "remote: error: cannot lock ref 'refs/heads/review-data': is at abc but expected def",
            "push_rejected",
        ),
        (
            "!\tHEAD:refs/heads/review-data\t[remote rejected] (failed to update ref)",
            "remote: permission denied",
            "git_failed",
        ),
        (
            "!\tHEAD:refs/heads/review-data\t[remote rejected] (hook declined)",
            "remote: branch protection rejected this push",
            "git_failed",
        ),
    ],
)
def test_stale_remote_ref_is_retryable_but_other_server_rejections_are_not(
    tmp_path, monkeypatch, stdout, stderr, code
):
    import subprocess

    _, _, sync = make_sync(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, stdout, stderr),
    )
    with pytest.raises(ReviewError) as error:
        sync.git("push", "--porcelain", "origin", "review-data")
    assert error.value.code == code
    assert stderr not in str(error.value)


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


def region_reviewers(tmp_path):
    """Two independent validated checkouts of a two-region data branch."""
    from dataclasses import replace

    from review_support import synthetic_record, write_record

    from survey.review.scans import LocalScanSource
    from survey.review.service import ReviewService

    first, settings, first_sync = make_sync(tmp_path)
    record = synthetic_record()
    record["region"] = "other"
    write_record(first.store.directory / "other.jsonl", record)
    git(settings.data_checkout, "add", "results/other.jsonl")
    git(settings.data_checkout, "commit", "-m", "Seed another region")
    git(settings.data_checkout, "push", "origin", "review-data")
    first.store.reload()
    first.reindex_history()
    checkout = tmp_path / "second"
    git(
        tmp_path,
        "clone",
        "--branch",
        "review-data",
        str(tmp_path / "remote.git"),
        str(checkout),
    )
    git(checkout, "config", "user.name", "Second reviewer")
    git(checkout, "config", "user.email", "second@example.invalid")
    scans = tmp_path / "second-scans"
    from review_support import synthetic_pdf

    synthetic_pdf(scans / "other/synthetic.pdf")
    second_refs = [replace(ref, region="other") for ref in refs()]
    second = ReviewService(
        RecordStore(checkout / "results"),
        second_refs,
        [],
        LocalScanSource(scans, tmp_path / "second-cache"),
    )
    return first, first_sync, second, GitSync(checkout, second.store), second_refs[1]


@pytest.mark.parametrize("committed", [False, True])
def test_two_clones_share_different_regions_without_losing_history(tmp_path, committed):
    first, first_sync, second, second_sync, second_ref = region_reviewers(tmp_path)
    a = decide(first, value="11")
    b = decide(second, ref=second_ref, value="22", request_id="second-reviewer")
    if committed:
        git(second_sync.checkout, "add", "results/other.jsonl")
        git(second_sync.checkout, "commit", "-m", "Unpushed regional review")
    assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
    assert second_sync.sync(second.reindex_history)["state"] == "uploaded"
    assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
    for service in (first, second):
        assert service.store.current(refs()[1])[0].field["value"] == "11"
        assert service.store.current(second_ref)[0].field["value"] == "22"
        assert a["decision"]["id"] in service.decisions
        assert b["decision"]["id"] in service.decisions
    assert git(first_sync.checkout, "rev-parse", "HEAD") == git(
        second_sync.checkout, "rev-parse", "HEAD"
    )


def test_push_race_retries_once_and_retains_decisions_saved_during_push(
    tmp_path, monkeypatch
):
    first, first_sync, second, second_sync, second_ref = region_reviewers(tmp_path)
    decide(first, value="11")
    decide(second, ref=second_ref, value="22", request_id="second-reviewer")
    original = second_sync.git
    pushes = []

    def raced(*args, **kwargs):
        if args[0] == "push":
            pushes.append(args)
            if len(pushes) == 1:
                assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
                decide(second, ref=second_ref, value="33", request_id="during-push")
        return original(*args, **kwargs)

    monkeypatch.setattr(second_sync, "git", raced)
    assert second_sync.sync(second.reindex_history)["state"] == "uploaded"
    assert len(pushes) == 2
    assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
    assert first.store.current(second_ref)[0].field["value"] == "33"
    assert len(first.store.current(second_ref)[0].field["review"]["history"]) == 2


def test_repeated_push_race_stops_after_one_retry(tmp_path, monkeypatch):
    first, first_sync, second, second_sync, second_ref = region_reviewers(tmp_path)
    decide(second, ref=second_ref, value="22", request_id="second-reviewer")
    original = second_sync.git
    attempts = []

    def raced(*args, **kwargs):
        if args[0] == "push":
            attempts.append(args)
            decide(
                first, value=str(len(attempts) + 10), request_id=f"race-{len(attempts)}"
            )
            assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
        return original(*args, **kwargs)

    monkeypatch.setattr(second_sync, "git", raced)
    status = second_sync.sync(second.reindex_history)
    assert status["error"]["code"] == "push_rejected" and status["pending"]
    assert len(attempts) == 2
    assert second.item(second_ref.item_id)["field"]["value"] == "22"


def test_incoming_validation_does_not_block_local_saves(tmp_path, monkeypatch):
    first, first_sync, second, second_sync, second_ref = region_reviewers(tmp_path)
    decide(first, value="11")
    assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
    validating, release = Event(), Event()
    original = second_sync.validate_snapshot

    def delayed(*args):
        validating.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(second_sync, "validate_snapshot", delayed)
    with ThreadPoolExecutor() as executor:
        future = executor.submit(second_sync.sync, second.reindex_history)
        assert validating.wait(10)
        try:
            save = executor.submit(
                decide, second, second_ref, value="33", request_id="during-validation"
            )
            assert save.result(5)["saved_locally"]
        finally:
            release.set()
        assert future.result(10)["state"] == "uploaded"
    assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
    assert first.store.current(second_ref)[0].field["value"] == "33"


def test_sync_validates_only_changed_incoming_regions(tmp_path, monkeypatch):
    from survey.review import sync as module

    first, first_sync, second, second_sync, second_ref = region_reviewers(tmp_path)
    decide(first, value="11")
    assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
    original = module.parse_records
    regions = []

    def observed(raw, region, name):
        regions.append(region)
        return original(raw, region, name)

    monkeypatch.setattr(module, "parse_records", observed)
    assert second_sync.sync(second.reindex_history)["state"] == "uploaded"
    assert regions == ["demo"]
    regions.clear()
    decide(second, ref=second_ref, value="22", request_id="second-reviewer")
    assert second_sync.sync(second.reindex_history)["state"] == "uploaded"
    assert regions == []


def test_same_region_different_fields_still_require_manual_reconciliation(tmp_path):
    from review_support import synthetic_pdf

    first, first_sync, second, second_sync, _ = region_reviewers(tmp_path)
    synthetic_pdf(second.scans.root / "demo/synthetic.pdf")
    second.replace_queue(refs(), [])
    decide(first, value="11")
    decide(second, ref=refs()[2], action="accept", request_id="garden-review")
    before = (second.store.directory / "demo.jsonl").read_bytes()
    head = git(second_sync.checkout, "rev-parse", "HEAD")
    assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
    status = second_sync.sync(second.reindex_history)
    assert status["error"]["code"] == "remote_ahead"
    assert (second.store.directory / "demo.jsonl").read_bytes() == before
    assert git(second_sync.checkout, "rev-parse", "HEAD") == head


def test_new_audit_collision_during_incoming_validation_is_rechecked(
    tmp_path, monkeypatch
):
    from survey.review import prepared_service, service

    first, first_sync, second, second_sync, second_ref = region_reviewers(tmp_path)
    remote_decision = decide(first, value="11")["decision"]
    assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
    original = second_sync.validate_snapshot

    def raced(*args):
        candidate = original(*args)
        for module in (service, prepared_service):
            monkeypatch.setattr(module, "uuid4", lambda: remote_decision["id"])
        decide(second, ref=second_ref, value="22", request_id="colliding-event")
        return candidate

    monkeypatch.setattr(second_sync, "validate_snapshot", raced)
    head = git(second_sync.checkout, "rev-parse", "HEAD")
    status = second_sync.sync(second.reindex_history)
    assert status["error"]["code"] == "invalid_history"
    assert git(second_sync.checkout, "rev-parse", "HEAD") == head
    assert second.store.current(second_ref)[0].field["value"] == "22"
    assert second.store.current(refs()[1])[0].field["value"] == "12"


def test_same_region_save_during_validation_stops_before_git_changes(
    tmp_path, monkeypatch
):
    from review_support import synthetic_pdf

    first, first_sync, second, second_sync, _ = region_reviewers(tmp_path)
    synthetic_pdf(second.scans.root / "demo/synthetic.pdf")
    second.replace_queue(refs(), [])
    decide(first, value="11")
    assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
    original = second_sync.validate_snapshot

    def raced(*args):
        candidate = original(*args)
        decide(second, ref=refs()[2], action="accept", request_id="during-validation")
        return candidate

    monkeypatch.setattr(second_sync, "validate_snapshot", raced)
    head = git(second_sync.checkout, "rev-parse", "HEAD")
    status = second_sync.sync(second.reindex_history)
    assert status["error"]["code"] == "remote_ahead"
    assert git(second_sync.checkout, "rev-parse", "HEAD") == head
    assert second.item(refs()[2].item_id)["review_state"] == "accepted"
    assert second.item(refs()[1].item_id)["field"]["value"] == "12"


def test_same_region_push_race_preserves_both_reviewers_commits(tmp_path, monkeypatch):
    from review_support import synthetic_pdf

    first, first_sync, second, second_sync, _ = region_reviewers(tmp_path)
    synthetic_pdf(second.scans.root / "demo/synthetic.pdf")
    second.replace_queue(refs(), [])
    decide(second, value="22", request_id="second-reviewer")
    original = second_sync.git
    pushes = []

    def raced(*args, **kwargs):
        if args[0] == "push":
            pushes.append(args)
            decide(first, ref=refs()[2], action="accept", request_id="racing-reviewer")
            assert first_sync.sync(first.reindex_history)["state"] == "uploaded"
        return original(*args, **kwargs)

    monkeypatch.setattr(second_sync, "git", raced)
    status = second_sync.sync(second.reindex_history)
    assert status["error"]["code"] == "diverged" and status["pending"]
    assert len(pushes) == 1
    assert second.item(refs()[1].item_id)["field"]["value"] == "22"
    assert first.item(refs()[2].item_id)["review_state"] == "accepted"
    assert git(first_sync.checkout, "rev-parse", "HEAD") != git(
        second_sync.checkout, "rev-parse", "HEAD"
    )


def test_incoming_region_with_other_schema_is_refused_before_install(
    tmp_path, monkeypatch
):
    import review_support
    from review_support import card_record, legacy, write_record

    monkeypatch.setattr(review_support, "PREPARED", True)
    service, settings, sync = make_sync(tmp_path)
    head = git(settings.data_checkout, "rev-parse", "HEAD")
    before = dict(service.store.regions)
    other = other_clone(tmp_path)
    record = legacy(card_record())
    record["region"] = "other"
    write_record(other / "results/other.jsonl", record)
    git(other, "add", "results/other.jsonl")
    git(other, "commit", "-m", "Published-schema region")
    git(other, "push", "origin", "review-data")
    status = sync.sync(service.reindex_history)
    assert status["error"]["code"] == "review_preparation_required"
    assert git(settings.data_checkout, "rev-parse", "HEAD") == head
    assert service.store.regions == before

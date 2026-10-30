"""Normal Git sharing of allowlisted JSONL, with network outside the save lock."""

import errno
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from survey.extraction.record import SCHEMA_VERSION
from survey.records import (
    REGION,
    PreparedRegions,
    RecordStore,
    ReviewError,
    digest,
    parse_records,
    prepare_regions,
    read_records,
)


def check_one_schema(regions):
    """One ownership model per dataset: published 0.6.0 data keeps the shared
    first-card reviewer until a prepared 0.7.0 seed is adopted."""
    prepared = {
        r["schema_version"] == SCHEMA_VERSION
        for records, _ in regions.values()
        for r in records
    }
    if len(prepared) > 1:
        raise ReviewError(
            "review_preparation_required",
            "The review dataset mixes prepared schema 0.7.0 and published records; adopt one prepared seed for every region",
        )


class WriterLock:
    """OS advisory lock, released even after a process crash (Windows/POSIX)."""

    def __init__(self, path: Path):
        self.path, self.stream = path, None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            # Windows locks prevent reads of another owner's byte too. Acquire
            # before any content I/O; msvcrt can lock a byte beyond EOF.
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            raise ReviewError(
                "writer_busy", "Another review application owns this checkout", 409
            ) from error
        self.stream = stream

    def release(self):
        if self.stream:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None


class GitSync:
    def __init__(self, checkout: Path, store: RecordStore, branch: str = "review-data"):
        self.checkout, self.store, self.branch = checkout.resolve(), store, branch
        self.sync_lock = Lock()
        self.error = None
        self.pushing = False
        self.pushed_sha = None
        self.pushed_at = None
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch) or branch in {
            "main",
            "master",
        }:
            raise ReviewError(
                "invalid_branch", "Review must use a dedicated data branch"
            )
        self.git("check-ref-format", "--branch", branch)
        if Path(self.git("rev-parse", "--show-toplevel")).resolve() != self.checkout:
            raise ReviewError(
                "invalid_checkout",
                "Data path must be the root of a separate Git checkout",
            )
        self.verify_checkout()
        lock_path = Path(self.git("rev-parse", "--git-path", "review-writer.lock"))
        self.writer_lock = WriterLock(
            lock_path if lock_path.is_absolute() else self.checkout / lock_path
        )

    def git(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.checkout), *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=40,
            env={
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "never",
                "LC_ALL": "C",
            },
        )
        if check and result.returncode:
            stale_remote_ref = (
                "[remote rejected]" in result.stdout
                and re.search(
                    r"cannot lock ref 'refs/heads/[^']+': is at [0-9a-f]+ but expected [0-9a-f]+",
                    result.stdout + "\n" + result.stderr,
                )
                is not None
            )
            if args[0] == "push" and (
                stale_remote_ref
                or any(
                    "[rejected]" in line
                    and ("(fetch first)" in line or "(non-fast-forward)" in line)
                    for line in result.stdout.splitlines()
                )
            ):
                raise ReviewError(
                    "push_rejected", "Data branch advanced during sharing", 409
                )
            # stderr/remote URLs may contain credentials; never return them to the UI.
            raise ReviewError(
                "git_failed",
                f"Git {args[0]} failed; check local credentials, branch rules, and connectivity",
                503,
            )
        return result.stdout.strip()

    def verify_checkout(self):
        if self.git("branch", "--show-current") != self.branch:
            raise ReviewError(
                "wrong_branch",
                f"Data checkout must be on {self.branch}; no main data commits are allowed",
            )
        if not self.git("remote", "get-url", "origin"):
            raise ReviewError("missing_remote", "Configure the data checkout origin")
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir"))
        if any(
            (git_dir / marker).exists()
            for marker in (
                "MERGE_HEAD",
                "rebase-merge",
                "rebase-apply",
                "CHERRY_PICK_HEAD",
            )
        ):
            raise ReviewError(
                "git_conflict",
                "Finish or resolve the existing Git operation before reviewing",
                409,
            )
        if self.git("ls-files", "-u"):
            raise ReviewError(
                "git_conflict", "Data checkout contains unresolved conflicts", 409
            )

    @staticmethod
    def allowed(path: str) -> bool:
        return (
            path.startswith("results/")
            and path.count("/") == 1
            and path.endswith(".jsonl")
            and bool(REGION.fullmatch(Path(path).stem))
        )

    def changes(self) -> list[tuple[str, str]]:
        # Do not strip the leading space of porcelain's unstaged columns.
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.checkout),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return [(row[:2], row[3:]) for row in result.stdout.split("\0") if row]

    def remote_sha(self) -> str:
        return self.git(
            "rev-parse", "--verify", f"refs/remotes/origin/{self.branch}", check=False
        )

    def ancestor(self, older: str, newer: str) -> bool:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.checkout),
                "merge-base",
                "--is-ancestor",
                older,
                newer,
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode not in (0, 1):
            raise ReviewError("git_failed", "Cannot compare data branch history", 503)
        return result.returncode == 0

    def validate_snapshot(self, revision: str, paths: set[str]) -> PreparedRegions:
        """Validate only changed immutable incoming blobs, outside the save lock."""
        candidate = {}
        for path in sorted(paths):
            entry = self.git("ls-tree", revision, "--", path)
            if not entry:
                raise ReviewError(
                    "invalid_path",
                    "Deleting region data requires manual reconciliation",
                )
            metadata, found = entry.split("\t", 1)
            mode, kind, blob = metadata.split()
            if (
                found != path
                or not self.allowed(path)
                or mode not in {"100644", "100755"}
                or kind != "blob"
            ):
                raise ReviewError(
                    "invalid_path", "Remote contains an unsupported region JSONL path"
                )
            result = subprocess.run(
                ["git", "-C", str(self.checkout), "cat-file", "blob", blob],
                capture_output=True,
                timeout=40,
                check=False,
            )
            if result.returncode:
                raise ReviewError(
                    "git_failed", "Cannot read incoming region records", 503
                )
            region = Path(path).stem
            candidate[region] = parse_records(result.stdout, region, path)
        return prepare_regions(candidate) if candidate else PreparedRegions({}, {}, {})

    def upstream_paths(self, base: str, remote: str) -> set[str]:
        rows = self.git(
            "diff", "--name-status", "--no-renames", base, remote
        ).splitlines()
        paths = set()
        for row in rows:
            status, path = row.split("\t", 1)
            if status not in {"A", "M"} or not self.allowed(path):
                raise ReviewError(
                    "unexpected_changes",
                    "Incoming changes require manual reconciliation",
                    409,
                )
            paths.add(path)
        return paths

    def outgoing_paths(self, base: str, head: str) -> set[str]:
        paths = set()
        for commit in self.git("rev-list", f"{base}..{head}").splitlines():
            if len(self.git("rev-list", "--parents", "-n", "1", commit).split()) > 2:
                raise ReviewError(
                    "unexpected_commit",
                    "Unpushed merge commits require manual reconciliation",
                    409,
                )
            rows = self.git(
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--name-status",
                "--no-renames",
                "-r",
                commit,
            ).splitlines()
            if not rows:
                raise ReviewError(
                    "unexpected_commit",
                    "Unpushed commits must contain region changes",
                    409,
                )
            for row in rows:
                status, path = row.split("\t", 1)
                if status not in {"A", "M"} or not self.allowed(path):
                    raise ReviewError(
                        "unexpected_commit",
                        "Unpushed commits must contain only region JSONL changes",
                        409,
                    )
                paths.add(path)
        return paths

    def checked_changes(self):
        changes = self.changes()
        if any(
            not self.allowed(path) or any(c in columns for c in "DRCU")
            for columns, path in changes
        ):
            raise ReviewError(
                "unexpected_changes",
                "Sync refuses unrelated, renamed, deleted, or conflicted paths; local work is retained",
                409,
            )
        return changes

    def share_snapshot(self, reload_callback=None) -> tuple[str, str]:
        """Prepare remotely validated changes while local decisions can continue."""
        self.verify_checkout()
        self.git(
            "fetch",
            "--no-tags",
            "origin",
            f"refs/heads/{self.branch}:refs/remotes/origin/{self.branch}",
        )
        remote = self.remote_sha()
        if not remote:
            raise ReviewError(
                "missing_remote_branch",
                "Admin must provision the data branch before sharing",
            )
        with self.store.lock:
            head = self.git("rev-parse", "HEAD")
            changes = self.checked_changes()
            versions = {
                region: version for region, (_, version) in self.store.regions.items()
            }
        base = self.git("merge-base", head, remote)
        incoming_paths = self.upstream_paths(base, remote)
        outgoing_paths = self.outgoing_paths(base, head)
        local_paths = outgoing_paths | {path for _, path in changes}
        if incoming_paths & local_paths:
            raise ReviewError(
                "remote_ahead" if self.ancestor(head, remote) else "diverged",
                "Both reviewers changed the same region; reconcile manually. Local work is retained",
                409,
            )
        candidate = self.validate_snapshot(remote, incoming_paths)
        # Added external region files are not trusted merely because Git permits them.
        additions = {}
        for _, path in changes:
            region = Path(path).stem
            if region not in versions:
                additions[region] = read_records(self.checkout / path, region)
        if additions:
            candidate = prepare_regions({**candidate.regions, **additions})
        # Cheap hashes detect external tools without repeating schema validation.
        observed = {
            region: digest((self.store.directory / f"{region}.jsonl").read_bytes())
            for region in versions
        }
        with self.store.lock:
            self.verify_checkout()
            if self.git("rev-parse", "HEAD") != head:
                raise ReviewError(
                    "git_conflict",
                    "Checkout history changed externally; local work retained",
                    409,
                )
            changes = self.checked_changes()
            if incoming_paths & ({path for _, path in changes} | outgoing_paths):
                raise ReviewError(
                    "remote_ahead",
                    "Same-region edits arrived during sharing; reconcile manually",
                    409,
                )
            for region, version in versions.items():
                current_version = self.store.regions[region][1]
                actual = observed[region]
                if current_version != version:
                    actual = digest(
                        (self.store.directory / f"{region}.jsonl").read_bytes()
                    )
                if actual != current_version:
                    raise ReviewError(
                        "external_change",
                        "An external writer changed this region; restart before sharing",
                        409,
                    )
            for _, path in changes:
                region = Path(path).stem
                if region in self.store.regions:
                    self.store.check_version(region, self.store.regions[region][1])
                elif region not in additions:
                    raise ReviewError(
                        "external_change",
                        "Unvalidated region appeared during sharing",
                        409,
                    )
            for region, (_, version) in additions.items():
                if (
                    digest((self.store.directory / f"{region}.jsonl").read_bytes())
                    != version
                ):
                    raise ReviewError(
                        "external_change",
                        "External region changed during validation",
                        409,
                    )
            check_one_schema({**self.store.regions, **candidate.regions})
            self.store.check_audits(candidate)
            if changes:
                if not self.git("config", "user.name", check=False) or not self.git(
                    "config", "user.email", check=False
                ):
                    raise ReviewError(
                        "missing_git_identity",
                        "Configure Git user.name and user.email on this machine",
                    )
                self.git("add", "--", *(path for _, path in changes))
                self.git("commit", "-m", "review: save reviewed region records")
                head = self.git("rev-parse", "HEAD")
            if incoming_paths:
                if self.ancestor(head, remote):
                    self.git("merge", "--ff-only", remote)
                else:
                    try:
                        self.git("rebase", "--onto", remote, base)
                    except ReviewError:
                        self.git("rebase", "--abort", check=False)
                        raise ReviewError(
                            "git_conflict",
                            "Rebase failed; local commits retained for manual reconciliation",
                            409,
                        ) from None
            elif head != remote and not self.ancestor(remote, head):
                # Even an upstream commit with no net file changes must be incorporated.
                try:
                    self.git("rebase", "--onto", remote, base)
                except ReviewError:
                    self.git("rebase", "--abort", check=False)
                    raise ReviewError(
                        "git_conflict", "Rebase failed; local commits retained", 409
                    ) from None
            for region, (records, _) in candidate.regions.items():
                candidate.regions[region] = (
                    records,
                    digest((self.store.directory / f"{region}.jsonl").read_bytes()),
                )
            if candidate.regions:
                self.store.install(candidate)
                if reload_callback:
                    reload_callback(set(candidate.regions))
            return self.git("rev-parse", "HEAD"), remote

    def status(self) -> dict:
        with self.store.lock:
            try:
                self.verify_checkout()
                head, remote = self.git("rev-parse", "HEAD"), self.remote_sha()
                changes = self.changes()
                pending = bool(changes) or head != remote
                return {
                    "state": "upload_failed"
                    if self.error
                    else "uploading"
                    if self.pushing
                    else "waiting_to_upload"
                    if pending
                    else "uploaded",
                    "pending": pending,
                    "head": head,
                    "known_remote_sha": remote or None,
                    "pushed_sha": self.pushed_sha,
                    "pushed_at": self.pushed_at,
                    "error": self.error,
                }
            except (ReviewError, OSError, subprocess.SubprocessError) as error:
                return {
                    "state": "upload_failed",
                    "pending": True,
                    "error": {
                        "code": getattr(error, "code", "git_failed"),
                        "message": str(error)
                        if isinstance(error, ReviewError)
                        else "Git is unavailable",
                    },
                }

    def sync(self, reload_callback=None) -> dict:
        if not self.sync_lock.acquire(blocking=False):
            return self.status()
        self.pushing = True
        try:
            for attempt in range(2):
                snapshot, remote = self.share_snapshot(reload_callback)
                if snapshot != remote:
                    try:
                        self.git(
                            "push",
                            "--porcelain",
                            "origin",
                            f"{snapshot}:refs/heads/{self.branch}",
                        )
                    except ReviewError as error:
                        if error.code == "push_rejected" and attempt == 0:
                            continue
                        raise
                self.pushed_sha = snapshot
                self.pushed_at = datetime.now(UTC).isoformat()
                self.error = None
                break
        except (ReviewError, OSError, subprocess.SubprocessError) as error:
            self.error = {
                "code": getattr(error, "code", "git_failed"),
                "message": str(error)
                if isinstance(error, ReviewError)
                else "Git timed out or is unavailable; local changes retained",
            }
        finally:
            self.pushing = False
            self.sync_lock.release()
        return self.status()

"""Normal Git sharing of allowlisted JSONL, with network outside the save lock."""

import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from survey.records import REGION, RecordStore, ReviewError, read_records


class WriterLock:
    """OS advisory lock, released even after a process crash (Windows/POSIX)."""

    def __init__(self, path: Path):
        self.path, self.stream = path, None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
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
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
        )
        if check and result.returncode:
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
            self.verify_checkout()
            self.git(
                "fetch",
                "--no-tags",
                "origin",
                f"refs/heads/{self.branch}:refs/remotes/origin/{self.branch}",
            )
            with self.store.lock:
                self.verify_checkout()
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
                head, remote = self.git("rev-parse", "HEAD"), self.remote_sha()
                if not remote:
                    raise ReviewError(
                        "missing_remote_branch",
                        "Admin must provision the data branch before sharing",
                    )
                if head != remote:
                    if self.ancestor(head, remote):
                        if changes:
                            raise ReviewError(
                                "remote_ahead",
                                "Remote has new data and local edits exist; reconcile manually",
                                409,
                            )
                        self.git("merge", "--ff-only", remote)
                        self.store.reload()
                        if reload_callback:
                            reload_callback()
                        head = remote
                    elif not self.ancestor(remote, head):
                        raise ReviewError(
                            "diverged",
                            "Local and remote data histories diverged; manual reconciliation required",
                            409,
                        )
                for region, (_, version) in self.store.regions.items():
                    self.store.check_version(region, version)
                for path in self.store.directory.glob("*.jsonl"):
                    if path.is_symlink() or not REGION.fullmatch(path.stem):
                        raise ReviewError(
                            "invalid_path",
                            "Sync refuses symlinks or non-region JSONL names",
                        )
                    read_records(path, path.stem)
                outgoing = self.git("rev-list", f"{remote}..{head}").splitlines()
                for commit in outgoing:
                    paths = self.git(
                        "diff-tree",
                        "--root",
                        "--no-commit-id",
                        "--name-only",
                        "-r",
                        commit,
                    ).splitlines()
                    if not paths or any(not self.allowed(path) for path in paths):
                        raise ReviewError(
                            "unexpected_commit",
                            "Unpushed commits must contain only region JSONL changes",
                            409,
                        )
                if changes:
                    if not self.git("config", "user.name", check=False) or not self.git(
                        "config", "user.email", check=False
                    ):
                        raise ReviewError(
                            "missing_git_identity",
                            "Configure Git user.name and user.email on this machine",
                        )
                    paths = [path for _, path in changes]
                    self.git("add", "--", *paths)
                    self.git("commit", "-m", "review: save reviewed region records")
                snapshot = self.git("rev-parse", "HEAD")
            # Saves can proceed during this network call. Push the captured commit.
            if snapshot != remote:
                self.git("push", "origin", f"{snapshot}:refs/heads/{self.branch}")
            self.pushed_sha = snapshot
            self.pushed_at = datetime.now(UTC).isoformat()
            self.error = None
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

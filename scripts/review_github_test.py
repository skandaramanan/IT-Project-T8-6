"""Opt-in review acceptance against a disposable local remote or GitHub review-data.

Run --help; ordinary pytest and CI never invoke this live-writing tool.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import runpy
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager, redirect_stdout
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from survey.cli import load_env
from survey.records import Reference, read_dataset, read_records, resolve_field

CODE = Path(__file__).resolve().parents[1]
REPOSITORY = "skandaramanan/IT-Project-T8-6"
BRANCH = "review-data"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(*args, cwd=None, timeout=120):
    result = subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
    )
    # Do not echo stderr: Git/network errors can contain credential-bearing URLs.
    require(
        result.returncode == 0,
        f"{Path(str(args[0])).name} {args[1]} failed (exit {result.returncode})",
    )
    return result.stdout.strip()


def git(path, *args):
    return command("git", "-C", path, *args)


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def wait_for(predicate, timeout=60, interval=0.25):
    end = time.monotonic() + timeout
    while True:
        result = predicate()
        if result:
            return result
        require(time.monotonic() < end, f"Condition not satisfied within {timeout}s")
        time.sleep(interval)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def prepare(args):
    root = args.workspace.resolve()
    require(not root.exists(), "Workspace must be new; existing work is never replaced")
    require(
        not root.is_relative_to(CODE), "Workspace must be outside the code checkout"
    )
    require(
        args.local or not git(CODE, "status", "--porcelain"),
        "Commit the tooling first: preparation pins a clean code revision",
    )
    base = git(CODE, "rev-parse", "HEAD")
    remote = (
        str(root / "remote.git") if args.local else f"git@github.com:{REPOSITORY}.git"
    )
    if not args.local:
        require(
            not git(CODE, "ls-remote", "--heads", remote, BRANCH),
            "review-data already exists; inspect it rather than overwrite it",
        )
    root.mkdir(parents=True)
    scan_root = root / "scans"
    scan_root.mkdir()
    # Reuse the established five-flag, four-page demo rather than inventing records.
    with redirect_stdout(io.StringIO()):
        runpy.run_path(str(CODE / "scripts/review_demo.py"))["create_demo"](
            root / "demo"
        )
    template = json.loads((root / "demo/data checkout/results/demo.jsonl").read_text())
    flags = [
        json.loads(line)
        for line in (root / "demo/flags.jsonl").read_text().splitlines()
    ]
    seed = root / "provision"
    command("git", "clone", "--no-hardlinks", CODE, seed)
    git(seed, "switch", "-c", BRANCH, base)
    git(seed, "config", "user.name", "Review acceptance setup")
    git(seed, "config", "user.email", "review-acceptance@example.invalid")
    shutil.rmtree(seed / "results")
    (seed / "results").mkdir()
    queue = []
    for region in ("demo-a", "demo-b"):
        record = deepcopy(template)
        record["region"] = region
        (seed / "results" / f"{region}.jsonl").write_text(json.dumps(record) + "\n")
        (scan_root / region).mkdir()
        shutil.copyfile(
            root / "demo/scans/demo/synthetic.pdf", scan_root / region / "synthetic.pdf"
        )
        queue.extend({**flag, "region": region} for flag in flags)
    sources = []
    if not args.synthetic_only:
        source = CODE / "results/216418.jsonl"
        original_scans = args.scan_root.resolve()
        sample = runpy.run_path(str(CODE / "scripts/review_sample.py"))["select_sample"]
        records, _ = read_records(source, "216418")
        selected, real_flags, _ = sample(
            records, "216418", ["Weekly Rent", "Age of Head"], 2
        )
        require(len(selected) == 2, "Expected two complete sample dwellings")
        (seed / "results/216418.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected)
        )
        (scan_root / "216418").mkdir()
        for pdf in sorted({flag["pdf"] for flag in real_flags}):
            original = original_scans / "216418" / pdf
            require(original.is_file(), f"Missing original scan: {original}")
            # Copy scans: the scan resolver rejects symlinks outside scan_root.
            shutil.copyfile(original, scan_root / "216418" / pdf)
            sources.append({"path": str(original), "sha256": sha(original)})
        sources.append({"path": str(source), "sha256": sha(source)})
        queue.extend(real_flags)
    (root / "flags.jsonl").write_text(
        "".join(json.dumps(flag) + "\n" for flag in queue)
    )
    read_dataset(sorted((seed / "results").glob("*.jsonl")))
    git(seed, "add", "results")
    git(seed, "commit", "-m", "Seed provisional review acceptance data")
    if args.local:
        command("git", "init", "--bare", remote)
    git(seed, "remote", "set-url", "origin", remote)
    # Recheck immediately before push; no force and no replacement of existing data.
    require(
        not git(seed, "ls-remote", "--heads", "origin", BRANCH),
        "review-data appeared during preparation",
    )
    git(
        seed,
        "push",
        "origin",
        "HEAD:refs/heads/review-data",
    )
    manifest = {
        "version": 1,
        "repository": REPOSITORY,
        "branch": BRANCH,
        "remote": remote,
        "local": args.local,
        "code_sha": base,
        "seed_sha": git(seed, "rev-parse", "HEAD"),
        "sources": sources,
        "real_sample": not args.synthetic_only,
        "code_dirty": bool(git(CODE, "status", "--porcelain")),
    }
    write_json(root / "manifest.json", manifest)
    print(f"Prepared {root}; retained provisional branch {BRANCH}")


class Backend:
    def __init__(self, root, checkout, name, interval=3600):
        self.root, self.checkout, self.name, self.interval = (
            root,
            checkout,
            name,
            interval,
        )
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.process = None
        self.client = None

    def start(self):
        self.log = (self.checkout.parent / f"{self.checkout.name}.log").open("a")
        # survey.cli is not an executable module; use the installed console's callable.
        args = [
            sys.executable,
            "-c",
            "from survey.cli import main; raise SystemExit(main())",
            "review",
            "--scan-root",
            str(self.root / "scans"),
            "--data-checkout",
            str(self.checkout),
            "--flags",
            str(self.root / "flags.jsonl"),
            "--cache",
            str(self.checkout.parent / f"{self.checkout.name}-cache"),
            "--data-branch",
            BRANCH,
            "--port",
            str(self.port),
            "--sync-interval",
            str(self.interval),
        ]
        # Explicit flags win over production .env; no Drive key is needed by these tests.
        env = {**os.environ, "SURVEY_REVIEW_DRIVE_API_KEY": "", "PYTHONUNBUFFERED": "1"}
        self.process = subprocess.Popen(
            args, cwd=CODE, stdout=self.log, stderr=self.log, env=env
        )
        self.client = httpx.Client(base_url=self.url, timeout=120, trust_env=False)

        def healthy():
            require(
                self.process.poll() is None, f"Backend exited; inspect {self.log.name}"
            )
            try:
                response = self.client.get("/api/health", timeout=1)
            except httpx.TransportError:
                return False
            health = response.json()
            require(
                health["ready"], f"Backend startup diagnostics: {health['diagnostics']}"
            )
            return True

        wait_for(healthy)
        self.post("/api/session", {"name": self.name})
        return self

    def stop(self):
        if self.client:
            self.client.close()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        if hasattr(self, "log"):
            self.log.close()

    def restart(self):
        self.stop()
        self.start()

    def get(self, path):
        response = self.client.get(path)
        return self.response(response)

    def post(self, path, body):
        response = self.client.post(path, json=body, headers={"Origin": self.url})
        return self.response(response)

    @staticmethod
    def response(response):
        if not response.is_success:
            try:
                code = response.json().get("error", {}).get("code", "unknown_error")
            except ValueError:
                code = "non_json_error"
            raise RuntimeError(f"Review API HTTP {response.status_code}: {code}")
        return response.json()

    def items(self, region="demo-a"):
        return self.get(f"/api/queue?region={region}")["items"]

    def decide(self, item, action="correct", value="009"):
        current = self.get(f"/api/review-items/{item['id']}")
        scan = self.client.get(current["scan_url"])
        require(
            scan.status_code == 200 and scan.headers["content-type"] == "image/png",
            "Scan failed to render",
        )
        body = {
            "action": action,
            "expected_version": current["version"],
            "request_id": str(uuid4()),
        }
        if action == "correct":
            body["value"] = value
        result = self.post(f"/api/review-items/{item['id']}/decisions", body)
        require(result["saved_locally"], "Decision was not saved locally")
        return result

    def undo(self, result):
        item = self.get(f"/api/review-items/{result['item']['id']}")
        return self.post(
            f"/api/decisions/{result['decision']['id']}/undo",
            {"expected_version": item["version"], "request_id": str(uuid4())},
        )

    def share(self):
        status = self.post("/api/sync", {})
        require(
            status["state"] == "uploaded" and not status["pending"],
            f"Sharing failed: {status.get('error')}",
        )
        return status["head"]


class Run:
    def __init__(self, root, check_ci=True, verify_revision=True):
        self.root = root.resolve()
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        require(
            self.manifest["repository"] == REPOSITORY
            and self.manifest["branch"] == BRANCH,
            "Unexpected workspace repository/branch",
        )
        require(
            not verify_revision
            or git(CODE, "rev-parse", "HEAD") == self.manifest["code_sha"],
            "Code revision changed; commit clean code and explicitly repin this workspace",
        )
        if not self.manifest["local"]:
            require(
                self.manifest["remote"] == f"git@github.com:{REPOSITORY}.git",
                "Unexpected live remote",
            )
            require(
                not git(CODE, "status", "--porcelain"),
                "Live runs require a clean code checkout",
            )
        self.check_ci = check_ci
        self.token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self.directory = (
            self.root
            / f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:6]}"
        )
        self.directory.mkdir()
        self.results = []
        self.checkpoints = []

    def clone(self, label):
        checkout = self.directory / f"{label}-{uuid4().hex[:6]}"
        command("git", "clone", "--branch", BRANCH, self.manifest["remote"], checkout)
        require(
            git(checkout, "remote", "get-url", "origin") == self.manifest["remote"],
            "Unexpected clone remote",
        )
        git(checkout, "merge-base", "--is-ancestor", self.manifest["seed_sha"], "HEAD")
        git(checkout, "config", "user.name", f"Review acceptance {label}")
        git(checkout, "config", "user.email", f"review-{label.lower()}@example.invalid")
        return checkout

    @contextmanager
    def backend(self, label, interval=3600):
        server = Backend(self.root, self.clone(label), f"Reviewer {label}", interval)
        try:
            yield server.start()
        finally:
            server.stop()

    @contextmanager
    def failed_push(self, server):
        # Only this clone's push transport is changed. Fetch still goes to GitHub.
        previous = git(server.checkout, "config", "--get-regexp", "^remote.origin.url$")
        require(previous, "Missing remote")
        git(
            server.checkout,
            "config",
            "remote.origin.pushurl",
            str(self.directory / "missing-remote.git"),
        )
        try:
            yield
        finally:
            git(server.checkout, "config", "--unset-all", "remote.origin.pushurl")

    def verify(self, expectations=()):
        checkout = self.clone("verify")
        read_dataset(sorted((checkout / "results").glob("*.jsonl")))
        head = git(checkout, "rev-parse", "HEAD")
        # Inspect every commit: a code change later reverted is still out of scope.
        paths = [
            line
            for line in git(
                checkout,
                "log",
                "--format=",
                "--name-status",
                "--no-renames",
                f"{self.manifest['seed_sha']}..{head}",
            ).splitlines()
            if line
        ]
        require(
            all(
                line.startswith("M\tresults/")
                and line.endswith(".jsonl")
                and line.count("/") == 1
                for line in paths
            ),
            "Application commits changed unexpected paths",
        )
        for expected in expectations:
            item = expected["item"]
            records, _ = read_records(
                checkout / "results" / f"{item['region']}.jsonl", item["region"]
            )
            ref = Reference(
                item["region"],
                item["source"]["pdf"],
                item["source"]["page"],
                item["field_path"],
            )
            field = resolve_field(records, ref).field
            require(
                field["value"] == expected["value"],
                f"Remote value mismatch for {item['region']} {item['field_path']}",
            )
            history = field.get("review", {}).get("history", [])
            require(
                history and history[-1]["reviewer"] == expected["reviewer"],
                "Remote audit reviewer mismatch",
            )
            if expected.get("decision"):
                require(
                    any(event["id"] == expected["decision"] for event in history),
                    "Remote audit event missing",
                )
        self.checkpoints.append(head)
        return {
            "sha": head,
            "hashes": {p.name: sha(p) for p in (checkout / "results").glob("*.jsonl")},
        }

    def scenario(self, name, function):
        start = time.monotonic()
        try:
            detail = function() or {}
            result = {"name": name, "status": "passed", "detail": detail}
        except (
            RuntimeError,
            OSError,
            ValueError,
            httpx.HTTPError,
            subprocess.SubprocessError,
        ) as error:
            # Sanitized messages only; never include command output or request headers.
            message = (
                str(error) if isinstance(error, RuntimeError) else type(error).__name__
            )
            result = {"name": name, "status": "failed", "error": message}
        result["seconds"] = round(time.monotonic() - start, 2)
        self.results.append(result)
        self.report()
        print(f"{name}: {result['status']}", file=sys.stderr, flush=True)
        return result["status"] == "passed"

    def ci(self):
        if self.manifest["local"]:
            return {
                "status": "not_run",
                "reason": "Local bare remote has no GitHub Actions",
            }
        require(
            self.check_ci and self.token,
            "GitHub CI checks blocked: set GITHUB_TOKEN with Contents/Actions read access",
        )
        runs = []
        with httpx.Client(
            base_url=f"https://api.github.com/repos/{REPOSITORY}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30,
        ) as client:
            for checkpoint in dict.fromkeys(self.checkpoints):

                def complete(checkpoint=checkpoint):
                    response = client.get(
                        "/actions/workflows/review-data.yml/runs",
                        params={"head_sha": checkpoint, "branch": BRANCH},
                    )
                    require(
                        response.status_code == 200,
                        f"GitHub Actions lookup failed (HTTP {response.status_code})",
                    )
                    matches = response.json()["workflow_runs"]
                    if not matches or matches[0]["status"] != "completed":
                        return False
                    run = matches[0]
                    require(
                        run["conclusion"] == "success",
                        f"GitHub validation {run['conclusion']}: {run['html_url']}",
                    )
                    return {
                        "sha": checkpoint,
                        "url": run["html_url"],
                        "conclusion": run["conclusion"],
                    }

                runs.append(wait_for(complete, 600, interval=5))
        return {"runs": runs}

    def report(self):
        data = {
            "code_sha": self.manifest["code_sha"],
            "seed_sha": self.manifest["seed_sha"],
            "local": self.manifest["local"],
            "results": self.results,
            "checkpoints": list(dict.fromkeys(self.checkpoints)),
            "code_dirty": bool(git(CODE, "status", "--porcelain")),
            "acceptance_complete": not self.manifest["local"]
            and self.manifest["real_sample"]
            and bool(self.results)
            and all(r["status"] == "passed" for r in self.results),
        }
        write_json(self.directory / "report.json", data)
        (self.directory / "report.md").write_text(
            "# Review GitHub acceptance\n\n"
            + f"Code: `{data['code_sha']}`\n\n"
            + "\n".join(
                f"- {r['name']}: **{r['status']}**"
                + (f" — {r['error']}" if "error" in r else "")
                for r in self.results
            )
            + "\n"
        )

    def source_check(self):
        for source in self.manifest["sources"]:
            require(
                sha(Path(source["path"])) == source["sha256"], "Original source changed"
            )


def expected(server, result):
    return {
        "item": result["item"],
        "value": result["item"]["field"]["value"],
        "reviewer": server.name,
        "decision": result["decision"]["id"],
    }


def api_scenarios(run):
    def pending_fixtures():
        # Resume safely: undo active TEST decisions through the application, never reset Git.
        with run.backend("fixture-reset") as a:
            for region in ("demo-a", "demo-b", "216418"):
                if region == "216418" and not run.manifest["real_sample"]:
                    continue
                for item in a.items(region):
                    current = a.get(f"/api/review-items/{item['id']}")
                    while current.get("undo_decision_id"):
                        current = a.undo(
                            {
                                "item": current,
                                "decision": {"id": current["undo_decision_id"]},
                            }
                        )["item"]
            a.share()
            return run.verify()

    def decisions():
        with run.backend("decisions") as a:
            items = a.items()
            rent = next(i for i in items if i["label"] == "Weekly Rent")
            original = rent["field"]["value"]
            result = a.decide(rent)
            a.restart()
            current = a.get(f"/api/review-items/{rent['id']}")
            require(
                current["field"]["value"] == "009" and current["resolved"],
                "Restart lost correction/progress",
            )
            require(a.get("/api/sync/status")["pending"], "Restart lost pending work")
            first = a.share()
            require(a.share() == first, "No-op share created a commit")
            run.verify([expected(a, result)])
            undone = a.undo(result)
            require(
                undone["item"]["field"]["value"] == original,
                "Undo did not restore original",
            )
            a.restart()
            a.share()
            run.verify([expected(a, undone)])
            for action in ("accept", "no_data", "illegible"):
                saved = a.decide(rent, action)
                field = saved["item"]["field"]
                if action != "accept":
                    require(
                        field["value"] is None and field["status"] == action,
                        "Incorrect decision status",
                    )
                a.share()
                run.verify([expected(a, saved)])
                a.undo(saved)
                a.share()
            text = next(i for i in items if i["field_path"].endswith("/text"))
            saved = a.decide(text, value="Café — 王\nSecond line")
            a.restart()
            a.share()
            return run.verify([expected(a, saved)])

    def recovery():
        with run.backend("recovery") as a:
            result = a.decide(a.items()[1], value="018")
            with run.failed_push(a):
                status = a.post("/api/sync", {})
                require(
                    status["state"] == "upload_failed" and status["pending"],
                    "Push failure not surfaced",
                )
                retained = sha(a.checkout / "results/demo-a.jsonl")
                head = git(a.checkout, "rev-parse", "HEAD")
                a.restart()
                require(
                    sha(a.checkout / "results/demo-a.jsonl") == retained,
                    "Restart changed retained data",
                )
                require(
                    git(a.checkout, "rev-parse", "HEAD") == head
                    and a.get("/api/sync/status")["pending"],
                    "Unpushed commit lost",
                )
            a.share()
            return run.verify([expected(a, result)])

    def concurrent():
        with run.backend("A") as a, run.backend("B") as b:
            with ThreadPoolExecutor(2) as pool:
                fa = pool.submit(a.decide, a.items("demo-a")[0], value="021")
                fb = pool.submit(b.decide, b.items("demo-b")[0], value="032")
                ra, rb = fa.result(), fb.result()
                shares = [pool.submit(server.share) for server in (a, b)]
                for future in shares:
                    future.result()
            proof = run.verify([expected(a, ra), expected(b, rb)])
            for server in (a, b):
                require(server.share() == proof["sha"], "Reviewers did not converge")
                for result in (ra, rb):
                    current = server.get(f"/api/review-items/{result['item']['id']}")
                    require(
                        current["field"]["value"] == result["item"]["field"]["value"],
                        "Incoming field not installed",
                    )
            return proof

    def automatic(periodic):
        with run.backend(
            "periodic" if periodic else "completion", 5 if periodic else 3600
        ) as a:
            items = a.items("demo-b")
            # Restore an incomplete batch first, so only the final decision triggers completion.
            for item in items:
                if item.get("undo_decision_id"):
                    a.undo({"item": item, "decision": {"id": item["undo_decision_id"]}})
            a.share()
            before = git(a.checkout, "rev-parse", "HEAD")
            last = None
            for item in items[:1] if periodic else items:
                last = a.decide(item, "accept")
            wait_for(lambda: a.get("/api/sync/status")["state"] == "uploaded")
            require(
                git(a.checkout, "rev-parse", "HEAD") != before,
                "Automatic synchronization made no commit",
            )
            return run.verify([expected(a, last)])

    def conflict():
        with run.backend("conflict-A") as a, run.backend("conflict-B") as b:
            ra = a.decide(a.items()[0], value="041")
            rb = b.decide(b.items()[1], value="052")
            retained = sha(b.checkout / "results/demo-a.jsonl")
            a.share()
            status = b.post("/api/sync", {})
            require(
                status["state"] == "upload_failed"
                and status["error"]["code"] in {"remote_ahead", "diverged"},
                "Same-region changes were not refused",
            )
            require(
                sha(b.checkout / "results/demo-a.jsonl") == retained,
                "Conflict changed local bytes",
            )
            b.restart()
            require(
                b.get(f"/api/review-items/{rb['item']['id']}")["field"]["value"]
                == "052",
                "Conflict work lost after restart",
            )
            proof = run.verify([expected(a, ra)])
            return {
                **proof,
                "preserved_checkout": str(b.checkout),
                "error": status["error"]["code"],
            }

    def real():
        require(
            run.manifest["real_sample"],
            "Real sample not prepared; --synthetic-only excludes this check",
        )
        with run.backend("real") as a:
            item = next(i for i in a.items("216418") if i["label"] == "Weekly Rent")
            result = a.decide(item, value="009")
            a.restart()
            require(
                a.get(f"/api/review-items/{item['id']}")["field"]["value"] == "009",
                "Real sample lost on restart",
            )
            a.share()
            run.verify([expected(a, result)])
            undone = a.undo(result)
            a.share()
            return run.verify([expected(a, undone)])

    return [
        ("prepare-pending-fixtures", pending_fixtures),
        ("decisions-restart-undo", decisions),
        ("failed-push-recovery", recovery),
        ("two-reviewers-disjoint-regions", concurrent),
        ("batch-completion", lambda: automatic(False)),
        ("periodic-sharing", lambda: automatic(True)),
        ("same-region-conflict", conflict),
        ("real-sample", real),
    ]


def browser_session(root):
    """Private stdio control channel for Playwright, never an application endpoint."""
    run = Run(root, check_ci=False)
    failure = None
    try:
        with ExitStack() as stack:
            servers = {
                key: stack.enter_context(run.backend(f"browser-{key}"))
                for key in ("A", "B")
            }

            def reply(value):
                print(json.dumps(value), flush=True)

            reply(
                {
                    "urls": {key: server.url for key, server in servers.items()},
                    "directory": str(run.directory),
                }
            )
            for line in sys.stdin:
                try:
                    request = json.loads(line)
                    server = servers[request.get("server", "A")]
                    action = request["action"]
                    if action == "restart":
                        server.restart()
                        result = {"url": server.url}
                    elif action == "fail-push":
                        require(failure is None, "Push failure already active")
                        failure = run.failed_push(server)
                        failure.__enter__()
                        result = {}
                    elif action == "restore-push":
                        require(failure is not None, "No active push failure")
                        failure.__exit__(None, None, None)
                        failure = None
                        result = {}
                    elif action == "verify":
                        result = run.verify(request["expectations"])
                    elif action == "stop":
                        break
                    else:
                        raise RuntimeError("Unknown browser control command")
                    reply({"ok": True, "result": result})
                except (
                    RuntimeError,
                    OSError,
                    ValueError,
                    httpx.HTTPError,
                    subprocess.SubprocessError,
                ) as error:
                    reply(
                        {
                            "ok": False,
                            "error": str(error)
                            if isinstance(error, RuntimeError)
                            else type(error).__name__,
                        }
                    )
            if failure:
                failure.__exit__(None, None, None)
                failure = None
    finally:
        if failure:
            failure.__exit__(None, None, None)
        run.report()


def repin(root):
    """Revalidate existing data before recording a deliberate application upgrade."""
    run = Run(root, verify_revision=False)
    require(
        not git(CODE, "status", "--porcelain"),
        "Repinning requires a clean code checkout",
    )
    run.source_check()
    proof = run.verify()
    previous = run.manifest["code_sha"]
    current = git(CODE, "rev-parse", "HEAD")
    run.manifest.setdefault("revision_history", []).append(
        {
            "previous_code_sha": previous,
            "code_sha": current,
            "validated_data_sha": proof["sha"],
            "at": datetime.now(UTC).isoformat(),
        }
    )
    run.manifest["code_sha"] = current
    run.manifest["code_dirty"] = False
    write_json(run.root / "manifest.json", run.manifest)
    print(f"Repinned {previous[:7]} -> {current[:7]}; existing branch/data retained")


def main():
    def interrupted(_number, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    load_env(CODE / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser(
        "prepare",
        help="Provision a NEW provisional branch (writes to remote unless --local)",
    )
    p.add_argument("workspace", type=Path)
    p.add_argument(
        "--local",
        action="store_true",
        help="Use a new local bare remote instead of GitHub",
    )
    p.add_argument("--synthetic-only", action="store_true")
    p.add_argument(
        "--scan-root",
        type=Path,
        default=Path("/Users/ericzhang/Downloads/Wilfred_Prest_Survey_Data"),
    )
    for name in ("run", "manual", "repin", "browser-session"):
        p = sub.add_parser(name)
        p.add_argument("workspace", type=Path)
        if name == "run":
            p.add_argument("--skip-browser", action="store_true")
            p.add_argument(
                "--skip-ci",
                action="store_true",
                help="Record live CI as blocked; cannot produce full acceptance",
            )
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args)
        return 0
    if args.action == "browser-session":
        browser_session(args.workspace)
        return 0
    if args.action == "repin":
        repin(args.workspace)
        return 0
    run = Run(args.workspace, check_ci=not getattr(args, "skip_ci", False))
    if args.action == "manual":
        for name, port in (("A", 8765), ("B", 8766)):
            checkout = run.clone(f"manual-{name}")
            print(
                shlex.join(
                    [
                        "uv",
                        "run",
                        "survey",
                        "review",
                        "--scan-root",
                        str(run.root / "scans"),
                        "--data-checkout",
                        str(checkout),
                        "--flags",
                        str(run.root / "flags.jsonl"),
                        "--cache",
                        str(checkout.parent / f"cache-{name}"),
                        "--port",
                        str(port),
                        "--sync-interval",
                        "3600",
                        "--open-browser",
                    ]
                )
            )
        return 0
    functions = api_scenarios(run)
    for name, function in functions:
        if name == "real-sample" and not run.manifest["real_sample"]:
            run.results.append(
                {
                    "name": name,
                    "status": "not_run",
                    "reason": "Synthetic-only workspace",
                }
            )
            continue
        if not run.scenario(name, function):
            run.results.extend(
                {"name": remaining, "status": "blocked"}
                for remaining, _ in functions[len(run.results) :]
            )
            break
    if not args.skip_browser and all(
        r["status"] in {"passed", "not_run"} for r in run.results
    ):

        def browsers():
            existing = set(run.root.glob("run-*"))
            try:
                command("npm", "run", "test:e2e", cwd=CODE / "frontend", timeout=900)
            finally:
                for directory in set(run.root.glob("run-*")) - existing:
                    report = directory / "report.json"
                    if report.is_file():
                        run.checkpoints.extend(
                            json.loads(report.read_text())["checkpoints"]
                        )
            return {"artifacts": str(CODE / "frontend/test-results")}

        env_workspace = os.environ.get("REVIEW_TEST_WORKSPACE")
        os.environ["REVIEW_TEST_WORKSPACE"] = str(run.root)
        os.environ["REVIEW_TEST_PYTHON"] = sys.executable
        try:
            run.scenario("browser-smoke", browsers)
        finally:
            if env_workspace is None:
                os.environ.pop("REVIEW_TEST_WORKSPACE", None)
            else:
                os.environ["REVIEW_TEST_WORKSPACE"] = env_workspace
    else:
        run.results.append(
            {
                "name": "browser-smoke",
                "status": "not_run" if args.skip_browser else "blocked",
            }
        )
    run.scenario("original-source-hashes", run.source_check)
    if not run.manifest["local"] and (args.skip_ci or not run.token):
        run.results.append(
            {
                "name": "github-validation",
                "status": "blocked",
                "error": "Set GITHUB_TOKEN and omit --skip-ci to verify Actions",
            }
        )
    elif run.manifest["local"]:
        run.results.append(
            {"name": "github-validation", "status": "not_run", "reason": "Local remote"}
        )
    else:
        run.scenario("github-validation", run.ci)
    run.report()
    print(f"Report: {run.directory / 'report.md'}")
    return int(any(r["status"] in {"failed", "blocked"} for r in run.results))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        RuntimeError,
        OSError,
        ValueError,
        httpx.HTTPError,
        subprocess.SubprocessError,
    ) as error:
        print(
            str(error) if isinstance(error, RuntimeError) else type(error).__name__,
            file=sys.stderr,
        )
        raise SystemExit(1) from None

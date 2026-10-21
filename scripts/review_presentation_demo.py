"""Create and optionally launch a fresh full-corpus presentation sandbox."""

import argparse
import csv
import fcntl
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from survey.records import REGION
from survey.review.launch import open_when_ready

REPO = Path(__file__).resolve().parents[1]


def isolated_env():
    # Ignore inherited Git repository/config overrides, signing and user hooks.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("GIT_", "SURVEY_REVIEW_"))
    }
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return env


def git(where, *args):
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(where), *args],
        env=isolated_env(),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def check_paths(source, scans, sandbox):
    for origin in (REPO, source, scans):
        if (
            sandbox == origin
            or sandbox.is_relative_to(origin)
            or origin.is_relative_to(sandbox)
        ):
            raise ValueError(
                "Sandbox must be separate from code, source results and scans"
            )
    if not source.is_dir() or not scans.is_dir():
        raise ValueError("Source results and scan root must be existing directories")


def copy_scan(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    # APFS clone: independent file contents without duplicating all PDF blocks.
    if sys.platform == "darwin":
        result = subprocess.run(
            ["cp", "-c", str(source), str(destination)],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return
    shutil.copy2(source, destination)


def prepare(source, scans, sandbox):
    source, scans, sandbox = (
        p.expanduser().resolve() for p in (source, scans, sandbox)
    )
    check_paths(source, scans, sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=sandbox))
    print(f"Copying seed records into {run}…", flush=True)
    results = run / "data" / "results"
    results.mkdir(parents=True)
    scan_copy = run / "scans"
    scan_copy.mkdir()
    references, excluded = set(), []

    def visit(value, region):
        if isinstance(value, dict):
            image = value.get("image")
            if isinstance(image, str) and image.lower().endswith(".pdf"):
                if Path(image).name != image or "\\" in image:
                    raise ValueError(f"Unsafe PDF name: {image}")
                references.add((region, image))
            for child in value.values():
                visit(child, region)
        elif isinstance(value, list):
            for child in value:
                visit(child, region)

    for path in sorted(source.glob("*.jsonl")):
        if not path.read_text(encoding="utf-8").strip():
            excluded.append(path.name)
            continue
        if not REGION.fullmatch(path.stem):
            raise ValueError(f"Invalid region filename: {path.name}")
        shutil.copy2(path, results / path.name)
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                visit(json.loads(line), path.stem)
    if not list(results.glob("*.jsonl")):
        raise ValueError("No populated regional JSONL files found")

    def cli(*args, stdout=None):
        subprocess.run(
            [sys.executable, "-m", "survey.cli", *map(str, args)],
            cwd=run,
            env=isolated_env(),
            check=True,
            stdout=stdout,
        )

    print("Validating copied records…", flush=True)
    cli("validate-results", results)
    print("Generating a fresh review assignment…", flush=True)
    with (run / "flags.jsonl").open("w", encoding="utf-8") as stream:
        cli("flags", results, stdout=stream)
    print("Copying referenced PDFs and catalogue metadata…", flush=True)
    missing = []
    for region, image in sorted(references):
        original = scans / region / image
        if not original.resolve().is_relative_to(scans):
            raise ValueError(f"Scan resolves outside scan root: {original}")
        if original.is_file():
            copy_scan(original, scan_copy / region / image)
        else:
            missing.append(f"{region}/{image}")
    metadata = scans / "metadata.csv"
    if metadata.is_file():
        shutil.copy2(metadata, scan_copy / "metadata.csv")
        # Check the header without modifying catalogue titles or source metadata.
        with metadata.open(encoding="utf-8-sig", newline="") as stream:
            headers = csv.DictReader(stream).fieldnames or []
        if "Node ID" not in headers or not {"Node Title", "Title"}.intersection(
            headers
        ):
            print("Warning: metadata.csv lacks region title columns", flush=True)
    else:
        print("Warning: metadata.csv missing; regions will use numeric IDs", flush=True)

    git(run, "init", "--bare", str(run / "remote.git"))
    data = run / "data"
    git(data, "init", "-b", "review-data")
    for key, value in [
        ("user.name", "Presentation Demo"),
        ("user.email", "demo@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.hooksPath", "/dev/null"),
    ]:
        git(data, "config", key, value)
    git(data, "add", "results")
    git(data, "commit", "-m", "Seed fresh presentation demo")
    git(data, "remote", "add", "origin", str(run / "remote.git"))
    git(data, "push", "-u", "origin", "review-data")
    manifest = {
        "code_revision": git(REPO, "rev-parse", "HEAD"),
        "source_results": str(source),
        "source_scans": str(scans),
        "excluded_empty_files": excluded,
        "missing_scans": missing,
        "regions": len(list(results.glob("*.jsonl"))),
        "remote": str(run / "remote.git"),
    }
    (run / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (sandbox / "latest-run.txt").write_text(str(run) + "\n")
    print(
        f"Fresh sandbox: {run}\nLocal sharing destination: {run / 'remote.git'}",
        flush=True,
    )
    if excluded:
        print(f"Excluded empty source files: {', '.join(excluded)}", flush=True)
    if missing:
        print(f"Warning: {len(missing)} missing PDFs; see manifest.json", flush=True)
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-root", type=Path, required=True)
    parser.add_argument("--source-results", type=Path, default=REPO / "results")
    parser.add_argument(
        "--sandbox-root", type=Path, default=Path.home() / "SurveyReviewDemoSandboxes"
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        sandbox = args.sandbox_root.expanduser().resolve()
        check_paths(
            args.source_results.expanduser().resolve(),
            args.scan_root.expanduser().resolve(),
            sandbox,
        )
        if not 1 <= args.port <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        if not args.prepare_only and not (REPO / "frontend/dist/index.html").is_file():
            raise ValueError("Build the UI first: scripts/setup_presentation_demo.sh")
        sandbox.mkdir(parents=True, exist_ok=True)
        with (sandbox / ".launch.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError(
                    "A demo using this sandbox root is already running; stop it with Ctrl+C"
                ) from error
            if not args.prepare_only:
                with socket.socket() as probe:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind(("127.0.0.1", args.port))
            run = prepare(args.source_results, args.scan_root, sandbox)
            if args.prepare_only:
                return 0
            print(
                f"Validating backend startup; allow a few minutes. Open http://127.0.0.1:{args.port} when ready.\nCtrl+C stops the demo. Each launch starts fresh.",
                flush=True,
            )
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "survey.cli",
                    "review",
                    "--scan-root",
                    str(run / "scans"),
                    "--data-checkout",
                    str(run / "data"),
                    "--flags",
                    str(run / "flags.jsonl"),
                    "--cache",
                    str(run / "cache"),
                    "--port",
                    str(args.port),
                    "--data-branch",
                    "review-data",
                ],
                cwd=run,
                env=isolated_env(),
            )
            if not args.no_browser:
                threading.Thread(
                    target=open_when_ready, args=(args.port, 600), daemon=True
                ).start()
            try:
                return server.wait()
            except KeyboardInterrupt:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
                return 130
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Demo setup failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Prepare production-record acceptance on copies, with the real queue producer.

No live remote is contacted. This does not execute or certify human acceptance.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path

from survey.records import Reference, read_records
from survey.review.flags import build_flags
from survey.review.scans import LocalScanSource

REPO = Path(__file__).resolve().parents[1]


def fingerprint(path):
    with path.open("rb") as stream:
        return sha256(stream.read()).hexdigest()


def prepare_acceptance(source, scans, destination, port=8877):
    source, scans, destination = (
        path.resolve() for path in (source, scans, destination)
    )
    if any(
        destination.is_relative_to(path) or path.is_relative_to(destination)
        for path in (REPO, scans, source.parent)
    ):
        raise ValueError("Destination must be separate from code, records and scans")
    if destination.exists():
        raise ValueError("Choose a new destination; existing work is never replaced")
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    records, source_digest = read_records(source, source.stem)
    flags, skipped = build_flags({source.stem: records})
    if skipped:
        raise ValueError("Queue producer skipped sources: " + "; ".join(skipped))
    originals = {source: source_digest}
    probe = LocalScanSource(scans, destination / "cache")
    for entry in flags:
        ref = Reference(**entry)
        probe.probe(ref)
        pdf = (scans / ref.region / ref.pdf).resolve()
        if pdf not in originals:
            originals[pdf] = fingerprint(pdf)
    if fingerprint(source) != source_digest:
        raise ValueError(
            "Records changed during validation; retry from a stable source"
        )
    # All validation precedes destination creation. Copy whole regional records,
    # preserving household positions, unflagged data, identities and machine scores.
    checkout = destination / "data checkout"
    results = checkout / "results"
    results.mkdir(parents=True)
    shutil.copy2(source, results / source.name)
    if fingerprint(results / source.name) != originals[source]:
        raise ValueError("Records changed while copying; discard this destination")
    for pdf, expected in originals.items():
        if pdf == source:
            continue
        target = destination / "scans" / source.stem / pdf.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf, target)
        if fingerprint(target) != expected:
            raise ValueError("Scan changed while copying; discard this destination")
    (destination / "scans").mkdir(exist_ok=True)
    flags_path = destination / "flags.jsonl"
    flags_path.write_text(
        "".join(json.dumps(flag) + "\n" for flag in flags), encoding="utf-8"
    )
    if any(fingerprint(path) != digest for path, digest in originals.items()):
        raise ValueError("Source changed while copying; discard this destination")
    remote = destination / "remote.git"

    def git(where, *args):
        subprocess.run(
            ["git", "-C", str(where), *args], check=True, capture_output=True
        )

    git(destination, "init", "--bare", str(remote))
    git(checkout, "init", "-b", "review-data")
    git(checkout, "config", "user.name", "Disposable Acceptance")
    git(checkout, "config", "user.email", "acceptance@example.invalid")
    git(checkout, "add", "results")
    git(checkout, "commit", "-m", "Seed disposable production-record acceptance")
    git(checkout, "remote", "add", "origin", str(remote))
    git(checkout, "push", "-u", "origin", "review-data")
    command = [
        "uv",
        "run",
        "survey",
        "review",
        "--scan-root",
        str(destination / "scans"),
        "--data-checkout",
        str(checkout),
        "--flags",
        str(flags_path),
        "--cache",
        str(destination / "cache"),
        "--port",
        str(port),
        "--open-browser",
    ]
    manifest = {
        "region": source.stem,
        "records": len(records),
        "flags": len(flags),
        "original_sha256": {str(path): digest for path, digest in originals.items()},
        "code_base": subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
        ).strip(),
        "code_changes": "uncommitted changes may be present; retain git diff with evidence",
        "remote": str(remote),
        "launch": command,
        "acceptance": "NOT EXECUTED; requires named human TC-M07 and physical Windows evidence",
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    print((subprocess.list2cmdline if os.name == "nt" else shlex.join)(command))
    return checkout, flags_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path, help="one compatible regional JSONL")
    parser.add_argument(
        "directory", type=Path, help="new directory outside all sources"
    )
    parser.add_argument("--scan-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    try:
        prepare_acceptance(args.records, args.scan_root, args.directory, args.port)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))

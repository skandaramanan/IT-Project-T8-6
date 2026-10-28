"""Prepare a local review test from existing extracted survey records.

Selected field names and source cards are test inputs, not confidence-based
queue generation. Originals are read-only and uploads target a local Git remote.
"""

import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path

from survey.extraction.record import FIELD_MAP
from survey.records import REGION, Reference, ReviewError, read_records, resolve_field
from survey.review.fields import field_pointers
from survey.review.prepare import prepare_records
from survey.review.relinking import refresh_identities


def select_sample(records, region, labels, limit, pdf=None, pages=None):
    selected, flags, count = [], [], 0
    for record in records:
        record_flags = []
        for index, household in enumerate(record["dwelling"]["households"]):
            cards = [
                c for c in household.get("cards", []) if c["role"] == "coding-front"
            ]
            if not cards:
                continue
            card = cards[0]
            if (pdf and card["image"] != pdf) or (
                pages and card.get("page") not in pages
            ):
                continue
            household_flags = []
            for label in dict.fromkeys(labels):
                key, group = FIELD_MAP[label]
                if record["schema_version"] == "0.7.0":
                    pointer = next(
                        path
                        for name, path, kind in field_pointers(index, review=True)
                        if name == label and kind != "front"
                    )
                elif group in {"dwelling", "house"}:
                    if index != 0:
                        continue
                    pointer = (
                        f"/dwelling/{key}"
                        if group == "dwelling"
                        else f"/dwelling/house/{key}"
                    )
                else:
                    prefix = f"/dwelling/households/{index}"
                    pointer = (
                        f"{prefix}/{key}"
                        if group == "household"
                        else f"{prefix}/{group}/{key}"
                    )
                ref = Reference(region, card["image"], card.get("page"), pointer)
                try:
                    resolve_field(records, ref)
                except ReviewError as error:
                    if error.code in {"stale_pointer", "unsupported_source"}:
                        continue
                    raise
                household_flags.append(
                    {
                        "region": region,
                        "pdf": ref.pdf,
                        "page": ref.page,
                        "field_path": pointer,
                        "reason": "Manually selected integration test field",
                    }
                )
            if household_flags:
                record_flags.extend(household_flags)
                count += 1
            if count >= limit:
                break
        if record_flags:
            # Keep the whole dwelling: household indexes and shared ownership
            # must remain identical to the source extraction.
            selected.append(record)
            flags.extend(record_flags)
        if count >= limit:
            break
    if not flags:
        raise ValueError(
            "No matching fields/cards found; change the field or card selection"
        )
    return selected, flags, count


def prepare_sample(
    source, scans, root, labels, limit=2, pdf=None, pages=None, port=8875
):
    source, scans, root = source.resolve(), scans.resolve(), root.resolve()
    if root.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("Test directory must be outside the code checkout")
    if not scans.is_dir():
        raise ValueError("Scan root must contain the downloaded region folders")
    if root.exists() and any(root.iterdir()):
        raise ValueError(
            "Choose a new or empty directory; existing work will not be replaced"
        )
    if (
        source.is_relative_to(root)
        or scans.is_relative_to(root)
        or root.is_relative_to(scans)
    ):
        raise ValueError(
            "Test directory must be separate from source records and scans"
        )
    if limit < 1 or not 1 <= port <= 65535:
        raise ValueError("Household limit and port must be positive and valid")
    region = source.stem
    if not REGION.fullmatch(region):
        raise ValueError(
            "Regional JSONL filename must be a plain lowercase region name"
        )
    records, _ = read_records(source, region)
    if any(record["schema_version"] != "0.7.0" for record in records):
        records, _ = prepare_records(records)
    selected, flags, count = select_sample(records, region, labels, limit, pdf, pages)
    refresh_identities(selected)
    for entry in flags:
        scan = scans / region / entry["pdf"]
        if not scan.resolve().is_relative_to(scans) or not scan.is_file():
            raise ValueError(f"Missing original scan: {scan}")
    checkout, remote = root / "data checkout", root / "remote.git"
    results = checkout / "results"
    results.mkdir(parents=True)
    (results / source.name).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in selected),
        encoding="utf-8",
    )
    flags_path = root / "manual-flags.jsonl"
    flags_path.write_text(
        "".join(json.dumps(f) + "\n" for f in flags), encoding="utf-8"
    )

    def git(where, *args):
        subprocess.run(
            ["git", "-C", str(where), *args], check=True, capture_output=True
        )

    git(root, "init", "--bare", str(remote))
    git(checkout, "init", "-b", "review-data")
    git(checkout, "config", "user.name", "Local Review Test")
    git(checkout, "config", "user.email", "review-test@example.invalid")
    git(checkout, "add", "results")
    git(checkout, "commit", "-m", "Seed local review sample")
    git(checkout, "remote", "add", "origin", str(remote))
    git(checkout, "push", "-u", "origin", "review-data")
    print(
        f"Copied {len(selected)} dwellings; selected {count} households and {len(flags)} fields."
    )
    print(f"Original records/scans unchanged. Upload destination: {remote}")
    print("Run from the code checkout:")
    print(
        (subprocess.list2cmdline if os.name == "nt" else shlex.join)(
            [
                "uv",
                "run",
                "survey",
                "review",
                "--scan-root",
                str(scans),
                "--data-checkout",
                str(checkout),
                "--flags",
                str(flags_path),
                "--cache",
                str(root / "cache"),
                "--port",
                str(port),
                "--open-browser",
            ]
        )
    )
    return checkout, flags_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "records", type=Path, help="existing regional JSONL, e.g. 216412.jsonl"
    )
    parser.add_argument(
        "directory", type=Path, help="new empty test directory outside code checkout"
    )
    parser.add_argument("--scan-root", type=Path, required=True)
    parser.add_argument(
        "--field",
        action="append",
        choices=sorted(FIELD_MAP),
        help="repeat to select fields; default Weekly Rent and Garden",
    )
    parser.add_argument("--households", type=int, default=2)
    parser.add_argument("--pdf", help="optional exact PDF basename")
    parser.add_argument(
        "--page",
        type=int,
        action="append",
        help="optional original PDF page; repeat to select cards",
    )
    parser.add_argument("--port", type=int, default=8875)
    args = parser.parse_args()
    try:
        prepare_sample(
            args.records,
            args.scan_root,
            args.directory,
            args.field or ["Weekly Rent", "Garden"],
            args.households,
            args.pdf,
            args.page,
            args.port,
        )
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))

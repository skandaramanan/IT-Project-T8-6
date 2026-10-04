"""Selects the C1/C2 benchmark cards and extracts them as images.

The IT-73 structure run already classified 843 pages into
``results/pages.jsonl``, so the sample is picked from that rather than by
re-running a model over the archive.

C1 vs C2 is decided by two independent markers, not one -- the structure
spike found the same field read unevenly looks exactly like a variant field,
so a single marker isn't enough:

- ``No. of Family Boarders``   -- a field C2 has and C1 doesn't
- ``...Unearned Income``       -- C2 spells it out where C1 truncates to ``I.``

Across the 226 canonical coding fronts the two agree on 71 of 72 pages. The
one page where they disagree is dropped rather than guessed at.

Selection is round-robin across units, not first-N: consecutive pages in one
unit are consecutive records filled in by one clerk in one sitting, which is
what made the C3 benchmark unrepresentative.

data/ is gitignored, so this script is what's committed, not its output --
same archive in, same cards out, on any machine.

Usage:
    uv run python spike/select_c1_c2_sample.py
    uv run python spike/select_c1_c2_sample.py --c1 20 --c2 10
    uv run python spike/select_c1_c2_sample.py \\
        --format jpeg --out data/benchmark/c1c2-jpeg   # for Azure upload
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from survey.segmentation.pdf_pages import extract_image

DEFAULT_PAGES_JSONL = Path("results/pages.jsonl")
DEFAULT_OUT_DIR = Path("data/benchmark/c1c2")

# A page the model read badly has a short label list; the canonical coding
# card carries ~62. Below this it isn't a form variant, it's a bad read.
MIN_LABELS = 55

# ~11% of pages carry white rectangles sitting over the field values -- the
# structure spike's evidence points at a scanning fault rather than archival
# redaction, but either way the values under them are gone and the card can't
# be transcribed. Matched narrowly: "obscured by handwriting" is a different
# thing and must not disqualify a page.
WHITE_BLOCK = re.compile(
    r"white[^.]*(rectangl|block|patch|box)|(rectangl|block|patch|box)[^.]*white",
    re.IGNORECASE,
)


def _labels(row: dict) -> list[str]:
    return [field.get("label", "") for field in row["analysis"].get("fields", [])]


def is_legible(row: dict) -> bool:
    """False if the scan hides values the transcriber would need to read."""
    analysis = row["analysis"]
    if analysis.get("unreadable_regions"):
        return False
    return not any(
        WHITE_BLOCK.search(anomaly) for anomaly in (analysis.get("anomalies") or [])
    )


def classify(rows: list[dict]) -> dict[str, list[dict]]:
    """Split canonical coding fronts into C1 and C2. C3 and bad reads drop out."""
    coding: list[dict] = [
        row
        for row in rows
        if row.get("ok")
        and row["analysis"].get("page_role") == "coding-front"
        and len(_labels(row)) >= MIN_LABELS
        and is_legible(row)
        # C3 is the multi-family punch sheet -- shares 0/62 labels, own schema
        and not any("Dominant Family" in label for label in _labels(row))
    ]

    out: dict[str, list[dict]] = {"C1": [], "C2": []}
    for row in coding:
        labels = _labels(row)
        boarders = any("Family Boarders" in label for label in labels)
        spelled_out = any("Unearned Income" in label for label in labels)
        if boarders and spelled_out:
            out["C2"].append(row)
        elif not boarders and not spelled_out:
            out["C1"].append(row)
        # markers disagree: dropped, not guessed
    return out


def pick(rows: list[dict], count: int) -> list[dict]:
    """Round-robin across units so no unit dominates the sample."""
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: r["card_id"]):
        by_unit[row["unit"]].append(row)

    picked: list[dict] = []
    depth = 0
    while len(picked) < count:
        added = False
        for unit in sorted(by_unit):
            if depth < len(by_unit[unit]) and len(picked) < count:
                picked.append(by_unit[unit][depth])
                added = True
        if not added:  # fewer candidates than requested
            break
        depth += 1
    return picked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=Path, default=DEFAULT_PAGES_JSONL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--c1", type=int, default=20)
    parser.add_argument("--c2", type=int, default=10)
    parser.add_argument(
        "--format",
        choices=("png", "jpeg"),
        default="png",
        help="png for the benchmark (lossless); jpeg to stay under Document "
        "Intelligence's 50 MB custom-template training cap",
    )
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.pages.read_text().splitlines() if line]
    groups = classify(rows)
    selected = [
        (card_type, row)
        for card_type in ("C1", "C2")
        for row in pick(groups[card_type], getattr(args, card_type.lower()))
    ]

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = args.out / "manifest.csv"
    with manifest.open("w", newline="") as file:
        # these four columns are make_c1_ground_truth_sheet.META_COLUMNS
        writer = csv.writer(file)
        writer.writerow(["page id", "unit", "pdf page", "card type"])
        for card_type, row in selected:
            suffix = "jpg" if args.format == "jpeg" else "png"
            out_path = args.out / f"{row['card_id']}_{card_type}.{suffix}"
            extract_image(Path(row["pdf"]), row["page_number"], out_path, args.format)
            writer.writerow(
                [row["card_id"], row["unit"], row["page_number"], card_type]
            )
            print(f"{out_path.name}")

    counts = {kind: sum(1 for k, _ in selected if k == kind) for kind in ("C1", "C2")}
    print(
        f"\n{counts['C1']} C1 from {len({r['unit'] for k, r in selected if k == 'C1'})} units, "
        f"{counts['C2']} C2 from {len({r['unit'] for k, r in selected if k == 'C2'})} units"
        f"\nManifest: {manifest}"
    )


if __name__ == "__main__":
    main()

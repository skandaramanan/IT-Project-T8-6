"""Correct IT-124's committed Qwen results in place, from the cached readings.

uv run python scripts/patch_qwen_results.py [results/qwen2.5-vl-server-2000000px]

Two fixes from review, applied without re-segmenting the scans:

- A record read from an excluded source (``docs/runs/it124-excluded-sources.json``)
  is removed. One that also holds a kept card, or has reviewed fields, stops
  the script instead (``pipeline._exclude``).
- A field the reply gave under a misspelt label (``json_extraction.FIELD_ALIASES``,
  "Washhouse" in every reading) and the record has as ``omitted`` is filled in
  from the household's cached reading. A field the record already holds is
  never touched.

Each record is then scored again and the region's identities settled again,
with the pipeline's own functions, and validated. No model is asked anything.
Running it twice changes nothing the second time.
"""

import argparse
import json
from pathlib import Path

from survey.extraction.base import ExtractionResult
from survey.extraction.card_fields import FIELD_SCHEMA_BY_NAME
from survey.extraction.json_extraction import with_canonical_labels
from survey.extraction.record import FIELD_MAP, IDENTITY_GROUPS, build_field
from survey.pipeline import (
    _exclude,
    _score,
    _settle_identities,
    read_excluded_sources,
    read_records,
)
from survey.records import schema_errors, write_atomic

REPO = Path(__file__).resolve().parents[1]
CACHE = "qwen2.5-vl-server-2000000px/qwen-qwen2.5-vl-7b-q6_k"
MODEL_ID = "qwen2.5-vl"


def reading(region: str, image: str, page: int) -> ExtractionResult:
    path = REPO / "data/runs" / region / CACHE / f"{Path(image).stem}_p{page:04d}.json"
    return with_canonical_labels(ExtractionResult(**json.loads(path.read_text())))


def fill(groups: dict, result: ExtractionResult) -> int:
    """Fill the omitted fields ``result`` now has a value for; how many."""
    filled = 0
    for label, (key, group) in FIELD_MAP.items():
        if group not in groups or label not in result.fields:
            continue
        if groups[group][key]["status"] != "omitted":
            continue
        source = "coding-front" if group in IDENTITY_GROUPS else None
        # The run had no strike detection, so no field carries `negated`.
        groups[group][key] = build_field(
            FIELD_SCHEMA_BY_NAME[label],
            result.fields[label],
            source=source,
            struck=None,
        )
        filled += 1
    return filled


def patch(path: Path, excluded_path: Path) -> tuple[int, int, int]:
    region = path.stem
    before = read_records(path, region)
    records = _exclude(before, read_excluded_sources(excluded_path, region), quiet=True)
    filled = 0
    for record in records:
        dwelling = record["dwelling"]
        readings = {}
        for index, household in enumerate(dwelling["households"]):
            card = household["cards"][0]
            result = reading(region, card["image"], card["page"])
            readings[card["image"], card["page"]] = result
            groups = {
                "household": household,
                "head": household["head"],
                "counts": household["counts"],
                "coding": household["coding"],
            }
            if index == 0:  # the dwelling's fields came from its first card
                groups |= {"dwelling": dwelling, "house": dwelling["house"]}
            filled += fill(groups, result)
        _score(record, readings, MODEL_ID)
    _settle_identities(records)
    for record in records:
        if errors := schema_errors(record):
            raise SystemExit(f"{path}: {'; '.join(errors)}")
    if records:
        write_atomic(path, "".join(json.dumps(record) + "\n" for record in records))
    else:  # as the pipeline does: an empty region is not published (216461)
        path.unlink()
    return len(before), len(records), filled


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "results", nargs="?", type=Path, default=REPO / "results" / CACHE.split("/")[0]
    )
    parser.add_argument(
        "--excluded-sources",
        type=Path,
        default=REPO / "docs/runs/it124-excluded-sources.json",
    )
    args = parser.parse_args()
    totals = [0, 0, 0]
    for path in sorted(args.results.glob("*.jsonl")):
        counts = patch(path, args.excluded_sources)
        totals = [a + b for a, b in zip(totals, counts)]
        print(
            f"{path.stem}: {counts[0]} -> {counts[1]} records, {counts[2]} fields filled"
        )
    print(f"total: {totals[0]} -> {totals[1]} records, {totals[2]} fields filled")


if __name__ == "__main__":
    main()

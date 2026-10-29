"""Replay IT-123 readings offline, preserving reviewed fields and physical cards.

uv run python scripts/rebuild_cached_results.py --output data/it123-rebuild/results

The output must be separate from results/. No model client is constructed; a
missing cache is an expected negative probe, never permission to call an API.
"""

import argparse
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

from survey.association.records import build_dwelling_records
from survey.extraction.base import ExtractionResult
from survey.pipeline import (
    RunSummary,
    _coding_cards,
    _corrected_fields,
    _merge,
    _score,
    apply_identity_corrections,
    read_verified_coding,
    recover_coding_cards,
    reread_identities,
)
from survey.records import schema_errors, write_atomic
from survey.segmentation.segmenter import CardType, SegmentedCard

MODEL = "gemini-3.5-flash-lite"


class OfflineReader:
    def __init__(self, name):
        self.name = name
        self.missing = 0

    def extract(self, _):
        self.missing += 1
        return ExtractionResult()


def cached_readings(directory):
    readings = {}
    for path in sorted(directory.glob("*.json")):
        pdf, page = path.stem.rsplit("_p", 1)
        readings[pdf + ".pdf", int(page)] = ExtractionResult(
            **json.loads(path.read_text())
        )
    return readings


def rebuild_region(region, cache, previous, verified):
    coding = cached_readings(cache / MODEL)
    fronts = cached_readings(cache / f"{MODEL}-survey-front")
    inventory = {c for r in previous for c in _coding_cards(r)}
    if missing := inventory - coding.keys():
        raise ValueError(
            f"{region}: published coding cards lack caches: {sorted(missing)}"
        )
    by_pdf = defaultdict(list)
    for pdf, page in sorted(coding.keys() | fronts.keys()):
        # Caches also contain abandoned probes from older segmentation runs.
        # Replay the published coding inventory, not every stale probe result.
        if (pdf, page) not in fronts and (pdf, page) not in inventory:
            continue
        by_pdf[pdf].append(page)
    records = []
    reader, identity = OfflineReader(MODEL), OfflineReader(f"{MODEL}-identity")
    for pdf, pages in by_pdf.items():
        cards, readings = [], {}
        # Absolute PDF positions keep association distances stable even when
        # cache entries for blank backs or unreadable images are absent.
        for page in pages:
            key = pdf, page
            front = key in fronts and key not in verified
            card = SegmentedCard(
                CardType.FRONT if front else CardType.NUMERIC_CODING,
                Path(f"p{page:04d}.png"),
                Path(pdf),
                page - 1,
            )
            cards.append(card)
            readings[card] = fronts[key] if front else coding[key]
        page_numbers = list(range(1, max(pages) + 1))

        def locate(card):
            return card.source_scan.name, card.page_index + 1

        apply_identity_corrections(readings, locate, previous)
        cards = recover_coding_cards(
            cards, readings, page_numbers, Path(pdf), reader, cache, RunSummary()
        )

        filled = reread_identities(
            readings, locate, Path(pdf), identity, cache, RunSummary()
        )
        built, _, _ = build_dwelling_records(
            [(card, readings[card]) for card in cards],
            region=region,
            batch=pdf,
            locate=locate,
            reread=filled,
        )
        by_place = {locate(card): reading for card, reading in readings.items()}
        for record in built:
            _score(record, by_place, MODEL)
        records.extend(built)
    merged = _merge(previous, records)
    before = {c for r in previous for c in _coding_cards(r)}
    after = {c for r in merged for c in _coding_cards(r)}
    if before - after:
        raise ValueError(f"{region}: coding cards lost: {sorted(before - after)}")
    # Protect the complete corrected payload, including original machine value
    # and history, even if a changed front association moves its JSON path.
    corrections = Counter(
        json.dumps(f, sort_keys=True) for r in previous for _, f in _corrected_fields(r)
    )
    kept = Counter(
        json.dumps(f, sort_keys=True) for r in merged for _, f in _corrected_fields(r)
    )
    if corrections - kept:
        raise ValueError(f"{region}: reviewed fields were lost")
    for record in merged:
        if errors := schema_errors(record):
            raise ValueError(f"{region}: invalid rebuilt record: {errors}")
    return merged, len(after - before)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("data/runs"))
    parser.add_argument("--previous", type=Path, default=Path("results"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--verified-coding",
        type=Path,
        default=Path("docs/runs/it123-verified-coding.json"),
    )
    args = parser.parse_args()
    if args.output.resolve() == args.previous.resolve():
        parser.error(
            "use a separate staging directory; inspect the report before replacing results"
        )
    logging.basicConfig(level=logging.ERROR)
    args.output.mkdir(parents=True, exist_ok=True)
    report = []
    for path in sorted(args.previous.glob("*.jsonl")):
        previous = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        verified = read_verified_coding(args.verified_coding, path.stem)
        records, added = rebuild_region(
            path.stem, args.cache / path.stem, previous, verified
        )
        output = args.output / path.name
        if records:
            write_atomic(output, "".join(json.dumps(r) + "\n" for r in records))
        else:
            output.unlink(missing_ok=True)
        counts = Counter(f for r in records for f in r["dwelling"].get("flags", []))
        row = {
            "region": path.stem,
            "records": len(records),
            "households": sum(len(r["dwelling"]["households"]) for r in records),
            "new_coding_cards": added,
            "flags": dict(counts),
        }
        report.append(row)
        print(json.dumps(row), flush=True)
    write_atomic(
        args.output.parent / "report.json", json.dumps(report, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()

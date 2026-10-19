"""Re-measure confidence from saved raw benchmark readings, without model calls.

Example (run from the repository root)::

    uv run python benchmark/calibrate_confidence.py \\
      --qwen-raw data/it124-review-20261017/handoff/data/benchmark/results/q6-2mp-rp1.05/raw \\
      --output data/it125-calibration/calibration.json

All denominators use the authoritative ground-truth sheet, including omitted
fields and absent/failed arms. Absence is never counted as a correct blank.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from ground_truth import (
    DEFAULT_GROUND_TRUTH_XLSX,
    DEFAULT_IMAGES_DIR,
    load_ground_truth,
)
from survey.confidence.agreement import compare_fields
from survey.extraction.json_extraction import parse_confidence_bands, parse_json_fields
from survey.extraction.record import normalise

MIN_BAND_SAMPLE = 10


def _cell(correct: int, total: int) -> dict:
    return {
        "correct": correct,
        "total": total,
        "accuracy": correct / total if total else None,
    }


def _reading(raw_dir: Path, page_id: str) -> tuple[dict | None, dict, dict]:
    path = raw_dir / f"{page_id}.txt"
    if not path.is_file():
        return None, {}, {"page_id": page_id, "state": "absent"}
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    fields = parse_json_fields(text)
    evidence = {
        "page_id": page_id,
        "state": "available" if fields is not None else "failed",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return fields, parse_confidence_bands(text), evidence


def measure_pair(cards, primary_raw: Path, secondary_raw: Path) -> dict:
    """Measure one configuration, retaining class, band and state denominators."""
    class_n, class_right = Counter(), Counter()
    band_n, band_right = Counter(), Counter()
    standalone_n, standalone_right = Counter(), Counter()
    standalone_band_n, standalone_band_right = Counter(), Counter()
    states = {"a": Counter(), "b": Counter()}
    inputs = {"a": [], "b": []}
    omitted_fields = {"a": [], "b": []}
    for card in cards:
        first, bands, first_evidence = _reading(primary_raw, card.page_id)
        second, _, second_evidence = _reading(secondary_raw, card.page_id)
        inputs["a"].append(first_evidence)
        inputs["b"].append(second_evidence)
        paired = compare_fields(first, second, list(card.fields), first_bands=bands)
        for name, expected in card.fields.items():
            truth = normalise(expected)
            for arm, fields in (("a", first), ("b", second)):
                state = (
                    "unavailable"
                    if fields is None
                    else "omitted"
                    if name not in fields
                    else "blank"
                    if not normalise(fields[name])
                    else "value"
                )
                states[arm][state] += 1
                standalone_n[arm] += 1
                standalone_right[arm] += (
                    fields is not None
                    and name in fields
                    and normalise(fields[name]) == truth
                )
                if state == "omitted":
                    omitted_fields[arm].append({"page_id": card.page_id, "field": name})
            field = paired[name]
            # Omitted primary fields have no reading to validate, even if truth
            # happens to be blank. They remain in denominators as not correct.
            correct = first is not None and name in first and field["a"] == truth
            agreement = field["agreement"]
            class_n[agreement] += 1
            class_right[agreement] += correct
            band = bands.get(name)
            if band:
                key = f"{agreement}/{band}"
                band_n[key] += 1
                band_right[key] += correct
                standalone_band_n[band] += 1
                standalone_band_right[band] += correct
    return {
        "cards": len(cards),
        "fields": sum(standalone_n.values()) // 2,
        "classes": {k: _cell(class_right[k], n) for k, n in sorted(class_n.items())},
        "class_bands": {
            k: {**_cell(band_right[k], n), "measured_override": n >= MIN_BAND_SAMPLE}
            for k, n in sorted(band_n.items())
        },
        "standalone": {
            k: _cell(standalone_right[k], n) for k, n in sorted(standalone_n.items())
        },
        "standalone_bands": {
            k: _cell(standalone_band_right[k], n)
            for k, n in sorted(standalone_band_n.items())
        },
        "field_states": {k: dict(sorted(v.items())) for k, v in states.items()},
        "omitted_fields": omitted_fields,
        "raw_inputs": inputs,
    }


def calibrate(
    ground_truth: Path, gemini_raw: Path, banded_raw: Path, qwen_raw: Path
) -> dict:
    cards = load_ground_truth(ground_truth, DEFAULT_IMAGES_DIR)
    return {
        "configuration": "Gemini Flash-Lite default unbanded x Qwen2.5-VL-7B Q6_K 2MP rp1.05",
        "normalization": "current parse_json_fields aliases and record.normalise; omitted != blank",
        "minimum_band_sample": MIN_BAND_SAMPLE,
        "ground_truth_sha256": hashlib.sha256(ground_truth.read_bytes()).hexdigest(),
        "paths": {
            "ground_truth": str(ground_truth),
            "gemini_raw": str(gemini_raw),
            "banded_raw": str(banded_raw),
            "qwen_raw": str(qwen_raw),
        },
        "unbanded": measure_pair(cards, gemini_raw, qwen_raw),
        "banded": measure_pair(cards, banded_raw, qwen_raw),
    }


def compact_calibration(report: dict) -> dict:
    """Portable tracked evidence: measurements and input-manifest hashes only.

    The local full report retains individual source hashes and omission
    identities. The compact artifact excludes local paths and source text.
    Each manifest hash commits to sorted page IDs, input states and SHA-256
    hashes so a later local remeasurement can verify exact input identity.
    """
    compact = {
        key: report[key]
        for key in (
            "configuration",
            "normalization",
            "minimum_band_sample",
            "ground_truth_sha256",
        )
    }
    for mode in ("unbanded", "banded"):
        measurement = report[mode]
        compact[mode] = {
            key: value
            for key, value in measurement.items()
            if key not in {"raw_inputs", "omitted_fields"}
        }
        compact[mode]["raw_input_manifests"] = {
            arm: {
                "readings": len(inputs),
                "sha256": hashlib.sha256(
                    json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ).hexdigest(),
            }
            for arm, inputs in measurement["raw_inputs"].items()
        }
    return compact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_XLSX)
    parser.add_argument(
        "--gemini-raw",
        type=Path,
        default=Path("data/benchmark/results/gemini-3.5-flash-lite/raw"),
    )
    parser.add_argument(
        "--banded-raw",
        type=Path,
        default=Path("data/benchmark/results/gemini-3.5-flash-lite-banded/raw"),
    )
    parser.add_argument("--qwen-raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="Optional portable counts and input-hash artifact (for example docs/runs/it125-calibration.json)",
    )
    args = parser.parse_args()
    for path in (args.gemini_raw, args.banded_raw, args.qwen_raw):
        if not path.is_dir():
            parser.error(f"raw input directory does not exist: {path}")
    report = calibrate(
        args.ground_truth, args.gemini_raw, args.banded_raw, args.qwen_raw
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.summary_output:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(
            json.dumps(compact_calibration(report), indent=2, sort_keys=True) + "\n"
        )
    for name in ("unbanded", "banded"):
        print(name, json.dumps(report[name]["classes"], sort_keys=True))
    print(f"Calibration evidence: {args.output}")


if __name__ == "__main__":
    main()

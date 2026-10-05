"""Pairs two extractors' readings of the same cards, field by field (IT-98).

No ground truth to check "correct" against, so agreement between two
independent extractors stands in as the trust signal. Reads
``data/benchmark/results/<model>/raw/<page_id>.txt`` written by
``run_benchmark.py``, so the two arms never need to run on the same machine.

    uv run python benchmark/dual_extract.py --models gemini qwen2.5-vl

Only missing cards get extracted (via run_benchmark.py, not reimplemented),
so an interrupted run resumes. ``--no-fetch`` pairs only what's on disk.

"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from ground_truth import (
    DEFAULT_GROUND_TRUTH_XLSX,
    DEFAULT_IMAGES_DIR,
    load_ground_truth,
)
from run_benchmark import DEFAULT_RESULTS_ROOT, EXTRACTORS, load_extractor
from survey.confidence.agreement import (
    AGREE,
    BOTH_BLANK,
    DISAGREE,
    NO_SECOND_OPINION,
    ONE_BLANK,
    compare_fields,
)
from survey.confidence.card import assert_every_card_scored, card_confidence
from survey.confidence.field import assert_every_field_scored, score_fields
from survey.extraction.json_extraction import parse_confidence_bands, parse_json_fields


def load_arm(
    results_root: Path, model: str
) -> tuple[dict[str, dict[str, str] | None], dict[str, dict[str, str]]]:
    """Every saved reading for one model, keyed by page id, and any
    self-reported confidence bands.

    A card whose request failed has no raw file -- absence is the AC3 signal,
    not an error.
    """
    raw_dir = results_root / model / "raw"
    fields: dict[str, dict[str, str] | None] = {}
    bands: dict[str, dict[str, str]] = {}
    for path in sorted(raw_dir.glob("*.txt")):
        page_id = path.stem
        if not _has_reading(raw_dir, page_id):
            continue  # empty file: no answer
        text = path.read_text()
        fields[page_id] = parse_json_fields(text)
        bands[page_id] = parse_confidence_bands(text)
    return fields, bands


def _has_reading(raw_dir: Path, page_id: str) -> bool:
    """Whether this card has a saved answer worth reading back.

    Content, not existence -- an empty file (a skipped batch slot) isn't a
    reading, and treating it as one would strand the card as
    no_second_opinion forever instead of re-requesting it.
    """
    path = raw_dir / f"{page_id}.txt"
    return path.is_file() and path.stat().st_size > 0


def missing_pages(results_root: Path, model: str, page_ids: list[str]) -> list[str]:
    """The cards this arm has no saved reading for, in sheet order."""
    raw_dir = results_root / model / "raw"
    return [page_id for page_id in page_ids if not _has_reading(raw_dir, page_id)]


def fetch_command(
    model: str,
    page_ids: list[str],
    ground_truth: Path,
    images: Path,
    results_root: Path = DEFAULT_RESULTS_ROOT,
) -> list[str]:
    """The ``run_benchmark.py`` invocation that fills in this arm's missing cards.

    Shells out rather than reimplementing extraction, so retry/batching/
    concurrency behavior can't drift from the single-arm runner.
    """
    return [
        sys.executable,
        str(Path(__file__).with_name("run_benchmark.py")),
        "--model",
        model,
        "--ground-truth",
        str(ground_truth),
        "--images",
        str(images),
        "--results-root",
        str(results_root),
        "--pages",
        *page_ids,
    ]


def pair_cards(
    first_model: str,
    second_model: str,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    field_names: list[str] | None = None,
    page_ids: list[str] | None = None,
) -> list[dict]:
    """Both arms' saved output, paired card by card.

    ``page_ids`` is the authoritative card list when given; otherwise it's the
    union (never intersection) of what the two arms produced, so a card both
    arms failed on still shows up instead of silently vanishing.
    """
    first_fields, first_bands = load_arm(results_root, first_model)
    second_fields, second_bands = load_arm(results_root, second_model)
    # Sheet order (deduplicated) when there's a sheet; union fallback sorts.
    wanted = (
        list(dict.fromkeys(page_ids))
        if page_ids
        else sorted(set(first_fields) | set(second_fields))
    )

    records = []
    for page_id in wanted:
        first = first_fields.get(page_id)
        second = second_fields.get(page_id)
        paired = compare_fields(
            first,
            second,
            field_names,
            first_bands.get(page_id),
            second_bands.get(page_id),
        )
        models = {"a": first_model, "b": second_model}
        scored = score_fields(paired, models)
        # AC1: every consumer of pair_cards inherits this guarantee for free.
        assert_every_field_scored(scored, expected_fields=len(paired))
        records.append(
            {
                "page_id": page_id,
                "models": models,
                "counts": dict(
                    Counter(field["agreement"] for field in paired.values())
                ),
                "fields": paired,
                "scored": scored,
                "card_confidence": card_confidence(
                    field["confidence"] for field in scored.values()
                ),
            }
        )
    # IT-85 AC1, the card-level twin of the per-field assertion above.
    assert_every_card_scored(records)
    return records


def summarise(records: list[dict]) -> str:
    totals: Counter = Counter()
    for record in records:
        totals.update(record["counts"])
    total = sum(totals.values())
    lines = [f"{len(records)} cards, {total} field comparisons"]
    for name in (AGREE, DISAGREE, ONE_BLANK, BOTH_BLANK, NO_SECOND_OPINION):
        count = totals.get(name, 0)
        lines.append(f"  {name:<18} {count:>6}  ({count / total:.1%})" if total else "")
    # Agreement over coded fields only -- counting BOTH_BLANK would make any
    # two extractors look like they concur, since a card is mostly empty cells.
    coded = totals.get(AGREE, 0) + totals.get(DISAGREE, 0)
    if coded:
        lines.append(
            f"\nAgreement on fields where both read a code: "
            f"{totals.get(AGREE, 0)}/{coded} ({totals.get(AGREE, 0) / coded:.1%})"
        )
    # Distribution, not a mean -- averaging hides that no field actually
    # scored the average (IT-100 AC5).
    spread = Counter(
        field["confidence"] for record in records for field in record["scored"].values()
    )
    if spread:
        lines.append("\nConfidence distribution:")
        for score, count in sorted(spread.items(), reverse=True):
            lines.append(f"  {score:.2f}  {count:>6}  ({count / total:.1%})")

    stranded = [r["page_id"] for r in records if r["counts"].get(NO_SECOND_OPINION)]
    if stranded:
        lines.append(f"\nCards with only one reading ({len(stranded)}): {stranded}")
    return "\n".join(line for line in lines if line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs=2,
        default=["gemini", "qwen2.5-vl"],
        metavar=("A", "B"),
        help="The two arms to pair. Either a run_benchmark --model name, or a "
        "results directory name directly -- the local arm's raw/ is often "
        "copied in from the machine that has the GPU (default: %(default)s)",
    )
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Paired output (default: <results-root>/dual/<A>__<B>.json)",
    )
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_XLSX)
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Pair only what is already saved, never call a model. Use when both "
        "raw/ directories were produced elsewhere -- the local VLM arm normally "
        "comes from the machine with the GPU",
    )
    args = parser.parse_args()

    first_model, second_model = (_resolve(name) for name in args.models)

    page_ids: list[str] | None = None
    if args.no_fetch:
        for model in (first_model, second_model):
            if not (args.results_root / model / "raw").is_dir():
                raise SystemExit(
                    f"No saved output for {model!r} in {args.results_root}, and "
                    f"--no-fetch was given. Drop that arm's raw/ directory in, or "
                    f"rerun without --no-fetch to have it extracted."
                )
    else:
        # The sheet is the authoritative card list -- without it a card both
        # arms failed on would vanish rather than report as a total failure.
        cards = load_ground_truth(args.ground_truth, args.images)
        page_ids = [card.page_id for card in cards]
        for key, model in zip(args.models, (first_model, second_model)):
            _fetch_missing(key, model, page_ids, args)

    records = pair_cards(
        first_model, second_model, args.results_root, page_ids=page_ids
    )
    if not records:
        raise SystemExit("Both arms are empty -- nothing to pair")

    output = args.output or (
        args.results_root / "dual" / f"{first_model}__{second_model}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2))

    print(summarise(records))
    print(f"\nPaired output written to {output}")


def _fetch_missing(key: str, model: str, page_ids: list[str], args) -> None:
    """Extract whatever this arm is missing, if anything.

    A failure here (e.g. the local VLM needing a GPU this machine lacks) is
    reported and stepped over rather than fatal -- the honest result is a
    pairing where those fields read no_second_opinion, not a crash.
    """
    missing = missing_pages(args.results_root, model, page_ids)
    if not missing:
        print(f"{model}: all {len(page_ids)} cards already extracted")
        return

    if key not in EXTRACTORS:
        # A bare directory name, not a runnable model (e.g. the local VLM
        # arm, copied in from the GPU machine).
        print(
            f"{model}: {len(missing)} card(s) unread, and {key!r} is not a model "
            f"this harness can run -- copy the rest of its raw/ directory across. "
            f"Pairing continues; the gap is reported as no_second_opinion."
        )
        return

    print(f"{model}: extracting {len(missing)} of {len(page_ids)} cards...")
    command = fetch_command(
        key, missing, args.ground_truth, args.images, args.results_root
    )
    if subprocess.run(command, check=False).returncode:
        print(
            f"\n!! {model}: run_benchmark exited non-zero -- {len(missing)} card(s) "
            f"may still be unread. Pairing continues; anything still missing is "
            f"reported as no_second_opinion rather than assumed to agree.\n"
        )


def _resolve(name: str) -> str:
    """A --model name to the directory run_benchmark saved under.

    Differs for Gemini, whose ``name`` carries the model id to avoid two
    Gemini models overwriting each other's results.
    """
    return load_extractor(name).name if name in EXTRACTORS else name


if __name__ == "__main__":
    main()

"""The one entry point for the structure pipeline.

Three passes, one command. ``uv run main.py`` runs analyse -> report ->
synthesize in order; naming a step runs just that step, which is what you want
when re-clustering finished results at a different threshold rather than paying
for the model pass again.

The passes stay separate underneath because they fail differently: pass 1 is a
long, resumable, rate-limited network job, pass 2 is instant and local, pass 3
is one expensive call. Chaining them here is a convenience, not a reason to
pretend they are one thing -- ``analyze`` is resumable precisely because
re-running it is cheap and skips what is already done.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from structure.analyze import DEFAULT_MODEL, DEFAULT_RESULTS, run_analysis
from structure.calibrate import run_calibration
from structure.inventory import DEFAULT_INPUT_DIR
from structure.report import build_reports
from structure.synthesize import synthesise

DEFAULT_ENV_FILE = Path(".env")


def load_env(path: Path = DEFAULT_ENV_FILE) -> None:
    """Put .env into the environment, without a dependency for it.

    ``setdefault``, not assignment: a variable already exported in the shell
    wins over the file, so a one-off ``OPENROUTER_API_KEY=other uv run ...``
    still does what it looks like it does.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def survey_data_dir() -> Path:
    """Where the scans are. SURVEY_DATA_DIR is what .env.example documents; it
    points at the parent of the archive folder, not the archive folder itself."""
    root = os.environ.get("SURVEY_DATA_DIR")
    return Path(root) / DEFAULT_INPUT_DIR.name if root else DEFAULT_INPUT_DIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Discover what structures exist across the survey archive.",
    )
    parser.add_argument(
        "step",
        nargs="?",
        default="all",
        choices=["all", "analyze", "report", "synthesize", "calibrate"],
        help="Which pass to run (default: all three, in order). 'calibrate' is "
        "off to the side: it compares finished analyze runs and sends nothing",
    )
    parser.add_argument("--input", type=Path, default=None, help="Archive directory")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument("--model", default=DEFAULT_MODEL)

    group = parser.add_argument_group("analyze")
    group.add_argument(
        "--workers",
        type=int,
        default=32,
        help="Concurrent requests. 32 measured 27.5 pages/min; 60 measured 18.9 "
        "-- past the knee the provider queues rather than refuses, and tail "
        "latency crosses the 300s client timeout",
    )
    group.add_argument(
        "--rpm",
        type=float,
        default=0.0,
        help="Requests per minute ceiling shared across workers; 0 (default) "
        "means no gate, with 429 backoff as the only throttle. No per-minute "
        "cap has been observed -- but there is a 1,000/day free-tier cap, "
        "which no --rpm value can stretch",
    )
    group.add_argument(
        "--batch",
        type=int,
        default=1,
        help="Pages per request (default 1). The 1,000/day cap counts "
        "requests, so this is the only knob that stretches it -- at the cost "
        "of losing N pages per failed request, and of asking the model to keep "
        "N pages apart. Raise --max-tokens with it: ~1,200 output tokens/page",
    )
    group.add_argument(
        "--max-requests",
        type=int,
        default=0,
        help="Stop submitting once this many requests have been spent, retries "
        "included; 0 (default) means no ceiling. A budget for the 1,000/day "
        "cap that binds before the spend, not after it",
    )
    group.add_argument("--max-tokens", type=int, default=12000)
    group.add_argument(
        "--reasoning-effort", default="low", choices=["low", "medium", "high"]
    )
    group.add_argument("--units", nargs="+", default=None, metavar="UNIT")
    group.add_argument(
        "--per-unit",
        type=int,
        default=0,
        help="Analyse N pages from every unit, spread evenly through each, "
        "instead of the whole archive. What structures exist is a question "
        "about breadth: 44 units at 20 pages is 880 requests and about half an "
        "hour, where all 21,722 pages is three weeks of daily caps",
    )
    group.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Analyse only the first N pages of the selection -- smoke runs. "
        "The same N every time, so a resumed run finishes that set rather "
        "than moving on to fresh pages",
    )
    group.add_argument(
        "--skip-failed",
        action="store_true",
        help="Don't retry pages that already failed (default: retry them)",
    )
    group.add_argument(
        "--dry-run", action="store_true", help="Count pages, send nothing"
    )

    group = parser.add_argument_group("report")
    group.add_argument(
        "--merge-threshold",
        type=float,
        default=0.8,
        help="Label-set overlap at which two structures are treated as one "
        "(1.0 = exact match only, i.e. every transcription wobble is a variant). "
        "0.8 is where the knee sits on this data -- see --sweep",
    )
    group.add_argument(
        "--sweep",
        action="store_true",
        help="Print cluster counts across a range of merge thresholds and stop",
    )
    group.add_argument(
        "--export-images",
        action="store_true",
        help="Write the exception pages' scans to <out>/exception_images/",
    )

    group = parser.add_argument_group("calibrate")
    group.add_argument(
        "--arms",
        nargs="+",
        type=Path,
        default=None,
        metavar="RESULTS",
        help="Results files to compare, baseline first -- e.g. --arms "
        "results/calib_b1.jsonl results/calib_b5.jsonl results/calib_b10.jsonl",
    )

    group = parser.add_argument_group("synthesize")
    group.add_argument(
        "--clusters", type=int, default=8, help="How many largest clusters to include"
    )
    group.add_argument("--per-cluster", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> None:
    load_env()
    args = build_parser().parse_args(argv)

    if args.step == "calibrate":
        run_calibration(args.arms or [], args.out / "calibration.md")
        return

    if args.step in ("all", "analyze"):
        run_analysis(
            input_dir=args.input or survey_data_dir(),
            output=args.results,
            model=args.model,
            workers=args.workers,
            rpm=args.rpm,
            max_tokens=args.max_tokens,
            reasoning_effort=args.reasoning_effort,
            units=args.units,
            limit=args.limit,
            skip_failed=args.skip_failed,
            dry_run=args.dry_run,
            batch=args.batch,
            max_requests=args.max_requests,
            per_unit=args.per_unit,
        )
        if args.dry_run:
            return

    if args.step in ("all", "report"):
        build_reports(
            results=args.results,
            out=args.out,
            merge_threshold=args.merge_threshold,
            export_images=args.export_images,
            sweep=args.sweep,
        )
        if args.sweep:
            return

    if args.step in ("all", "synthesize"):
        synthesise(
            results=args.results,
            out=args.out / "synthesis.md",
            model=args.model,
            merge_threshold=args.merge_threshold,
            clusters=args.clusters,
            per_cluster=args.per_cluster,
            # The synthesis call carries a dozen scans and has to compare them,
            # so it gets the budget and the thinking the per-page pass doesn't.
            max_tokens=32000,
            reasoning_effort="high",
        )

"""Command line entry point for the extraction pipeline (FR-17, IT-120).

    uv run survey extract <scan_dir> [--region <name>]

A region is one archive unit folder (FR-02, D027): ``--region`` defaults to the
folder's name, e.g. ``216412``. Reads every PDF in ``scan_dir`` and writes
``<SURVEY_OUTPUT_DIR>/<region>.jsonl`` (default ``./results``). Each card's
reading is cached in ``data/runs/<region>/<extractor>/`` and replayed on a rerun;
``--fresh`` reads every card again.
Settings come from ``.env`` in the working directory. Exits 1 if any card or
PDF failed or any record failed the schema, so a scheduled run can tell.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

from survey.extraction.gemini import GeminiExtractor
from survey.pipeline import MergeRefused, run

log = logging.getLogger("survey")

# The region names a file and a cache folder, and the reviewer filters on it:
# lowercase only, so `North` and `north` can't share one file on macOS/Windows.
REGION = re.compile(r"[a-z0-9][a-z0-9_-]*")


def load_env(path: Path = Path(".env")) -> None:
    """Copy ``KEY=value`` lines into the environment.

    A variable already set wins, so a one-off ``GEMINI_MODEL=x uv run ...``
    still overrides the file. Blank values are skipped: ``.env.example`` ships
    them blank, and an empty GEMINI_MODEL would replace the default with "".
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if sep and key and not key.startswith("#") and value:
            os.environ.setdefault(key, value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="survey")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="extract a folder of scan PDFs")
    extract.add_argument("scan_dir", type=Path, help="folder of scan PDFs")
    extract.add_argument(
        "--region",
        help="region name, also the output file name (default: the folder's name)",
    )
    extract.add_argument(
        "--fresh",
        action="store_true",
        help="read every card again instead of replaying cached readings; "
        "reviewer corrections are still kept",
    )
    args = parser.parse_args(argv)
    region = args.scan_dir.resolve().name if args.region is None else args.region
    if not REGION.fullmatch(region):
        parser.error(
            f"region {region!r} must be lowercase letters, digits, - or _; "
            "pass --region to name it"
        )

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_env()
    # Fail loudly on an empty or mistyped folder rather than run on nothing.
    if not any(args.scan_dir.glob("*.pdf")):
        parser.error(f"no scan PDFs in {args.scan_dir}")

    extractor = GeminiExtractor()
    if not extractor.is_available():
        parser.error("GEMINI_API_KEY is not set; add it to .env")

    try:
        summary = run(
            args.scan_dir,
            region=region,
            extractor=extractor,
            front_extractor=GeminiExtractor(survey_front=True),
            out_dir=Path(os.environ.get("SURVEY_OUTPUT_DIR") or "results"),
            raw_dir=Path("data/runs") / region,
            fresh=args.fresh,
        )
    except MergeRefused as error:
        log.error("%s; nothing written", error)
        return 1
    log.info(
        "%d records, %d pages skipped, %d cards unreadable, %d cards failed, "
        "%d PDFs failed, %d records invalid",
        summary.records,
        summary.skipped_pages,
        summary.unreadable_cards,
        summary.failed_cards,
        summary.failed_pdfs,
        summary.invalid_records,
    )
    failed = summary.failed_cards or summary.failed_pdfs or summary.invalid_records
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

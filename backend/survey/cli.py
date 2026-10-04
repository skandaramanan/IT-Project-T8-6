"""Command line entry point for the extraction pipeline (FR-17, IT-120).

    uv run python src/cli.py extract <scan_dir> --region <name>

Reads every PDF in ``scan_dir`` and writes ``<SURVEY_OUTPUT_DIR>/<region>.jsonl``
(default ``./results``). Raw Gemini responses go to ``data/runs/<region>/``.
Settings come from ``.env`` in the working directory. Exits 1 if any card
failed extraction, so a scheduled run can tell.

Temporary: IT-126 turns the repo into an installable package, and this becomes
``uv run survey extract ...`` with the sys.path line below gone.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "spike"))

from gemini_extractor import GeminiExtractor

from pipeline import run

log = logging.getLogger("survey")


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
    parser = argparse.ArgumentParser(prog="survey", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="extract a folder of scan PDFs")
    extract.add_argument("scan_dir", type=Path, help="folder of scan PDFs")
    extract.add_argument(
        "--region", required=True, help="region name; also the output file name"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_env()
    # Checked before anything is written: an empty or mistyped folder would
    # otherwise replace the region's earlier output with an empty file.
    if not any(args.scan_dir.glob("*.pdf")):
        parser.error(f"no scan PDFs in {args.scan_dir}")

    extractor = GeminiExtractor()
    if not extractor.is_available():
        parser.error("GEMINI_API_KEY is not set; add it to .env")

    summary = run(
        args.scan_dir,
        region=args.region,
        extractor=extractor,
        out_dir=Path(os.environ.get("SURVEY_OUTPUT_DIR") or "results"),
        raw_dir=Path("data/runs") / args.region,
    )
    log.info(
        "%d records, %d pages skipped, %d cards unreadable, %d cards failed",
        summary.records,
        summary.skipped_pages,
        summary.unreadable_cards,
        summary.failed_cards,
    )
    return 1 if summary.failed_cards else 0


if __name__ == "__main__":
    sys.exit(main())

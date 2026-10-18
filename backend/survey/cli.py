"""Command line entry point for the extraction pipeline (FR-17, IT-120).

    uv run survey extract <scan_dir> [--region <name>] [--model qwen2.5-vl-server]

A region is one archive unit folder (FR-02, D027): ``--region`` defaults to the
folder's name, e.g. ``216412``. Reads every PDF in ``scan_dir`` and writes
``<SURVEY_OUTPUT_DIR>/<region>.jsonl`` (default ``./results``). Each card's
reading is cached in ``data/runs/<region>/<extractor>/`` and replayed on a rerun;
``--fresh`` reads every card again. Survey fronts are read too, at one more
Gemini request each. ``--notes`` reads each front's back for its interview notes
(FR-05), at one more request per back; a run without it keeps the notes an
earlier run read.
``--model qwen2.5-vl-server`` reads the coding cards with the second extractor
(IT-124) instead, through a local OpenAI-compatible server
(``--cached-only`` replays its cache with no server), into
``<SURVEY_OUTPUT_DIR>/<extractor>/<region>.jsonl`` -- its own file, so the two
arms never merge into one before IT-125 does it on purpose. Survey fronts,
backs and identity re-reads are not made: only coding fields have a second
opinion to agree with, and a Gemini re-read would mix the arms.
Scan-verified region/PDF/page decisions default to the repository's
``docs/runs/it123-verified-coding.json``; ``--verified-coding`` overrides it.
Pages scan inspection found are not coding cards (letters, notes) are never
read, and a record built from one earlier is removed: the default list is
``docs/runs/it124-excluded-sources.json``, and ``--excluded-sources`` overrides it.
Settings come from ``.env`` in the working directory.
Exits 1 if any card or PDF failed, or any record failed the schema. An unplaced
coding card is retained and flagged rather than treated as a failed request.

    uv run survey flags results > flags.jsonl  # the review queue
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

from survey.extraction.gemini import GeminiExtractor
from survey.extraction.qwen_server import QwenServerExtractor
from survey.pipeline import (
    MergeRefused,
    read_excluded_sources,
    read_verified_coding,
    run,
)

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
    extract.add_argument(
        "--model",
        choices=["gemini", "qwen2.5-vl-server"],
        default="gemini",
        help="extractor to read the cards with (default: %(default)s)",
    )
    extract.add_argument(
        "--cached-only",
        action="store_true",
        help="qwen2.5-vl-server: replay cached readings without a model server; "
        "a card with none fails. Needs QWEN_SERVER_MODEL and QWEN_SERVER_WEIGHTS",
    )
    extract.add_argument(
        "--verified-coding",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "docs/runs/it123-verified-coding.json",
        help="JSON list of region/pdf/page coding cards verified against the scans "
        "(default: repository docs/runs/it123-verified-coding.json)",
    )
    extract.add_argument(
        "--excluded-sources",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "docs/runs/it124-excluded-sources.json",
        help="JSON list of region/pdf/page pages verified against the scans as "
        "not coding cards, never read as one "
        "(default: repository docs/runs/it124-excluded-sources.json)",
    )
    extract.add_argument(
        "--notes",
        action="store_true",
        help="also read each survey back's interview notes, at one more Gemini "
        "request per back",
    )
    review = commands.add_parser("review", help="launch the local review backend")
    review.add_argument("--scan-root", type=Path)
    review.add_argument("--data-checkout", type=Path)
    review.add_argument("--flags", type=Path)
    review.add_argument("--cache", type=Path)
    review.add_argument("--data-branch")
    review.add_argument("--sync-interval", type=float)
    review.add_argument("--port", type=int)
    review.add_argument("--open-browser", action="store_true")
    validate = commands.add_parser(
        "validate-results", help="validate region JSONL without model credentials"
    )
    validate.add_argument("path", type=Path)
    flags = commands.add_parser("flags", help="list the fields that need review")
    flags.add_argument(
        "records", nargs="+", type=Path, help="results .jsonl files or folders"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_env()
    if args.command == "validate-results":
        from survey.records import ReviewError, read_dataset

        paths = (
            [args.path] if args.path.is_file() else sorted(args.path.glob("*.jsonl"))
        )
        if not paths:
            log.error("No region JSONL found at %s", args.path)
            return 1
        try:
            dataset = read_dataset(paths)
            for region, (records, _) in dataset.items():
                log.info("%s.jsonl: %d valid dwelling records", region, len(records))
        except ReviewError as error:
            log.error("%s", error)
            return 1
        return 0
    if args.command == "review":
        return _review(args, parser)
    if args.command == "flags":
        from survey.records import read_dataset
        from survey.review.flags import build_flags

        paths = []
        for path in args.records:
            if not path.exists():
                parser.error(f"no such file: {path}")
            paths += sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
        try:
            regions = {
                r: records
                for r, (records, _) in read_dataset(
                    paths, allow_duplicate_cards=True
                ).items()
            }
        except (OSError, ValueError) as error:  # ReviewError is a ValueError
            parser.error(str(error))
        queue, skipped = build_flags(regions)
        for flag in queue:
            print(json.dumps(flag))
        for message in skipped:
            print(f"{message}, skipped", file=sys.stderr)
        return 1 if skipped else 0
    region = args.scan_dir.resolve().name if args.region is None else args.region
    if not REGION.fullmatch(region):
        parser.error(
            f"region {region!r} must be lowercase letters, digits, - or _; "
            "pass --region to name it"
        )

    # Fail loudly on an empty or mistyped folder rather than run on nothing.
    if not any(args.scan_dir.glob("*.pdf")):
        parser.error(f"no scan PDFs in {args.scan_dir}")

    if args.cached_only and args.model != "qwen2.5-vl-server":
        parser.error("--cached-only replays the Qwen server's cache")
    out_dir = Path(os.environ.get("SURVEY_OUTPUT_DIR") or "results")
    if args.model == "gemini":
        extractor, front_extractor, identity_extractor = (
            GeminiExtractor(),
            GeminiExtractor(survey_front=True),
            GeminiExtractor(identity=True),
        )
        notes_extractor = GeminiExtractor(reverse_notes=True) if args.notes else None
        if not extractor.is_available():
            parser.error("GEMINI_API_KEY is not set; add it to .env")
    else:
        if args.notes:
            parser.error("--notes reads survey backs, which only Gemini reads")
        extractor, front_extractor = QwenServerExtractor(), None
        extractor.cached_only = args.cached_only
        notes_extractor = identity_extractor = None
        if not extractor.is_available():
            parser.error(extractor.unavailable)
        out_dir /= extractor.name

    try:
        summary = run(
            args.scan_dir,
            region=region,
            extractor=extractor,
            out_dir=out_dir,
            raw_dir=Path("data/runs") / region,
            fresh=args.fresh,
            front_extractor=front_extractor,
            notes_extractor=notes_extractor,
            identity_extractor=identity_extractor,
            verified_coding=read_verified_coding(args.verified_coding, region),
            excluded_sources=read_excluded_sources(args.excluded_sources, region),
        )
    except MergeRefused as error:
        log.error("%s; nothing written", error)
        return 1
    log.info(
        "%d records, %d pages skipped, %d cards unreadable, %d cards unplaced, "
        "%d cards failed, %d PDFs failed, %d records invalid, "
        "%d notes with no record",
        summary.records,
        summary.skipped_pages,
        summary.unreadable_cards,
        summary.unplaced_cards,
        summary.failed_cards,
        summary.failed_pdfs,
        summary.invalid_records,
        summary.unattached_notes,
    )
    failed = summary.failed_cards or summary.failed_pdfs or summary.invalid_records
    return 1 if failed else 0


def _review(args, parser) -> int:
    import socket
    import subprocess

    import uvicorn

    from survey.records import ReviewError
    from survey.review.api import Settings, create_app

    def path_setting(name):
        value = getattr(args, name) or os.environ.get(f"SURVEY_REVIEW_{name.upper()}")
        if not value:
            parser.error(
                f"review requires --{name.replace('_', '-')} or SURVEY_REVIEW_{name.upper()}"
            )
        return Path(value)

    try:
        settings = Settings(
            scan_root=path_setting("scan_root"),
            data_checkout=path_setting("data_checkout"),
            flags=path_setting("flags"),
            cache=args.cache
            or Path(
                os.environ.get("SURVEY_REVIEW_CACHE")
                or Path(tempfile.gettempdir()) / "survey-review-scans"
            ),
            data_branch=args.data_branch
            or os.environ.get("SURVEY_REVIEW_DATA_BRANCH")
            or "review-data",
            sync_interval=args.sync_interval
            if args.sync_interval is not None
            else float(os.environ.get("SURVEY_REVIEW_SYNC_INTERVAL") or 180),
            port=args.port
            if args.port is not None
            else int(os.environ.get("SURVEY_REVIEW_PORT") or 8765),
        )
        settings.validate()
    except (ReviewError, ValueError) as error:
        log.error("%s", error)
        return 1
    try:
        with socket.socket() as probe:
            if sys.platform != "win32":
                # Match Uvicorn's POSIX reuse behavior: TIME_WAIT connections
                # after shutdown must not look like a live competing server.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", settings.port))
    except OSError as error:
        log.error(
            "Cannot bind loopback port %d: %s; stop a competing backend or choose --port",
            settings.port,
            error,
        )
        return 1
    if args.open_browser:
        # Separate child observes readiness even while uvicorn owns this thread.
        subprocess.Popen(
            [sys.executable, "-m", "survey.review.launch", str(settings.port)]
        )
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, workers=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Runs one candidate extractor over a benchmark sheet and reports accuracy.

Defaults to the C1/C2 sheet -- 30 cards from 30 units, the forms that are 98%
of the coding cards. Its images are produced once by
``spike/select_c1_c2_sample.py``; this script never regenerates them.

Usage:
    uv run python spike/run_benchmark.py --model qwen2.5-vl

The older C3 set (20 cards, all from unit 216463) is still runnable, and is
the only one that can rebuild its own images from the source PDF:

    uv run python spike/run_benchmark.py --model qwen2.5-vl \\
        --ground-truth "data/Wilfred_Prest_Survey_Data/1262761_1973-0002-00052-sample 20.xlsx" \\
        --images data/benchmark/images \\
        --pdf "data/Wilfred_Prest_Survey_Data/216463/1262761_1973-0002-00052.pdf"

--pdf is only needed the first time (or after the image cache is cleared):
re-parsing a 182MB/492-page PDF on every candidate-model run would be waste.
"""

from __future__ import annotations

import argparse
import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from extract_benchmark_images import extract_benchmark_images
from ground_truth import (
    DEFAULT_GROUND_TRUTH_XLSX,
    DEFAULT_IMAGES_DIR,
    load_ground_truth,
)
from scoring import score_structured

from extraction.base import Extractor

EXTRACTORS: dict[str, str] = {
    # name -> "module:ClassName", imported lazily so picking one model doesn't
    # require every other candidate's dependencies to be installed
    "qwen2.5-vl": "qwen_vl_extractor:QwenVLExtractor",
    "qwen3-vl": "qwen3_vl_extractor:Qwen3VLExtractor",
    "internvl3": "internvl_extractor:InternVLExtractor",
    "molmo": "molmo_extractor:MolmoExtractor",
    "pixtral": "pixtral_extractor:PixtralExtractor",
    "nuextract3": "nuextract_extractor:NuExtractExtractor",
    "azure-doc-intel": "azure_doc_intel_extractor:AzureDocIntelExtractor",
    "ox-alpha": "ox_alpha_extractor:OxAlphaExtractor",
}


def load_extractor(name: str) -> Extractor:
    if name not in EXTRACTORS:
        raise SystemExit(f"Unknown model {name!r}. Choices: {', '.join(EXTRACTORS)}")
    module_name, class_name = EXTRACTORS[name].split(":")
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, class_name)()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(EXTRACTORS))
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Source batch PDF -- only needed if data/benchmark/images/ isn't populated yet",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Cards extracted concurrently (remote APIs are latency-bound; "
        "raise toward 20, but expect 429 backoff stalls past the provider's RPM cap)",
    )
    parser.add_argument(
        "--pages",
        nargs="+",
        default=None,
        metavar="PAGE_ID",
        help="Only run these page ids (default: every card in the sheet) -- for "
        "re-checking a card that failed without paying for the rest. Ids are "
        "strings, e.g. 216412_p0125 on the C1/C2 sheet, 134 on the C3 one",
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=DEFAULT_GROUND_TRUTH_XLSX,
        help="Benchmark sheet (default: C1/C2). Pass ground_truth.C3_GROUND_TRUTH_XLSX "
        "with --images to run the older C3 set",
    )
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES_DIR)
    args = parser.parse_args()

    extractor = load_extractor(args.model)
    if not extractor.is_available():
        raise SystemExit(
            f"{args.model} is not available (missing dependency or API key)"
        )

    cards = load_ground_truth(args.ground_truth, args.images)
    if args.pages:
        cards = [card for card in cards if card.page_id in set(args.pages)]
        unknown = set(args.pages) - {card.page_id for card in cards}
        if unknown:
            raise SystemExit(f"No benchmark card with page id {sorted(unknown)}")
    missing = [card for card in cards if not card.image_path.exists()]
    if missing:
        if args.pdf is None:
            raise SystemExit(
                f"{len(missing)}/{len(cards)} benchmark images aren't cached yet in "
                f"{args.images} -- run spike/select_c1_c2_sample.py for the C1/C2 set, "
                "or pass --pdf for the C3 set (see this script's docstring)"
            )
        # C3 only: it indexes one batch PDF by page number. C1/C2 cards come
        # from 30 different unit PDFs, which is select_c1_c2_sample.py's job.
        print(f"Extracting {len(missing)} missing benchmark images from {args.pdf}...")
        extract_benchmark_images(args.pdf, args.ground_truth, args.images)

    print(
        f"Running {extractor.name} over {len(cards)} benchmark cards "
        f"({args.workers} concurrently)\n"
    )

    def run_one(card):
        start = time.monotonic()
        result = extractor.extract(card.image_path)
        score = score_structured(card, result.fields)
        return card, score, result, time.monotonic() - start

    results_dir = Path("data/benchmark/results") / extractor.name
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    scores = []
    confidences: list[dict[str, float] | None] = []
    failed = 0
    wall_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, card): card for card in cards}
        for future in as_completed(futures):
            card = futures[future]
            try:
                card, score, result, elapsed = future.result()
            except Exception as error:  # noqa: BLE001 -- one bad card shouldn't kill 19 in-flight requests
                failed += 1
                print(f"page {card.page_id}: FAILED ({error})", flush=True)
                continue
            (raw_dir / f"{card.page_id}.txt").write_text(result.raw_text or "")
            scores.append(score)
            confidences.append(result.confidence)
            # flush: a card can take minutes, and redirected stdout is
            # block-buffered, so without this a running benchmark looks hung
            print(
                f"page {card.page_id}: {score.correct_fields}/{score.total_fields} fields "
                f"({score.accuracy:.0%}), "
                f"{score.correct_coded_fields}/{score.coded_fields} coded "
                f"in {elapsed:.1f}s",
                flush=True,
            )

    total_time = time.monotonic() - wall_start
    succeeded = len(scores)
    if succeeded:
        # a --pages run covers a few cards, so it must not clobber the full
        # run's mismatch file
        csv_path = results_dir / (
            "results-partial.csv" if args.pages else "results.csv"
        )
        with csv_path.open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["page_id", "field", "expected", "got", "match"])
            for score in sorted(scores, key=lambda s: s.page_id):
                for field, expected, got in score.mismatches:
                    writer.writerow([score.page_id, field, expected, got, False])
        zero_pages = sorted(s.page_id for s in scores if not s.correct_fields)
        if zero_pages:
            print(f"Zero-score pages: {zero_pages} (see {raw_dir}/)")
        print(f"\n--- {extractor.name} summary ---")
        print(
            f"Wall time: {total_time:.1f}s "
            f"({total_time / succeeded:.1f}s/card avg over {succeeded} scored"
            + (f", {failed} failed)" if failed else ")")
        )
        print(f"Mismatches written to {csv_path}")

        total_correct = sum(s.correct_fields for s in scores)
        total_fields = sum(s.total_fields for s in scores)
        print(
            f"Field accuracy: {total_correct}/{total_fields} ({total_correct / total_fields:.1%})"
        )
        coded_correct = sum(s.correct_coded_fields for s in scores)
        coded_total = sum(s.coded_fields for s in scores)
        # Cards are mostly empty cells, so the headline above flatters an
        # extractor that returns nothing -- this is the comparable number
        print(
            f"Coded-field accuracy: {coded_correct}/{coded_total} "
            f"({coded_correct / coded_total:.1%}) -- fields the card actually fills in"
        )
        # FR-10 is a Must, so whether an engine can score its own output at all
        # is a result in its own right -- report it beside the accuracy rather
        # than discovering it when the review queue gets built.
        if all(c is None for c in confidences):
            print("Confidence: none -- this engine cannot satisfy FR-10 on its own")
        else:
            scored = sum(len(c) for c in confidences if c)
            print(
                f"Confidence: {scored}/{total_fields} fields carry a score "
                f"({scored / total_fields:.1%})"
            )
    else:
        raise SystemExit(f"All {failed} cards failed")


if __name__ == "__main__":
    main()

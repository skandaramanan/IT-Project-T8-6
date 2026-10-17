"""Runs one candidate extractor over the benchmark sheet and reports accuracy.

The C1/C2 sheet -- 30 cards from 30 units, the forms that are 98% of the coding
cards. Its images are produced once by ``benchmark/select_c1_c2_sample.py``; this
script never regenerates them.

Usage:
    uv run python benchmark/run_benchmark.py --model qwen2.5-vl
"""

from __future__ import annotations

import argparse
import csv
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ground_truth import (
    DEFAULT_GROUND_TRUTH_XLSX,
    DEFAULT_IMAGES_DIR,
    load_ground_truth,
)
from scoring import score_structured
from survey.extraction.base import ExtractionResult, Extractor
from survey.extraction.json_extraction import parse_json_fields

# Where every run files its output. Defined here because this is what writes it;
# benchmark/dual_extract.py imports this name rather than repeating the path, so the
# reader and the writer cannot drift onto different directories.
DEFAULT_RESULTS_ROOT = Path("data/benchmark/results")

# Corpus size for the cost extrapolation IT-100 AC4 asks for. Approximate, and
# the roadmap's figure -- the full-scale run in Cycle 4 is what sizes it exactly.
CORPUS_CARDS = 6_500

EXTRACTORS: dict[str, str] = {
    # name -> "module:ClassName", imported lazily so picking one model doesn't
    # require every other candidate's dependencies to be installed
    #
    # The two candidates that survived IT-37 and D012. The rest stay on the
    # IT-37 branch as that spike's record: three never ran at all (transformers
    # API break, no Windows vLLM), the others were beaten on coded-field
    # accuracy, and azure-doc-intel needs a custom-trained model nobody set up.
    # Lazy importlib means a stale entry here would survive import and fail at
    # --model with a bare ModuleNotFoundError, so the dict lists what is present.
    "gemini": "survey.extraction.gemini:GeminiExtractor",  # primary, D012
    "qwen2.5-vl": "survey.extraction.qwen:QwenVLExtractor",  # local second opinion
    # the same model behind LM Studio/llama.cpp, for a GPU bitsandbytes can't use
    "qwen2.5-vl-server": "survey.extraction.qwen_server:QwenServerExtractor",
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
        help="Benchmark sheet (default: the C1/C2 set)",
    )
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument(
        "--results-root",
        type=Path,
        default=DEFAULT_RESULTS_ROOT,
        help="Where to save raw output and results (default: %(default)s). "
        "dual_extract passes its own through, so both look in the same place",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=1,
        help="Cards per request (default 1). Only for extractors that offer "
        "extract_batch. On a requests-per-day cap this multiplies the day's "
        "throughput -- but a model that stops reading partway through a batch "
        "returns well-formed fabricated values, not an error, so measure it "
        "with benchmark/batch_probe.py before trusting a size on a new model",
    )
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Score the raw model output already saved under results/<model>/raw/ "
        "instead of calling the API. For re-running the numbers after a scoring "
        "or ground-truth fix -- the model said what it said, and on a metered "
        "or daily-capped API re-asking it costs a day of quota to learn nothing",
    )
    args = parser.parse_args()

    extractor = load_extractor(args.model)
    if args.batch > 1 and not hasattr(extractor, "extract_batch"):
        raise SystemExit(f"{args.model} cannot batch: it has no extract_batch()")
    if not args.rescore and not extractor.is_available():
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
    if missing and not args.rescore:  # rescore never looks at the images
        raise SystemExit(
            f"{len(missing)}/{len(cards)} benchmark images aren't cached yet in "
            f"{args.images} -- run benchmark/select_c1_c2_sample.py to rebuild them"
        )

    results_dir = args.results_root / extractor.name
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    if args.rescore:
        cards = [card for card in cards if (raw_dir / f"{card.page_id}.txt").exists()]
        if not cards:
            raise SystemExit(f"Nothing to rescore: {raw_dir} has no saved output")

    batch_size = 1 if args.rescore else args.batch
    groups = [cards[i : i + batch_size] for i in range(0, len(cards), batch_size)]

    print(
        f"{'Rescoring saved output from' if args.rescore else 'Running'} "
        f"{extractor.name} over {len(cards)} benchmark cards"
        + (
            "\n"
            if args.rescore
            else f" in {len(groups)} request(s) of {batch_size} "
            f"({args.workers} concurrently)\n"
        )
    )

    def run_group(group):
        """Returns one (card, score, result, elapsed) per card in the group.

        elapsed is the whole request's wall time, so on a batch it is the same
        number for every card in it -- the per-card figure that matters when
        batching is the request time divided by the batch, and the summary's
        s/card average already does that division.
        """
        start = time.monotonic()
        results = [run_one(card) for card in group] if batch_size == 1 else None
        if results is None:
            results = extractor.extract_batch([c.image_path for c in group])
        elapsed = time.monotonic() - start
        return [
            (card, score_structured(card, r.fields), r, elapsed)
            for card, r in zip(group, results)
        ]

    def run_one(card):
        if args.rescore:
            # Only the parse is replayed, not the request: a raw file that no
            # longer parses is a bug in parse_json_fields, and scoring it as an
            # empty dict is the same signal the live run would have given.
            raw_text = (raw_dir / f"{card.page_id}.txt").read_text()
            return ExtractionResult(
                fields=parse_json_fields(raw_text) or {}, raw_text=raw_text
            )
        return extractor.extract(card.image_path)

    scores = []
    confidences: list[dict[str, float] | None] = []
    # IT-100 AC4 wants cost and latency per card, extrapolated to the corpus.
    # Both were already measured per request and then dropped here -- the
    # extractor computes cost_usd from real token counts and run_group times
    # every request -- so the gap was reporting, not measurement.
    costs: list[float | None] = []
    latencies: list[float] = []
    failed = 0
    wall_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_group, group): group for group in groups}
        for future in as_completed(futures):
            group = futures[future]
            try:
                finished = future.result()
            except Exception as error:  # noqa: BLE001 -- one bad request shouldn't kill the rest in flight
                failed += len(group)
                ids = ", ".join(c.page_id for c in group)
                print(f"page {ids}: FAILED ({error})", flush=True)
                continue
            for card, score, result, elapsed in finished:
                # Only write a raw file when there is something in it. An empty
                # one is indistinguishable from a real saved answer to anything
                # that tests for the file's existence -- dual_extract.missing_pages
                # did exactly that, and a card whose slot the model skipped was
                # then never re-requested on any later run.
                if result.raw_text:
                    (raw_dir / f"{card.page_id}.txt").write_text(result.raw_text)
                scores.append(score)
                confidences.append(result.confidence)
                costs.append(result.cost_usd)
                # On a batch this is the whole request's time, same figure for
                # every card in it -- so the median below is a per-request
                # latency, which is what the rate-limit arithmetic needs.
                latencies.append(elapsed)
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
            writer.writerow(["page_id", "field", "expected", "raw", "got", "match"])
            for score in sorted(scores, key=lambda s: s.page_id):
                for field, expected, raw, got in score.mismatches:
                    writer.writerow([score.page_id, field, expected, raw, got, False])
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

        # IT-100 AC4. Latency is the median request, not the mean of wall time
        # over cards: --workers runs requests concurrently, so wall/cards
        # understates a single card's latency by roughly the worker count.
        if latencies:
            print(
                f"Latency: {statistics.median(latencies):.1f}s median per request "
                f"({len(latencies)} requests, {args.workers} concurrent)"
            )
        priced = [c for c in costs if c is not None]
        if priced:
            per_card = sum(priced) / len(priced)
            print(
                f"Cost: ${sum(priced):.4f} over {len(priced)} cards "
                f"(${per_card:.5f}/card, ~${per_card * CORPUS_CARDS:,.2f} for "
                f"{CORPUS_CARDS:,} cards) -- list price, $0 on the free tier"
            )
        elif not args.rescore:
            print("Cost: unpriced -- no per-card cost reported by this engine")
    else:
        raise SystemExit(f"All {failed} cards failed")


if __name__ == "__main__":
    main()

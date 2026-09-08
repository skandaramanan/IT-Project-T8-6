"""Measures what batching several cards into one request costs in accuracy.

The free tier gates on requests per day, not tokens: a single-card request
spends ~11K of a 250K TPM allowance and 1 of 20 RPD. So the binding limit is
being hit with 4% of the token budget used, and packing N cards into one
request multiplies the day's throughput by N -- if the model still reads them
as carefully. That "if" is the whole question, and it is not free to assume:
asking a model to read five dense handwritten forms in one pass is exactly the
setup where attention spreads thin and per-card accuracy drops.

So this runs both arms over the SAME cards and scores them the same way:

    uv run python spike/batch_probe.py --model gemini-3.7-flash --batch-size 5

Cost is at most batch_size + 1 requests per model (N individual, 1 batched),
which is why it exists as a probe rather than a benchmark -- on a 20 RPD cap
you get about three of these a day. The individual arm reuses whatever
``run_benchmark.py`` already saved under results/<model>/raw/ and saves what it
does have to fetch, so a model you have already benchmarked costs 1 request,
and a probe interrupted halfway does not re-buy the cards it got.

Comparable by construction: same cards, same field schema, same scorer, same
``parse_json_fields``. The only difference between the arms is how many images
share a request.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "src"), str(_ROOT / "spike")]

import mimetypes
import os

from ground_truth import load_ground_truth
from json_extraction import parse_json_fields
from scoring import score_structured

from extraction.field_schema import build_extraction_prompt_schema

# Built from the same schema builder the single-card prompt uses, so the two
# arms can never drift into asking for different fields.
_SCHEMA_BLOCK = build_extraction_prompt_schema()


def batch_prompt(count: int) -> str:
    return (
        f"You are given {count} numeric coding cards from a 1941-43 social "
        f"survey, labelled CARD 1 to CARD {count}, each immediately after its "
        "label.\n\n"
        "Return ONLY a JSON object (no markdown fences, no commentary) whose "
        f'keys are "1" to "{count}" and whose value for each key is that '
        f"card's field object, containing exactly these "
        f"{len(_SCHEMA_BLOCK.splitlines())} keys.\n\n"
        "Read each card independently and completely. Give every value as a "
        'JSON string, copied exactly as written, keeping any leading zeros ("04", '
        "not 4). Use null where no code is written.\n\n" + _SCHEMA_BLOCK
    )


def _part(image_path: Path):
    from google.genai import types

    mime = mimetypes.types_map.get(image_path.suffix.lower(), "image/jpeg")
    return types.Part.from_bytes(data=image_path.read_bytes(), mime_type=mime)


def _usage(response) -> tuple[int, int]:
    u = response.usage_metadata
    return (u.prompt_token_count or 0), (u.candidates_token_count or 0) + (
        getattr(u, "thoughts_token_count", None) or 0
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemini-3.7-flash")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--pages", nargs="+", default=None)
    args = parser.parse_args()

    from gemini_extractor import GeminiExtractor, _retry_wait
    from google import genai

    cards = load_ground_truth()
    if args.pages:
        cards = [c for c in cards if c.page_id in set(args.pages)]
    cards = cards[: args.batch_size]
    if len(cards) < 2:
        raise SystemExit("Need at least 2 cards to say anything about batching")

    client = genai.Client()
    os.environ["GEMINI_MODEL"] = args.model
    os.environ.pop("GEMINI_CONFIDENCE_BAND", None)  # keep the probe unbanded
    extractor = GeminiExtractor()
    raw_dir = Path("data/benchmark/results") / args.model / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"{args.model}: {len(cards)} cards, individual vs one batched request\n")

    # --- arm A: one request per card ------------------------------------
    # Cached, because on a 20 RPD cap re-buying a card you already have is the
    # difference between three probes a day and one.
    single_scores, reused = [], 0
    start = time.monotonic()
    for card in cards:
        cached = raw_dir / f"{card.page_id}.txt"
        if cached.exists():
            fields = parse_json_fields(cached.read_text()) or {}
            reused += 1
        else:
            result = extractor.extract(card.image_path)
            cached.write_text(result.raw_text or "")
            fields = result.fields
        single_scores.append(score_structured(card, fields))
    single_time = time.monotonic() - start
    print(
        f"individual arm: {reused} reused from cache, {len(cards) - reused} fetched\n"
    )

    # --- arm B: one request for all of them -----------------------------
    contents: list = [batch_prompt(len(cards))]
    for index, card in enumerate(cards, start=1):
        contents += [f"CARD {index}:", _part(card.image_path)]

    # Same retry policy as the single-card path -- a 503 here would otherwise
    # throw away every request the individual arm just spent.
    start = time.monotonic()
    for attempt in range(1, 4):
        try:
            response = client.models.generate_content(
                model=args.model, contents=contents
            )
            break
        except Exception as error:  # SDK error types vary by transport
            wait = _retry_wait(error, attempt)
            if wait is None or attempt == 3:
                raise
            print(
                f"  batch attempt {attempt} failed ({str(error)[:60]}), "
                f"retrying in {wait:.0f}s"
            )
            time.sleep(wait)
    batch_time = time.monotonic() - start
    batch_in, batch_out = _usage(response)

    raw = response.text or ""
    try:
        outer = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        outer = {}
    if not isinstance(outer, dict):
        outer = {}
    batch_scores = []
        batch_scores.append(score_structured(card, fields))

    Path(f"data/benchmark/results/{args.model}-batch{len(cards)}.txt").write_text(raw)

    # --- compare ---------------------------------------------------------
    def totals(scores):
        return sum(s.correct_coded_fields for s in scores), sum(
            s.coded_fields for s in scores
        )

    s_ok, s_all = totals(single_scores)
    b_ok, b_all = totals(batch_scores)
    print(f"{'card':<16}{'individual':>12}{'batched':>10}")
    for card, single, batch in zip(cards, single_scores, batch_scores):
        print(
            f"{card.page_id:<16}"
            f"{single.correct_coded_fields:>7}/{single.coded_fields:<4}"
            f"{batch.correct_coded_fields:>6}/{batch.coded_fields:<4}"
        )
    print(
        f"\ncoded-field accuracy  individual {s_ok / s_all:.1%}   batched {b_ok / b_all:.1%}"
    )
    print(f"delta                 {(b_ok / b_all) - (s_ok / s_all):+.1%}")
    missing = [i for i in range(1, len(cards) + 1) if str(i) not in outer]
    if missing:
        print(f"WARNING: batch response omitted card(s) {missing} entirely")
    print(
        f"\nrequests   {len(cards)} -> 1  ({len(cards)}x more cards per RPD)\n"
        f"batch tok  {batch_in} in / {batch_out} out "
        f"({batch_in / len(cards):.0f} in per card)\n"
        f"wall time  {single_time:.0f}s individual"
        f"{' (cached)' if reused == len(cards) else ''} vs {batch_time:.0f}s batched"
    )


if __name__ == "__main__":
    main()

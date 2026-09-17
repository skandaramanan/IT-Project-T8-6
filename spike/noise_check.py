"""No-silent-loss check over the noise fixture set (IT-95, US-07 AC3).

Ignoring annotations of unknown purpose cuts both ways: an extractor tuned
to drop marks it does not recognise can drop marks it should have read. This
runs an extractor over cards that carry such annotations beside real values
and reports, by card and field, anything meaningful that went missing -- and
anything that came back which is not a field at all, because a noise mark
surfacing as a value is the other half of the same failure.

What counts as noise is D020 (docs/decisions/D020-noise-vs-meaningful-
annotations.md); the fixture manifest cites its rule per mark. Per D020's
"Handling of noise", a noise mark that is *absent* from the output is never
scored against the extractor -- the only failures here are a meaningful value
lost or a non-field key present.

It measures; it does not tune. A loss here is a finding for the extractor's
owner, not something to paper over in this module.

Usage:
    uv run python spike/noise_check.py --model gemini
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "src"), str(_ROOT / "spike")]

from ground_truth import BenchmarkCard
from scoring import score_structured

from extraction.field_schema import FIELD_SCHEMA

FIXTURES = _ROOT / "tests" / "fixtures"
MANIFEST = FIXTURES / "noise" / "manifest.json"
FIELD_NAMES = frozenset(spec.name for spec in FIELD_SCHEMA)


def load_noise_cards(manifest: Path = MANIFEST) -> list[BenchmarkCard]:
    """One BenchmarkCard per fixture, so scoring.score_structured can diff it."""
    data = json.loads(manifest.read_text())
    return [
        BenchmarkCard(
            page_id=card["image"],
            source_page=0,
            image_path=FIXTURES / card["image"],
            fields=card["expected"],
        )
        for card in data["cards"]
    ]


def find_losses(
    extract: Callable[[Path], dict[str, str]],
    cards: list[BenchmarkCard],
) -> list[str]:
    """Every meaningful value dropped and every non-field that leaked, one line
    each, naming the card and the field. Empty means nothing was lost."""
    losses: list[str] = []
    for card in cards:
        predicted = extract(card.image_path)
        for field, expected, raw, _ in score_structured(card, predicted).mismatches:
            losses.append(
                f"{card.page_id} / {field}: expected {expected!r}, got {raw!r}"
            )
        for leak in sorted(set(predicted) - FIELD_NAMES):
            losses.append(
                f"{card.page_id} / {leak}: not a field -- noise leaked as {predicted[leak]!r}"
            )
    return losses


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default="gemini")
    args = parser.parse_args()

    from run_benchmark import load_extractor

    extractor = load_extractor(args.model)
    if not extractor.is_available():
        raise SystemExit(f"{extractor.name} is not available -- see .env.example")

    losses = find_losses(lambda p: extractor.extract(p).fields, load_noise_cards())
    for line in losses:
        print(line)
    print(f"{len(losses)} loss(es) over {len(load_noise_cards())} cards")
    raise SystemExit(1 if losses else 0)


if __name__ == "__main__":
    main()

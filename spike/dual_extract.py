"""Pairs two extractors' readings of the same cards, field by field (IT-98).

FR-10 wants a confidence score on every field, and the 1980s dataset that would
tell us what "correct" means is directional at best (Client Meeting #3). So the
trust signal is manufactured instead: read every card twice, with two
independent extractors, and treat their agreement as a proxy for correctness.

This module is the comparison half. It does **not** call an API. Both arms have
already been run by ``run_benchmark.py``, which saves each card's raw response
under ``data/benchmark/results/<model>/raw/<page_id>.txt`` -- so pairing is a
pure function over two directories, and the two arms need not have run on the
same machine. That matters here: the hosted arm runs anywhere, the local VLM
needs a real GPU, and their raw directories meet by being copied together.

What this deliberately does not do:

- **Score anything.** Which reading is right is IT-100's question, answered
  against ground truth. Agreement is not correctness -- two models sharing a
  failure mode agree confidently and are both wrong, and measuring that is the
  whole point of IT-100's correlated-error check.
- **Turn a class into a number.** Mapping ``agree`` to a confidence value is
  IT-99. This emits the class; that ticket owns the arithmetic.
- **Decide which value wins.** That is IT-86's resolution policy.

Usage, once both arms have been run:

    uv run python spike/dual_extract.py --models gemini qwen2.5-vl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# pyproject's `pythonpath` only applies under pytest, so src/ and spike/ have to
# be put on the path here or every import below fails when run as a script.
_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "src"), str(_ROOT / "spike")]

from json_extraction import parse_json_fields
from scoring import agrees, normalise

from extraction.field_schema import FIELD_SCHEMA

DEFAULT_RESULTS_ROOT = Path("data/benchmark/results")

# Every card emits every schema field, whatever the models returned. A card is
# 62 fields either way, so a field one model silently dropped shows up as a
# comparison against nothing rather than vanishing from the output -- the same
# reasoning D011 gives for emitting all 62 into the record.
SCHEMA_FIELD_NAMES = [spec.name for spec in FIELD_SCHEMA]

# The five outcomes a field can have. Chosen to be exactly what the siblings
# need rather than what is natural here: IT-86's resolution policy has to cover
# four disagreement cases (agree / value-vs-blank / two values / both blank),
# and IT-99 AC4 requires an absent second opinion to be distinguishable from
# agreement. Collapsing NO_SECOND_OPINION into AGREE is the single mistake that
# would inflate every confidence number downstream, so it gets its own class.
AGREE = "agree"
DISAGREE = "disagree"
ONE_BLANK = "one_blank"
BOTH_BLANK = "both_blank"
NO_SECOND_OPINION = "no_second_opinion"

# Per-arm outcomes for one card. "unparseable" is kept apart from "no_output"
# because they fail for different reasons -- a missing file means the request
# failed or was never made, a present-but-unparseable one means the model
# answered and the answer was not usable. Both yield NO_SECOND_OPINION, but
# only one of them is worth re-running.
ARM_OK = "ok"
ARM_NO_OUTPUT = "no_output"
ARM_UNPARSEABLE = "unparseable"


def classify(first: str | None, second: str | None) -> str:
    """The agreement class for one field, given both arms' readings.

    Blankness is judged after normalisation, so the transcriber's "-", the
    coder's "B" and a model's omission are all one answer -- see
    ``scoring.normalise``. Leading zeros are **not** collapsed: `04` and `4` are
    different codes, so a split there is a real disagreement (IT-98 AC2b).
    """
    first_blank, second_blank = not normalise(first), not normalise(second)
    if first_blank and second_blank:
        return BOTH_BLANK
    if first_blank or second_blank:
        return ONE_BLANK
    return AGREE if agrees(first, second) else DISAGREE


def compare_fields(
    first: dict[str, str] | None,
    second: dict[str, str] | None,
    field_names: list[str] | None = None,
) -> dict[str, dict[str, str | None]]:
    """One card's fields, paired.

    ``None`` for an arm means it produced nothing usable for this card, which is
    not the same as producing blanks -- every field then reads
    NO_SECOND_OPINION rather than BOTH_BLANK, so a failed run cannot be mistaken
    for two models agreeing that the card is empty.
    """
    names = SCHEMA_FIELD_NAMES if field_names is None else field_names
    missing_arm = first is None or second is None
    paired: dict[str, dict[str, str | None]] = {}
    for name in names:
        first_raw = None if first is None else first.get(name)
        second_raw = None if second is None else second.get(name)
        paired[name] = {
            "a": normalise(first_raw),
            "b": normalise(second_raw),
            # What each model literally said. The raw/*.txt files hold the whole
            # response, but a reviewer chasing one disputed field should not
            # have to re-parse a blob to see it (AC4).
            "a_raw": first_raw,
            "b_raw": second_raw,
            "agreement": NO_SECOND_OPINION
            if missing_arm
            else classify(first_raw, second_raw),
        }
    return paired


def load_arm(
    results_root: Path, model: str
) -> tuple[dict[str, dict[str, str] | None], dict[str, str]]:
    """Every saved reading for one model, keyed by page id, plus why each failed.

    Reads what ``run_benchmark.py`` already wrote. A card whose request failed
    has no raw file at all -- the runner prints FAILED and continues without
    writing one -- so absence here is the AC3 signal, not an error.
    """
    raw_dir = results_root / model / "raw"
    fields: dict[str, dict[str, str] | None] = {}
    statuses: dict[str, str] = {}
    for path in sorted(raw_dir.glob("*.txt")):
        page_id = path.stem
        parsed = parse_json_fields(path.read_text())
        fields[page_id] = parsed
        statuses[page_id] = ARM_OK if parsed is not None else ARM_UNPARSEABLE
    return fields, statuses


def pair_cards(
    first_model: str,
    second_model: str,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    field_names: list[str] | None = None,
) -> list[dict]:
    """Both arms' saved output, paired card by card.

    The card set is the union of what the two arms produced, not the benchmark
    sheet -- a card only one arm reached still belongs in the output, marked as
    having no second opinion. Taking the intersection instead would make a
    half-failed run look like a clean one.
    """
    first_fields, first_status = load_arm(results_root, first_model)
    second_fields, second_status = load_arm(results_root, second_model)

    records = []
    for page_id in sorted(set(first_fields) | set(second_fields)):
        first = first_fields.get(page_id)
        second = second_fields.get(page_id)
        paired = compare_fields(first, second, field_names)
        records.append(
            {
                "page_id": page_id,
                "arms": {
                    "a": {
                        "model": first_model,
                        "status": first_status.get(page_id, ARM_NO_OUTPUT),
                    },
                    "b": {
                        "model": second_model,
                        "status": second_status.get(page_id, ARM_NO_OUTPUT),
                    },
                },
                "counts": dict(
                    Counter(field["agreement"] for field in paired.values())
                ),
                "fields": paired,
            }
        )
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
    # Agreement over the fields that carry a code is the comparable number: a
    # card is mostly empty cells, so counting BOTH_BLANK as agreement would make
    # any two extractors look like they concur. Same argument as coded-field
    # accuracy in scoring.py.
    coded = totals.get(AGREE, 0) + totals.get(DISAGREE, 0)
    if coded:
        lines.append(
            f"\nAgreement on fields where both read a code: "
            f"{totals.get(AGREE, 0)}/{coded} ({totals.get(AGREE, 0) / coded:.1%})"
        )
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
    args = parser.parse_args()

    first_model, second_model = (_resolve(name) for name in args.models)
    for model in (first_model, second_model):
        if not (args.results_root / model / "raw").is_dir():
            raise SystemExit(
                f"No saved output for {model!r} in {args.results_root}. Run "
                f"`uv run python spike/run_benchmark.py --model ...` for that arm "
                f"first, or copy its raw/ directory across."
            )

    records = pair_cards(first_model, second_model, args.results_root)
    if not records:
        raise SystemExit("Both arms are empty -- nothing to pair")

    output = args.output or (
        args.results_root / "dual" / f"{first_model}__{second_model}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2))

    print(summarise(records))
    print(f"\nPaired output written to {output}")


def _resolve(name: str) -> str:
    """A --model name to the directory run_benchmark saved under.

    They differ for Gemini, whose ``name`` is the model id so that two Gemini
    models do not overwrite each other's results. Anything unrecognised is
    passed through as a directory name, which is what a raw/ copied in from
    another machine will be.
    """
    from run_benchmark import EXTRACTORS, load_extractor

    return load_extractor(name).name if name in EXTRACTORS else name


if __name__ == "__main__":
    main()

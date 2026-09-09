"""Pairs two extractors' readings of the same cards, field by field (IT-98).

FR-10 wants a confidence score on every field, and the 1980s dataset that would
tell us what "correct" means is directional at best (Client Meeting #3). So the
trust signal is manufactured instead: read every card twice, with two
independent extractors, and treat their agreement as a proxy for correctness.

``run_benchmark.py`` saves each card's raw response under
``data/benchmark/results/<model>/raw/<page_id>.txt``, so the comparison itself
is a pure function over two directories -- which means the two arms need never
have run on the same machine. That matters here: the hosted arm runs anywhere,
the local VLM needs a real GPU, and their raw directories meet by being copied
together.

One command, because an arm with nothing saved is extracted first:

    uv run python spike/dual_extract.py --models gemini qwen2.5-vl

Only the cards actually missing are requested, and extraction is delegated to
``run_benchmark.py`` rather than reimplemented -- so an interrupted run resumes
instead of re-buying cards, which matters against Flash's 20-request daily cap.
Pass ``--no-fetch`` to pair only what is already on disk and never call a model.

What this deliberately does not do:

- **Score anything.** Which reading is right is IT-100's question, answered
  against ground truth. Agreement is not correctness -- two models sharing a
  failure mode agree confidently and are both wrong, and measuring that is the
  whole point of IT-100's correlated-error check.
- **Turn a class into a number.** Mapping ``agree`` to a confidence value is
  IT-99. This emits the class; that ticket owns the arithmetic.
- **Decide which value wins.** That is IT-86's resolution policy.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

# pyproject's `pythonpath` only applies under pytest, so src/ and spike/ have to
# be put on the path here or every import below fails when run as a script.
_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "src"), str(_ROOT / "spike")]

from ground_truth import (
    DEFAULT_GROUND_TRUTH_XLSX,
    DEFAULT_IMAGES_DIR,
    load_ground_truth,
)
from json_extraction import parse_confidence_bands, parse_json_fields
from run_benchmark import DEFAULT_RESULTS_ROOT, EXTRACTORS, load_extractor
from scoring import normalise

from extraction.field_schema import FIELD_SCHEMA

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


def classify(first: str | None, second: str | None) -> str:
    """The agreement class for one field, given both arms' readings.

    Blankness is judged after normalisation, so the transcriber's "-", the
    coder's "B" and a model's omission are all one answer -- see
    ``scoring.normalise``. Leading zeros are **not** collapsed: `04` and `4` are
    different codes, so a split there is a real disagreement (IT-98 AC2b).
    """
    a, b = normalise(first), normalise(second)
    if not a and not b:
        return BOTH_BLANK
    if not a or not b:
        return ONE_BLANK
    return AGREE if a == b else DISAGREE


def compare_fields(
    first: dict[str, str] | None,
    second: dict[str, str] | None,
    field_names: list[str] | None = None,
    first_bands: dict[str, str] | None = None,
    second_bands: dict[str, str] | None = None,
) -> dict[str, dict[str, str | None]]:
    """One card's fields, paired.

    ``None`` for an arm means it produced nothing usable for this card, which is
    not the same as producing blanks -- every field then reads
    NO_SECOND_OPINION rather than BOTH_BLANK, so a failed run cannot be mistaken
    for two models agreeing that the card is empty.

    A band key appears only where the model actually reported one. Absent is not
    "low": one means the model was never asked, the other means it was and said
    it could not read the cell, and IT-99 has to be able to tell them apart.
    """
    names = SCHEMA_FIELD_NAMES if field_names is None else field_names
    missing_arm = first is None or second is None
    paired: dict[str, dict[str, str | None]] = {}
    for name in names:
        first_raw = None if first is None else first.get(name)
        second_raw = None if second is None else second.get(name)
        field: dict[str, str | None] = {
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
        for key, bands in (("a_band", first_bands), ("b_band", second_bands)):
            if bands and name in bands:
                field[key] = bands[name]
        paired[name] = field
    return paired


def load_arm(
    results_root: Path, model: str
) -> tuple[dict[str, dict[str, str] | None], dict[str, dict[str, str]]]:
    """Every saved reading for one model, keyed by page id, and any
    self-reported confidence bands.

    Reads what ``run_benchmark.py`` already wrote. A card whose request failed
    has no raw file at all -- the runner prints FAILED and continues without
    writing one -- so absence here is the AC3 signal, not an error.

    Bands come back empty for a model that was never asked for them, which is
    the normal case; a raw/ directory does not have to say which prompt made it.
    """
    raw_dir = results_root / model / "raw"
    fields: dict[str, dict[str, str] | None] = {}
    bands: dict[str, dict[str, str]] = {}
    for path in sorted(raw_dir.glob("*.txt")):
        page_id = path.stem
        if not _has_reading(raw_dir, page_id):
            continue  # empty file: no answer, so no reading -- see _has_reading
        text = path.read_text()
        fields[page_id] = parse_json_fields(text)
        bands[page_id] = parse_confidence_bands(text)
    return fields, bands


def _has_reading(raw_dir: Path, page_id: str) -> bool:
    """Whether this card has a saved answer worth reading back.

    Content, not existence. An empty raw file is not an answer -- it is what a
    batch slot the model skipped used to leave behind -- and treating one as a
    saved reading strands that card forever: never re-requested, always paired
    as no_second_opinion. run_benchmark no longer writes them, but a raw/
    directory copied in from another machine may still hold some.
    """
    path = raw_dir / f"{page_id}.txt"
    return path.is_file() and path.stat().st_size > 0


def missing_pages(results_root: Path, model: str, page_ids: list[str]) -> list[str]:
    """The cards this arm has no saved reading for, in sheet order.

    Absence is the whole test. A card whose request failed left no raw file, so
    it looks identical to one never attempted -- which is correct here: both
    need the model called again, and neither should be paired as though the
    model had answered.
    """
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

    Shelling out to the existing runner rather than reimplementing extraction
    here is the point: it already owns retry-on-throttle, batching, concurrency,
    and the rule that a raised call writes no raw file while a useless answer
    writes one. A second copy of that would drift, and the two failure modes it
    distinguishes are exactly what ``load_arm`` reads back.

    ``--pages`` limits it to what is missing, so an interrupted run resumes
    instead of re-buying cards -- which matters on a 20-request daily cap.
    """
    return [
        sys.executable,
        str(_ROOT / "spike" / "run_benchmark.py"),
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

    ``page_ids`` is the authoritative card list when there is one -- the
    benchmark sheet. Without it the card set is the union of what the two arms
    produced, which is right when pairing raw directories copied in from
    elsewhere but wrong after a run: a card *both* arms failed appears in
    neither directory and would vanish from the output entirely, rather than
    showing up as the total failure it was.

    Union, never intersection. A card only one arm reached still belongs here,
    marked as having no second opinion; intersecting would make a half-failed
    run look clean.
    """
    # Imported here, not at module load: confidence.py names its five classes
    # by importing them from this module, so a top-level import back the other
    # way is circular. By the time pair_cards runs, both modules are fully
    # initialised.
    from confidence import assert_every_field_scored, score_fields

    first_fields, first_bands = load_arm(results_root, first_model)
    second_fields, second_bands = load_arm(results_root, second_model)
    # Sheet order when there is a sheet -- deduplicated, not sorted, so the
    # paired output lines up with the benchmark sheet it came from. The union
    # fallback has no authoritative order, so it sorts.
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
        # AC1: fail the run rather than write a field with no score. Here
        # rather than at the call site, so every consumer of pair_cards --
        # IT-100's benchmark, IT-85's aggregation -- inherits the guarantee
        # instead of each having to remember it.
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
    # The distribution, not just a mean: a card of 0.99s and one of 0.79s
    # average to something no field actually has (IT-100 AC5).
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
        # The sheet is the authoritative card list. Without it a card both arms
        # failed on would be absent from both raw/ directories and so vanish
        # from the output, instead of being reported as the total failure it is.
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

    A failure here is reported and stepped over rather than fatal. The most
    likely one is an arm that cannot run on this machine at all -- the local VLM
    needs a GPU -- and the honest result then is a pairing where every field
    reads ``no_second_opinion``, not a crash. That is a true statement about
    what we know, and the summary says so plainly.
    """
    missing = missing_pages(args.results_root, model, page_ids)
    if not missing:
        print(f"{model}: all {len(page_ids)} cards already extracted")
        return

    if key not in EXTRACTORS:
        # A bare directory name, not a runnable model -- the normal shape for
        # the local VLM arm, whose raw/ is copied in from the GPU machine.
        # Trying to run it would fail on every invocation and say nothing useful.
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

    They differ for Gemini, whose ``name`` is the model id so that two Gemini
    models do not overwrite each other's results. Anything unrecognised is
    passed through as a directory name, which is what a raw/ copied in from
    another machine will be.
    """
    return load_extractor(name).name if name in EXTRACTORS else name


if __name__ == "__main__":
    main()

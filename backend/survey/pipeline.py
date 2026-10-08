"""One run over a folder of scan PDFs, start to finish (FR-17, IT-120).

Each PDF is split into page images and sorted into cards by the segmenter.
Every numeric coding card is extracted (and every survey front, given a front
extractor), the cards are grouped into dwellings (IT-105), and each dwelling is
built into one D007 record and scored. A region's records go to ``<out_dir>/<region>.jsonl``, and a file holding
another region's records is refused (FR-02). Reruns are safe (NFR-07,
NFR-04, D026): cached readings are replayed, records are merged with the
previous file by the coding cards they were read from, and a reviewer's
``corrected`` field is never overwritten. Every record is validated against
the D007 envelope (IT-66): a new one that fails is logged and not written, and
a previous one that fails stops the run.

A page the segmenter cannot place, a card with no readable identity and a card
the extractor fails on are each logged and skipped; the run carries on unless
3 cards in a row get no answer (the daily cap or an outage).

Stopgaps until the work they stand in for lands:

- Gemini alone, so every field scores as NO_SECOND_OPINION (D016), refined by
  its self-reported band when it gave one. The Qwen arm and merge are
  IT-124/IT-125. A field the extractor never returned scores 0.0.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from functools import reduce
from operator import getitem
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pypdf import PdfReader

from survey.association.dwelling import ReviewFlag
from survey.association.records import build_dwelling_records
from survey.confidence.agreement import NO_SECOND_OPINION
from survey.confidence.card import card_confidence
from survey.confidence.field import confidence_for
from survey.extraction.base import ExtractionResult, Extractor
from survey.extraction.json_extraction import parse_confidence_bands
from survey.extraction.record import FIELD_MAP, build_record_id
from survey.segmentation.pdf_pages import extract_image
from survey.segmentation.segmenter import (
    CardType,
    SegmentedCard,
    classify_page,
    segment_pages,
)

log = logging.getLogger(__name__)

MAX_FAILURE_STREAK = 3  # a daily cap fails every card; stop instead of backing off each

# ponytail: repo-relative, which holds for the editable install uv makes. Move
# the schema into the package if survey is ever installed from a wheel.
SCHEMA_PATH = Path(__file__).parents[2] / "schema" / "record-envelope.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


class MergeRefused(ValueError):
    """The previous results can't be merged safely, so nothing was written."""


@dataclass
class RunSummary:
    records: int = 0
    skipped_pages: int = 0  # not a card the segmenter recognises
    unreadable_cards: int = 0  # no municipality or household number
    unplaced_cards: int = 0  # read, but fits no dwelling
    failed_cards: int = 0  # extractor raised or returned nothing usable
    failed_pdfs: int = 0  # could not be opened or split into pages
    failure_streak: int = 0  # consecutive failed cards; reaching the cap stops the run
    invalid_records: int = 0  # failed the envelope, not written


def run(
    scan_dir: Path,
    *,
    region: str,
    extractor: Extractor,
    out_dir: Path,
    raw_dir: Path | None = None,
    fresh: bool = False,
    front_extractor: Extractor | None = None,
) -> RunSummary:
    """Process every PDF in ``scan_dir`` and write ``<region>.jsonl``.

    ``front_extractor`` reads the survey fronts too; without it they are not
    read. ``fresh`` sets the cached readings aside (``<extractor>.previous``)
    and reads every card again; corrections are still kept. Set aside once, at
    the start, so a fresh run cut short resumes with a plain rerun.
    """
    summary = RunSummary()
    out_path = out_dir / f"{region}.jsonl"
    _read_records(out_path, region)  # fail fast: a damaged file must cost no quota
    for reader in filter(None, (extractor, front_extractor)):
        cache_dir = raw_dir / reader.name if raw_dir else None
        if fresh and cache_dir and cache_dir.exists():
            previous = cache_dir.with_name(cache_dir.name + ".previous")
            shutil.rmtree(previous, ignore_errors=True)
            cache_dir.rename(previous)
    records: list[dict[str, Any]] = []
    for pdf in sorted(scan_dir.glob("*.pdf")):
        if summary.failure_streak >= MAX_FAILURE_STREAK:
            break
        log.info("%s: reading", pdf.name)
        try:
            records += _run_pdf(
                pdf, region, extractor, front_extractor, raw_dir, summary
            )
        except Exception:  # without this, one damaged PDF loses the whole batch
            log.exception("%s: unreadable PDF, skipped", pdf.name)
            summary.failed_pdfs += 1

    if summary.failure_streak >= MAX_FAILURE_STREAK:
        log.error(
            "%d cards failed in a row; stopping, rerun to resume",
            MAX_FAILURE_STREAK,
        )
    # re-read: corrections may have been saved meanwhile
    merged = _merge(_read_records(out_path, region), records)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(out_path, "".join(json.dumps(record) + "\n" for record in merged))
    summary.records = len(merged)
    log.info(
        "wrote %d records to %s, %d kept from the previous run",
        len(merged),
        out_path,
        len(merged) - len(records),
    )
    return summary


def _run_pdf(
    pdf: Path,
    region: str,
    extractor: Extractor,
    front_extractor: Extractor | None,
    raw_dir: Path | None,
    summary: RunSummary,
) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as tmp:
        pages: list[Path] = []
        page_numbers: list[int] = []  # 1-based PDF page, parallel to `pages`
        for number in range(1, len(PdfReader(pdf).pages) + 1):
            path = Path(tmp) / f"p{number:04d}.png"
            try:
                extract_image(pdf, number, path)
            # Not just ValueError: a page whose image can't be decoded (3 pages
            # are JBIG2, which needs a system jbig2dec) must not cost its PDF.
            except Exception:
                log.warning(
                    "%s p%d: no readable scan image, skipped",
                    pdf.name,
                    number,
                    exc_info=True,
                )
                summary.skipped_pages += 1
                continue
            pages.append(path)
            page_numbers.append(number)

        cards = segment_pages(pages, source_scan=pdf)
        placed = {card.page_index for card in cards}
        for index, page in enumerate(pages):
            # Every record has a blank coding-card back; only non-blank pages
            # the segmenter couldn't place are worth a warning.
            if index not in placed and classify_page(page) is not None:
                log.warning(
                    "%s p%d: unrecognised page, skipped", pdf.name, page_numbers[index]
                )
                summary.skipped_pages += 1

        readers = {
            CardType.NUMERIC_CODING: extractor,
            CardType.FRONT: front_extractor,
        }
        readings: dict[SegmentedCard, ExtractionResult] = {}
        for card in cards:
            reader = readers.get(card.card_type)
            if reader is None:
                continue
            if summary.failure_streak >= MAX_FAILURE_STREAK:
                break
            number = page_numbers[card.page_index]
            result = _reading(card.image_path, pdf, number, reader, raw_dir, summary)
            if result is not None:
                readings[card] = result

    def locate(card: SegmentedCard) -> tuple[str, int]:  # D026: scan and page
        return pdf.name, page_numbers[card.page_index]

    records, dwellings, unplaced = build_dwelling_records(
        [(card, readings.get(card)) for card in cards],
        region=region,
        batch=pdf.name,
        locate=locate,
        fronts_read=front_extractor is not None,
    )
    # Every front is unnumbered when none was read; flagging each is noise.
    quiet = set() if front_extractor else {ReviewFlag.MISSING_DWELLING_NO}
    for dwelling in dwellings:
        if flags := dwelling.flags - quiet:
            log.warning(
                "%s p%d: dwelling %s flagged: %s",
                *locate(dwelling.cards[0]),
                dwelling.dwelling_no,
                ", ".join(sorted(flags)),
            )
        summary.unreadable_cards += ReviewFlag.MISSING_RECORD_ID in dwelling.flags
    for card in unplaced:
        # An unread card is already counted as failed.
        if card.card_type is CardType.NUMERIC_CODING and card in readings:
            log.warning("%s p%d: coding card fits no dwelling, skipped", *locate(card))
            summary.unplaced_cards += 1

    by_place = {locate(card): result for card, result in readings.items()}
    # The Gemini extractor's `name` carries -banded/-struck suffixes; the
    # confidence tables are keyed by the bare model id.
    model = getattr(extractor, "model_id", extractor.name)
    valid = []
    for record in records:
        _score(record, by_place, model)
        if errors := _schema_errors(record):
            # Not written, so the merge keeps this dwelling's previous record.
            image, page = min(_coding_cards(record))
            ids = ", ".join(h["record_id"] for h in record["dwelling"]["households"])
            log.error(
                "%s p%d: %s fails the schema, not written: %s",
                image,
                page,
                ids,
                "; ".join(errors),
            )
            summary.invalid_records += 1
        else:
            valid.append(record)
    return valid


def _reading(
    image: Path,
    pdf: Path,
    number: int,
    extractor: Extractor,
    raw_dir: Path | None,
    summary: RunSummary,
) -> ExtractionResult | None:
    """The card's cached reading, or a new one; None if it has none usable."""
    where = f"{pdf.name} p{number}"
    cache = (
        raw_dir / extractor.name / f"{pdf.stem}_p{number:04d}.json" if raw_dir else None
    )
    result = None
    if cache and cache.exists():
        try:
            result = ExtractionResult(**json.loads(cache.read_text(encoding="utf-8")))
        except (ValueError, TypeError):  # truncated, or saved before a format change
            log.warning("%s: unreadable cached reading, reading again", where)
    if result is None:
        try:
            result = extractor.extract(image)
        except Exception:  # one bad card must not end a run of hundreds
            log.exception("%s: extraction failed, skipped", where)
            summary.failed_cards += 1
            summary.failure_streak += 1
            return None
        if cache and result.raw_text:
            cache.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(cache, json.dumps(asdict(result)))
    if not result.fields:
        log.error("%s: no usable reading, skipped", where)
        summary.failed_cards += 1
        return None
    summary.failure_streak = 0
    return result


def _schema_errors(record: dict[str, Any]) -> list[str]:
    """Every way ``record`` breaks the envelope, as ``"<path>: <reason>"``."""
    return [
        f"{'/'.join(map(str, error.absolute_path)) or '<record>'}: {error.message}"
        for error in _VALIDATOR.iter_errors(record)
    ]


def _score(
    record: dict[str, Any],
    readings: dict[tuple[str, int], ExtractionResult],
    model: str,
) -> None:
    """Fill in field and card confidence, which build_record leaves null.

    Each household is scored from its own coding card's reading. The dwelling
    took its fields from the first household's card, so only that card scores
    them. Survey-front fields have no D016 calibration and stay null.
    """
    dwelling = record["dwelling"]
    for index, household in enumerate(dwelling["households"]):
        card = household["cards"][0]
        bands = parse_confidence_bands(readings[card["image"], card["page"]].raw_text)
        groups = {
            "household": household,
            "head": household["head"],
            "counts": household["counts"],
            "coding": household["coding"],
        }
        if index == 0:
            groups |= {"dwelling": dwelling, "house": dwelling["house"]}
        scores = []
        for label, (key, group) in FIELD_MAP.items():
            if group not in groups:
                continue
            field = groups[group][key]
            if field["status"] == "omitted":
                score = 0.0
            else:
                score = confidence_for(NO_SECOND_OPINION, model, bands.get(label))
            field["confidence"] = score
            scores.append(score)
        card["confidence"] = card_confidence(scores)


def _read_records(path: Path, region: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not _coding_cards(record):
                raise ValueError("no coding card")
        except (ValueError, KeyError, TypeError) as error:
            raise MergeRefused(f"{path} line {number}: not a valid record") from error
        # A hand-edited line (D025) is the likeliest way in.
        if errors := _schema_errors(record):
            raise MergeRefused(f"{path} line {number}: {'; '.join(errors)}")
        # FR-02: a renamed or misplaced file would otherwise be merged into this
        # region and kept, since the run never rebuilds another region's cards.
        if record.get("region") != region:
            raise MergeRefused(
                f"{path} line {number}: region {record.get('region')!r}, not {region!r}"
            )
        records.append(record)
    return records


def _household_cards(record: dict[str, Any]) -> list[list[tuple[str, int]]]:
    return [
        [
            (card["image"], card["page"])
            for card in household["cards"]
            if card["role"] == "coding-front"
        ]
        for household in record["dwelling"]["households"]
    ]


def _coding_cards(record: dict[str, Any]) -> frozenset[tuple[str, int]]:
    """The merge key (D026): scan and page, which a re-extraction can't change."""
    return frozenset(card for cards in _household_cards(record) for card in cards)


def _merge(
    previous: list[dict[str, Any]], records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Rebuilt records replace the previous ones whose cards they all cover.

    A previous record this run rebuilt only in part (a card unread, unplaced or
    with no record_id) is kept, and the rebuilt records sharing its cards are
    dropped, so no household goes missing.
    """
    while True:
        built = {card for record in records for card in _coding_cards(record)}
        partial = set().union(
            *(
                _coding_cards(old)
                for old in previous
                if _coding_cards(old) & built and not _coding_cards(old) <= built
            )
        )
        if not partial:
            break
        log.warning(
            "%s: rebuilt in part, previous lines kept",
            ", ".join(f"{image} p{page}" for image, page in sorted(partial)),
        )
        records = [r for r in records if not _coding_cards(r) & partial]
    by_card = {card: record for record in records for card in _coding_cards(record)}
    merged = list(records)
    for old in previous:
        rebuilt = _coding_cards(old) & by_card.keys()
        if rebuilt:
            _keep_corrections(old, by_card[min(rebuilt)])
        else:
            merged.append(old)
    return sorted(merged, key=lambda record: min(_coding_cards(record)))


def _keep_corrections(old: dict[str, Any], new: dict[str, Any]) -> None:
    corrections = list(_corrected_fields(old))
    if not corrections:
        return
    image, page = min(_coding_cards(old))
    if _household_cards(new) != _household_cards(old):
        raise MergeRefused(f"{image} p{page}: reviewed record was regrouped")
    for path, field in corrections:
        *parents, last = path
        try:
            reduce(getitem, parents, new)[last] = field
        except (KeyError, IndexError) as error:
            where = "/".join(map(str, path))
            raise MergeRefused(
                f"{image} p{page}: corrected field {where} has no place in the "
                "rebuilt record"
            ) from error
    dwelling = new["dwelling"]
    for kept, household in zip(old["dwelling"]["households"], dwelling["households"]):
        try:
            household["record_id"] = build_record_id(
                dwelling["municipality"]["value"] or "",
                dwelling["dwelling_no"]["value"] or "",
                household["household_no"]["value"] or "",
            )
        except ValueError:  # a blanked identity can't form an id
            household["record_id"] = kept["record_id"]
    # A corrected identity rebuilds record_id, which the reviewer never saw.
    if errors := _schema_errors(new):
        raise MergeRefused(
            f"{image} p{page}: reviewed record fails the schema once its "
            f"corrections are applied: {'; '.join(errors)}"
        )


def _corrected_fields(
    node: Any, path: tuple = ()
) -> Iterator[tuple[tuple, dict[str, Any]]]:
    if isinstance(node, dict):
        if node.get("origin") == "corrected":
            yield path, node
            return
        children = node.items()
    elif isinstance(node, list):
        children = enumerate(node)
    else:
        return
    for key, child in children:
        yield from _corrected_fields(child, (*path, key))


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)

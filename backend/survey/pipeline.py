"""One run over a folder of scan PDFs, start to finish (FR-17, IT-120).

Each PDF is split into page images, sorted into cards by the segmenter, and
every numeric coding card is extracted, built into a D007 record and scored.
A region's records go to ``<out_dir>/<region>.jsonl``. Reruns are safe
(NFR-07, NFR-04, D026): cached readings are replayed, records are merged with
the previous file by the coding cards they were read from, and a reviewer's
``corrected`` field is never overwritten.

A page the segmenter cannot place, a card with no readable identity and a card
the extractor fails on are each logged and skipped; the run carries on.

Stopgaps until the work they stand in for lands:

- One record per coding card. Association (IT-105) groups households into
  dwellings, and survey-front extraction is IT-117; until then the other
  three cards of a record are not read.
- Gemini alone, so every field scores as NO_SECOND_OPINION (D016), refined by
  its self-reported band when it gave one. The Qwen arm and merge are
  IT-124/IT-125. A field the extractor never returned scores 0.0.
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from functools import reduce
from operator import getitem
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from survey.confidence.agreement import NO_SECOND_OPINION
from survey.confidence.card import card_confidence
from survey.confidence.field import confidence_for
from survey.extraction.base import ExtractionResult, Extractor
from survey.extraction.json_extraction import parse_confidence_bands
from survey.extraction.record import FIELD_MAP, build_record
from survey.segmentation.pdf_pages import extract_image
from survey.segmentation.segmenter import CardType, classify_page, segment_pages

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    records: int = 0
    skipped_pages: int = 0  # not a card the segmenter recognises
    unreadable_cards: int = 0  # no municipality, dwelling or household number
    failed_cards: int = 0  # extractor raised or returned nothing usable
    failed_pdfs: int = 0  # could not be opened or split into pages


def run(
    scan_dir: Path,
    *,
    region: str,
    extractor: Extractor,
    out_dir: Path,
    raw_dir: Path | None = None,
) -> RunSummary:
    """Process every PDF in ``scan_dir`` and write ``<region>.jsonl``."""
    summary = RunSummary()
    out_path = out_dir / f"{region}.jsonl"
    previous = _read_records(out_path)  # first, so a damaged file costs no quota
    records: list[dict[str, Any]] = []
    for pdf in sorted(scan_dir.glob("*.pdf")):
        log.info("%s: reading", pdf.name)
        try:
            records += _run_pdf(pdf, region, extractor, raw_dir, summary)
        except Exception:  # without this, one damaged PDF loses the whole batch
            log.exception("%s: unreadable PDF, skipped", pdf.name)
            summary.failed_pdfs += 1

    merged = _merge(previous, records)
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
    raw_dir: Path | None,
    summary: RunSummary,
) -> list[dict[str, Any]]:
    records = []
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

        for card in cards:
            if card.card_type != CardType.NUMERIC_CODING:
                continue
            number = page_numbers[card.page_index]
            record = _read_card(
                card.image_path, pdf, number, region, extractor, raw_dir, summary
            )
            if record is not None:
                records.append(record)
    return records


def _read_card(
    image: Path,
    pdf: Path,
    number: int,
    region: str,
    extractor: Extractor,
    raw_dir: Path | None,
    summary: RunSummary,
) -> dict[str, Any] | None:
    where = f"{pdf.name} p{number}"
    cache = (
        raw_dir / extractor.name / f"{pdf.stem}_p{number:04d}.json" if raw_dir else None
    )
    result = None
    if cache and cache.exists():
        result = ExtractionResult(**json.loads(cache.read_text()))
    if result is None or not result.fields:
        try:
            result = extractor.extract(image)
        except Exception:  # one bad card must not end a run of hundreds
            log.exception("%s: extraction failed, skipped", where)
            summary.failed_cards += 1
            return None
        if cache and result.raw_text:
            cache.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(cache, json.dumps(asdict(result)))
    if not result.fields:
        log.error("%s: no usable reading, skipped", where)
        summary.failed_cards += 1
        return None
    try:
        record = build_record(
            result.fields,
            region=region,
            batch=pdf.name,
            image=pdf.name,
            page=number,
            struck=result.struck,
        )
    except ValueError as error:
        log.warning("%s: %s, skipped", where, error)
        summary.unreadable_cards += 1
        return None
    # The Gemini extractor's `name` carries -banded/-struck suffixes; the
    # confidence tables are keyed by the bare model id.
    _score(record, result, getattr(extractor, "model_id", extractor.name))
    return record


def _score(record: dict[str, Any], result: ExtractionResult, model: str) -> None:
    """Fill in field and card confidence, which build_record leaves null."""
    bands = parse_confidence_bands(result.raw_text)
    dwelling = record["dwelling"]
    household = dwelling["households"][0]
    groups = {
        "dwelling": dwelling,
        "household": household,
        "house": dwelling["house"],
        "head": household["head"],
        "counts": household["counts"],
        "coding": household["coding"],
    }
    scores = []
    for label, (key, group) in FIELD_MAP.items():
        field = groups[group][key]
        if field["status"] == "omitted":
            score = 0.0
        else:
            score = confidence_for(NO_SECOND_OPINION, model, bands.get(label))
        field["confidence"] = score
        scores.append(score)
    household["cards"][0]["confidence"] = card_confidence(scores)


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


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
    """Rebuilt records replace the previous ones they share a card with."""
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
        raise ValueError(f"{image} p{page}: reviewed record was regrouped")
    for path, field in corrections:
        *parents, last = path
        try:
            reduce(getitem, parents, new)[last] = field
        except (KeyError, IndexError) as error:
            where = "/".join(map(str, path))
            raise ValueError(
                f"{image} p{page}: corrected field {where} has no place in the "
                "rebuilt record"
            ) from error


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
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

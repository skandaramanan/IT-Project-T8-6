"""One run over a folder of scan PDFs, start to finish (FR-17, IT-120).

Each PDF is split into page images, sorted into cards by the segmenter, and
every numeric coding card is extracted, built into a D007 record and scored.
A region's records go to ``<out_dir>/<region>.jsonl``, overwritten each run.

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
from dataclasses import dataclass
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
    records: list[dict[str, Any]] = []
    for pdf in sorted(scan_dir.glob("*.pdf")):
        log.info("%s: reading", pdf.name)
        try:
            records += _run_pdf(pdf, region, extractor, raw_dir, summary)
        except Exception:  # without this, one damaged PDF loses the whole batch
            log.exception("%s: unreadable PDF, skipped", pdf.name)
            summary.failed_pdfs += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{region}.jsonl"
    out_path.write_text("".join(json.dumps(record) + "\n" for record in records))
    summary.records = len(records)
    log.info("wrote %d records to %s", len(records), out_path)
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
    try:
        result = extractor.extract(image)
    except Exception:  # one bad card must not end a run of hundreds
        log.exception("%s: extraction failed, skipped", where)
        summary.failed_cards += 1
        return None
    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{pdf.stem}_p{number:04d}.txt").write_text(result.raw_text or "")
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

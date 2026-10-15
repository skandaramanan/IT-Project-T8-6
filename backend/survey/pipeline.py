"""One run over a folder of scan PDFs, start to finish (FR-17, IT-120).

Each PDF is split into page images and sorted into cards by the segmenter.
Every numeric coding card is extracted (and every survey front, given a front
extractor), the cards are grouped into dwellings (IT-105), and each dwelling is
built into one D007 record and scored. Given a notes extractor, each front's
back is read too and its notes attached to the dwelling (FR-05, IT-89). A
region's records go to ``<out_dir>/<region>.jsonl``, and a file holding
another region's records is refused (FR-02). Reruns are safe (NFR-07,
NFR-04, D026): cached readings are replayed, records are merged with the
previous file by the coding cards they were read from, and a reviewer's
``corrected`` field is never overwritten. Every record is validated against
the D007 envelope (IT-66): a new one that fails is logged and not written, and
a previous one that fails stops the run.

A page the segmenter cannot place, a blank coding card and a card the
extractor fails on are each logged and skipped; the run carries on unless
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
from collections import Counter
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from functools import reduce
from operator import getitem
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from survey.association.dwelling import FRONT_FLAGS, ReviewFlag
from survey.association.notes import (
    FRONT,
    ReverseSlot,
    add_back_card,
    assign_household,
    attach_notes,
    find_reverses,
    read_notes,
)
from survey.association.notes import SOURCE as SURVEY_BACK
from survey.association.records import FRONT_SLOTS, Locate, build_dwelling_records
from survey.confidence.agreement import NO_SECOND_OPINION
from survey.confidence.card import card_confidence
from survey.confidence.field import confidence_for
from survey.extraction.base import ExtractionResult, Extractor
from survey.extraction.json_extraction import parse_confidence_bands
from survey.extraction.record import (
    FIELD_MAP,
    SCHEMA_VERSION,
    build_record_id,
    fill_identity,
    identity_of,
    normalise,
)
from survey.records import current_fields, schema_errors, write_atomic
from survey.segmentation.pdf_pages import extract_image
from survey.segmentation.segmenter import (
    CardType,
    SegmentedCard,
    classify_page,
    segment_pages,
)

log = logging.getLogger(__name__)

MAX_FAILURE_STREAK = 3  # a daily cap fails every card; stop instead of backing off each


class MergeRefused(ValueError):
    """The previous results can't be merged safely, so nothing was written."""


@dataclass
class RunSummary:
    records: int = 0
    skipped_pages: int = 0  # not a card the segmenter recognises, or a blank one
    unreadable_cards: int = 0  # dwellings with a household identity blank or unreadable
    unplaced_cards: int = 0  # read, but fits no dwelling: written on its own
    failed_cards: int = 0  # extractor raised or returned nothing usable
    failed_pdfs: int = 0  # could not be opened or split into pages
    failure_streak: int = 0  # consecutive failed cards; reaching the cap stops the run
    invalid_records: int = 0  # failed the envelope, not written
    unattached_notes: int = 0  # notes read whose dwelling has no record


def run(
    scan_dir: Path,
    *,
    region: str,
    extractor: Extractor,
    out_dir: Path,
    raw_dir: Path | None = None,
    fresh: bool = False,
    front_extractor: Extractor | None = None,
    notes_extractor: Extractor | None = None,
    identity_extractor: Extractor | None = None,
) -> RunSummary:
    """Process every PDF in ``scan_dir`` and write ``<region>.jsonl``.

    ``front_extractor`` reads the survey fronts too; without it they are not
    read. ``notes_extractor`` reads each front's back; without it a record
    keeps the notes a previous run read. ``identity_extractor`` reads again
    the identity block of a coding card that gave no usable record_id.
    ``fresh`` sets the cached readings
    aside (``<extractor>.previous``) and reads every card again; corrections
    are still kept. Set aside once, at
    the start, so a fresh run cut short resumes with a plain rerun.
    """
    if notes_extractor and not front_extractor:
        # A note finds its record through its front's card entry, which only
        # a read front gets.
        raise ValueError("reading notes needs front_extractor too")
    summary = RunSummary()
    out_path = out_dir / f"{region}.jsonl"
    _read_records(out_path, region)  # fail fast: a damaged file must cost no quota
    readers = (extractor, front_extractor, notes_extractor, identity_extractor)
    for reader in filter(None, readers):
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
                pdf,
                region,
                extractor,
                front_extractor,
                notes_extractor,
                identity_extractor,
                raw_dir,
                summary,
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
    notes_extractor: Extractor | None,
    identity_extractor: Extractor | None,
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
            # An unusable front counts as a blank one, so its dwelling is
            # still written; an unusable coding card has no household to add.
            if result is not None and (
                result.fields or card.card_type is CardType.FRONT
            ):
                readings[card] = result
        if front_extractor:
            cards = recover_coding_cards(
                cards, readings, page_numbers, pdf, extractor, raw_dir, summary
            )

        def locate(card: SegmentedCard) -> tuple[str, int]:  # D026: scan and page
            return pdf.name, page_numbers[card.page_index]

        reread = (
            reread_identities(
                readings, locate, pdf, identity_extractor, raw_dir, summary
            )
            if identity_extractor
            else set()
        )

        records, dwellings, unplaced = build_dwelling_records(
            [(card, readings.get(card)) for card in cards],
            region=region,
            batch=pdf.name,
            locate=locate,
            fronts_read=front_extractor is not None,
            reread=reread,
        )
        # Inside the block: a back is read off the page images, which go with it.
        if notes_extractor:
            notes = find_reverses(dwellings, cards, pages, page_numbers)
            _add_notes(records, notes, locate, pdf, notes_extractor, raw_dir, summary)
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
        summary.unplaced_cards += ReviewFlag.UNPLACED in dwelling.flags
    for card in unplaced:
        # An unread card is already counted as failed.
        if card.card_type is CardType.NUMERIC_CODING and card in readings:
            log.warning("%s p%d: blank coding card, skipped", *locate(card))
            summary.skipped_pages += 1

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
            ids = ", ".join(
                h["record_id"] or "no record_id"
                for h in record["dwelling"]["households"]
            )
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


def recover_coding_cards(
    cards: list[SegmentedCard],
    readings: dict[SegmentedCard, ExtractionResult],
    page_numbers: list[int],
    pdf: Path,
    extractor: Extractor,
    raw_dir: Path | None,
    summary: RunSummary,
) -> list[SegmentedCard]:
    """``cards``, with a coding card the segmenter took for a front put back.

    A coding card whose ruled lines sit on the front threshold (216414 p194)
    reads with the front prompt as nothing, or as its codes in front fields,
    but never with an address. Each front with no address is read with the
    coding prompt, and is a coding card if that reading spells a record_id; a
    blank front, a back or a narrative sheet does not. Empty probe responses
    are expected, but API failures count toward the run's shared failure cap.
    """
    out = []
    for card in cards:
        result = readings.get(card)
        if (
            card.card_type is CardType.FRONT
            and (result is not None and not normalise(result.fields.get("Address")))
            and summary.failure_streak < MAX_FAILURE_STREAK
        ):
            number = page_numbers[card.page_index]
            coding = _reading(
                card.image_path,
                pdf,
                number,
                extractor,
                raw_dir,
                summary,
                expected_empty=True,
            )
            try:
                identity_of(coding.fields if coding else {})
            except ValueError:
                pass
            else:
                log.warning("%s p%d: a coding card, not a front", pdf.name, number)
                del readings[card]
                card = replace(card, card_type=CardType.NUMERIC_CODING)
                readings[card] = coding
        out.append(card)
    return out


def reread_identities(
    readings: dict[SegmentedCard, ExtractionResult],
    locate: Locate,
    pdf: Path,
    extractor: Extractor,
    raw_dir: Path | None,
    summary: RunSummary,
) -> set[SegmentedCard]:
    """Each coding card with values but no usable record_id has its identity
    block read again; where that reading only fills what the first left blank
    or malformed, it is taken (D007). Returns the cards filled."""
    filled = set()
    for card, result in list(readings.items()):
        if card.card_type is not CardType.NUMERIC_CODING or not any(
            map(normalise, result.fields.values())
        ):
            continue
        try:
            identity_of(result.fields)
            continue
        except ValueError:
            pass
        if summary.failure_streak >= MAX_FAILURE_STREAK:
            break
        _, number = locate(card)
        second = _reading(card.image_path, pdf, number, extractor, raw_dir, summary)
        try:
            fields = fill_identity(result.fields, second.fields if second else {})
        except ValueError:
            continue
        readings[card] = replace(result, fields=fields)
        filled.add(card)
    return filled


def _add_notes(
    records: list[dict[str, Any]],
    slots: list[ReverseSlot],
    locate: Locate,
    pdf: Path,
    extractor: Extractor,
    raw_dir: Path | None,
    summary: RunSummary,
) -> None:
    """Each back read through the card cache, its note attached to its
    dwelling's record (FR-05)."""

    def read(slot: ReverseSlot) -> ExtractionResult | None:
        if summary.failure_streak >= MAX_FAILURE_STREAK:
            return None  # omitted, so the merge keeps any earlier reading
        return _reading(slot.image, pdf, slot.page, extractor, raw_dir, summary)

    for note in attach_notes(records, read_notes(slots, read), locate):
        # A dwelling with no record is logged already; only lost text is news.
        if note.text["status"] == "ok":
            log.warning(
                "%s p%d: notes read but the dwelling has no record, not written",
                *locate(note.slot.front),
            )
            summary.unattached_notes += 1


def _reading(
    image: Path,
    pdf: Path,
    number: int,
    extractor: Extractor,
    raw_dir: Path | None,
    summary: RunSummary,
    *,
    expected_empty: bool = False,
) -> ExtractionResult | None:
    """The card's cached reading, or a new one; None if the extractor failed.

    A reading with no usable fields is still returned (and stays cached, so it
    is not paid for again), but counts as a failed card unless an empty
    response is expected from a recovery probe.
    """
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
        if expected_empty:
            summary.failure_streak = 0
            return result
        log.error("%s: no usable reading", where)
        summary.failed_cards += 1
        return result
    summary.failure_streak = 0
    return result


def _schema_errors(record: dict[str, Any]) -> list[str]:
    """Every way ``record`` breaks the envelope, as ``"<path>: <reason>"``."""
    return schema_errors(record)


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

    A previous record this run rebuilt only in part (a card unread) is kept,
    and the rebuilt records sharing its cards are dropped, so no household goes
    missing.
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
            new = by_card[min(rebuilt)]
            _keep_front(old, new)
            _keep_notes(old, new)
            _keep_corrections(old, new)
        else:
            merged.append(old)
    _settle_identities(merged)
    # Last: kept notes and a corrected identity both outdate household_id.
    for record in merged:
        for note in record["dwelling"].get("notes", []):
            assign_household(note, record["dwelling"]["households"])
    return sorted(merged, key=lambda record: min(_coding_cards(record)))


def _settle_identities(records: list[dict[str, Any]]) -> None:
    """A record_id nulled because two households shared it comes back once a
    correction leaves it unshared, and identity flags a correction settled go."""
    flagged = [
        record["dwelling"]
        for record in records
        if _IDENTITY_FLAGS & set(record["dwelling"].get("flags", []))
    ]
    pending = [
        (household, _readable_id(dwelling, household))
        for dwelling in flagged
        for household in dwelling["households"]
        if household["record_id"] is None
    ]
    # A later duplicate in a mismatched dwelling lost its municipality when
    # grouping discarded that card's fields. It may still share any candidate
    # with the same dwelling/household suffix, including in another record.
    uncertain_suffixes = set()
    for dwelling in flagged:
        if ReviewFlag.DUPLICATE_RECORD_ID not in dwelling.get("flags", []):
            continue
        for household in dwelling["households"]:
            if (
                household["record_id"]
                or _identity_parts(dwelling, household) is not None
            ):
                continue
            try:
                identity = build_record_id(
                    "00",
                    dwelling["dwelling_no"]["value"] or "",
                    household["household_no"]["value"] or "",
                )
            except ValueError:
                uncertain_suffixes.add(None)
            else:
                uncertain_suffixes.add(identity.partition("-")[2])
    taken = Counter(
        household.get("record_id")
        for record in records
        for household in record["dwelling"]["households"]
    )
    taken.update(record_id for _, record_id in pending)
    for household, record_id in pending:
        if (
            record_id
            and taken[record_id] == 1
            and None not in uncertain_suffixes
            and record_id.partition("-")[2] not in uncertain_suffixes
        ):
            household["record_id"] = record_id
    for dwelling in flagged:
        ids = [
            (h["record_id"], _readable_id(dwelling, h)) for h in dwelling["households"]
        ]
        flags = set(dwelling.pop("flags"))
        if all(readable for _, readable in ids):
            flags.discard(ReviewFlag.MISSING_RECORD_ID)
        if all(record_id for record_id, _ in ids):
            flags.discard(ReviewFlag.DUPLICATE_RECORD_ID)
        if flags:
            dwelling["flags"] = sorted(flags)


_IDENTITY_FLAGS = {ReviewFlag.MISSING_RECORD_ID, ReviewFlag.DUPLICATE_RECORD_ID}


def _identity_parts(
    dwelling: dict[str, Any], household: dict[str, Any]
) -> tuple[str, str, str] | None:
    """Use only municipality evidence belonging to this household.

    Later cards' municipality fields are discarded when households are grouped.
    An existing ID retains that evidence; a null ID in a mismatched dwelling
    does not. Only an explicit municipality correction can replace it safely.
    """
    municipality = dwelling["municipality"]
    value = municipality["value"] or ""
    if municipality.get("origin") != "corrected":
        if household["record_id"]:
            value = household["record_id"].split("-")[0]
        else:
            mismatch = ReviewFlag.MUNICIPALITY_MISMATCH in dwelling.get("flags", [])
            if mismatch and household is not dwelling["households"][0]:
                return None
    return (
        value,
        dwelling["dwelling_no"]["value"] or "",
        household["household_no"]["value"] or "",
    )


def _readable_id(dwelling: dict[str, Any], household: dict[str, Any]) -> str | None:
    """The record_id supported by this household's available identity evidence."""
    parts = _identity_parts(dwelling, household)
    if parts is None:
        return None
    try:
        return build_record_id(*parts)
    except ValueError:
        return None


def _front_read(dwelling: dict[str, Any]) -> bool:
    fields = [dwelling[key] for key in FRONT_SLOTS if key in dwelling]
    fields += dwelling.get("handwritten", {}).values()
    return any(field["status"] != "omitted" for field in fields)


def _fronts(dwelling: dict[str, Any]) -> list[dict[str, Any]]:
    """The dwelling's front card entries. A run with or without notes adds or
    leaves out the backs', so those don't say whether it was regrouped."""
    return [card for card in dwelling.get("cards", []) if card["role"] != SURVEY_BACK]


def _keep_front(old: dict[str, Any], new: dict[str, Any]) -> None:
    """A front read before but unusable now (say, on ``--fresh``) keeps what
    was read before, rather than blanking the address and persons."""
    before, now = old["dwelling"], new["dwelling"]
    if _front_read(now) or not _front_read(before):
        return
    if _fronts(before) != _fronts(now):  # different fronts: regrouped
        return
    for key in (*FRONT_SLOTS, "handwritten"):
        now[key] = before[key]
    if len(before["households"]) == len(now["households"]) == 1:
        now["households"][0]["persons"] = before["households"][0].get("persons", [])
    # Flags the unusable reading set give way to the kept reading's.
    flags = {f for f in now.get("flags", []) if f not in FRONT_FLAGS}
    flags |= {f for f in before.get("flags", []) if f in FRONT_FLAGS}
    now.pop("flags", None)
    if flags:
        now["flags"] = sorted(flags)
    image, page = now["cards"][0]["image"], now["cards"][0]["page"]
    log.warning("%s p%d: front unusable, previous reading kept", image, page)


def _keep_notes(old: dict[str, Any], new: dict[str, Any]) -> None:
    """Notes read before outlive a run that didn't read backs, and a back read
    before but unread or not found now keeps its text. Notes pair by front,
    which every note has, unlike its back."""
    before, now = old["dwelling"], new["dwelling"]
    if "notes" not in before:
        return
    kept = {note["front_page"]: note for note in before["notes"]}
    fronts = {
        card["page"]: card for card in now.get("cards", []) if card["role"] == FRONT
    }
    for page, note in kept.items():
        if page not in fronts and note["text"]["status"] != "omitted":
            log.warning(
                "%s p%d: front left the dwelling, its notes not kept",
                before["cards"][0]["image"],
                page,
            )
    if "notes" not in now:
        notes = [kept[page] for page in fronts if page in kept]
        for note in notes:
            _keep_back(now, fronts[note["front_page"]], note)
        if notes:
            now["notes"] = notes
        return
    for index, note in enumerate(now["notes"]):
        previous = kept.get(note["front_page"])
        if (
            previous
            and note["text"]["status"] == "omitted"
            and previous["text"]["status"] != "omitted"
            and note["page"] in (None, previous["page"])
        ):
            now["notes"][index] = previous
            if note["page"] is None:
                _keep_back(now, fronts[note["front_page"]], previous)
            log.warning(
                "%s p%d: back unread, previous notes kept",
                now["cards"][0]["image"],
                note["front_page"],
            )


def _keep_back(
    dwelling: dict[str, Any], front: dict[str, Any], note: dict[str, Any]
) -> None:
    if note["page"] is not None:
        add_back_card(dwelling, (front["image"], front["page"]), note["page"])


def _keep_corrections(old: dict[str, Any], new: dict[str, Any]) -> None:
    corrections = list(_corrected_fields(old))
    if not corrections:
        return
    image, page = min(_coding_cards(old))
    if _household_cards(new) != _household_cards(old):
        raise MergeRefused(f"{image} p{page}: reviewed record was regrouped")
    for path, field in corrections:
        try:
            *parents, last = _note_by_front(path, old, new)
            destination = reduce(getitem, parents, new)
            review = field.get("review", {})
            if review.get("state") == "pending" and field.get("origin") != "corrected":
                # Undo retains history; the current pending reading may change.
                destination[last]["review"] = deepcopy(review)
            else:
                destination[last] = deepcopy(field)
            if review:
                new["schema_version"] = SCHEMA_VERSION
        except (KeyError, IndexError) as error:
            where = "/".join(map(str, path))
            raise MergeRefused(
                f"{image} p{page}: corrected field {where} has no place in the "
                "rebuilt record"
            ) from error
    # A corrected identity rebuilds record_id, which the reviewer never saw.
    # Nothing else does: that would undo the null a duplicate was given.
    identity_paths = {path for path, _ in corrections if _is_identity(path)}
    if identity_paths:
        dwelling = new["dwelling"]
        shared_identity = any(len(path) == 2 for path in identity_paths)
        for index, (kept, household) in enumerate(
            zip(old["dwelling"]["households"], dwelling["households"])
        ):
            if (
                not shared_identity
                and ("dwelling", "households", index, "household_no")
                not in identity_paths
            ):
                continue
            identity = _identity_parts(dwelling, household)
            if identity is None:
                # The shared fields cannot recover a later card's lost reading.
                continue
            if not all(identity):  # a blanked identity can't form an id
                household["record_id"] = kept["record_id"]
                continue
            try:
                record_id = build_record_id(*identity)
            except ValueError as error:
                raise MergeRefused(
                    f"{image} p{page}: corrected identity: {error}"
                ) from error
            # Null IDs still need global duplicate checks after corrections.
            # Settlement restores them once their candidate is unambiguous.
            if household["record_id"] is not None:
                household["record_id"] = record_id
    if errors := _schema_errors(new):
        raise MergeRefused(
            f"{image} p{page}: reviewed record fails the schema once its "
            f"corrections are applied: {'; '.join(errors)}"
        )


def _is_identity(path: tuple) -> bool:
    """Municipality, dwelling number or a household number: what record_id is
    built from. The front's handwritten dwelling number is not."""
    return path in (("dwelling", "municipality"), ("dwelling", "dwelling_no")) or (
        len(path) == 4
        and path[:2] == ("dwelling", "households")
        and path[3] == "household_no"
    )


def _note_by_front(path: tuple, old: dict[str, Any], new: dict[str, Any]) -> tuple:
    """A corrected note goes back on the note for the same front: a gained or
    lost front shifts the list. KeyError when that front left the dwelling."""
    if path[:2] != ("dwelling", "notes"):
        return path
    front = old["dwelling"]["notes"][path[2]]["front_page"]
    indexes = {note["front_page"]: i for i, note in enumerate(new["dwelling"]["notes"])}
    index = indexes[front]
    return (*path[:2], index, *path[3:])


def _corrected_fields(
    node: Any, path: tuple = ()
) -> Iterator[tuple[tuple, dict[str, Any]]]:
    for field_path, field in current_fields(node, path):
        if field.get("origin") == "corrected" or field.get("review"):
            yield field_path, field


def _write_atomic(path: Path, text: str) -> None:
    write_atomic(path, text)

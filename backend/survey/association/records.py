"""Segmented, extracted cards to one D007 record per dwelling (FR-04).

Each coding card is a household and gives it its identity (``record_id``); the
survey front adds the address, the dwelling as written, and the person grid.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from survey.association.dwelling import (
    Dwelling,
    ReviewFlag,
    associate,
    dwelling_key,
    dwelling_number,
)
from survey.extraction.base import ExtractionResult, Extractor
from survey.extraction.record import build_record
from survey.extraction.survey_front import SOURCE as SURVEY_FRONT
from survey.extraction.survey_front import build_survey_front
from survey.segmentation.segmenter import CardType, SegmentedCard

Extracted = list[tuple[SegmentedCard, ExtractionResult | None]]
# Where a card sits in the scans, as a record names it: (image, page).
Locate = Callable[[SegmentedCard], tuple[str, int]]

log = logging.getLogger(__name__)

# Front fields D007 already has a dwelling slot for; the rest go in ``handwritten``.
FRONT_SLOTS = ("address", "families_in_dwelling")


def extract(
    cards: Sequence[SegmentedCard], *, coding: Extractor, front: Extractor
) -> Extracted:
    """Each card read by the extractor for its type; a reverse is not read."""
    by_type = {CardType.NUMERIC_CODING: coding, CardType.FRONT: front}
    return [
        (card, by_type[card.card_type].extract(card.image_path))
        if card.card_type in by_type
        else (card, None)
        for card in cards
    ]


def _numbers(extracted: Extracted) -> list[tuple[SegmentedCard, str | None]]:
    """Each card with its dwelling number. An unnumbered front marked as a
    continuation at the last numbered front's address ("89 Elphin St Cont.") is
    its overflow and takes its number; any other stays unnumbered and flagged."""
    numbers: list[tuple[SegmentedCard, str | None]] = []
    last = None
    for card, result in extracted:
        number = dwelling_number(card, result.fields) if result else None
        if card.card_type is CardType.FRONT and result:
            words = re.findall(r"\w+", (result.fields.get("Address") or "").lower())
            cont = any(w.startswith("cont") for w in words)
            # house number and street, the first two words that aren't the marker
            street = tuple(w[:5] for w in words if not w.startswith("cont"))[:2]
            if dwelling_key(number):
                last = (street, number)
            elif cont and len(street) == 2 and last and last[0] == street:
                number = last[1]
        numbers.append((card, number))
    return numbers


def _image_page(card: SegmentedCard) -> tuple[str, int]:
    return str(card.image_path), card.page_index + 1


def _card(card: SegmentedCard, role: str, locate: Locate) -> dict[str, Any]:
    image, page = locate(card)
    return {"role": role, "image": image, "page": page, "confidence": None}


def _record(
    dwelling: Dwelling,
    results: dict[SegmentedCard, ExtractionResult],
    *,
    region: str,
    batch: str | None,
    locate: Locate,
) -> dict[str, Any] | None:
    if dwelling.flags & {ReviewFlag.UNREAD_CODING_CARD, ReviewFlag.UNREAD_FRONT}:
        return None
    households = []
    for card in dwelling.cards:
        if card.card_type is not CardType.NUMERIC_CODING:
            continue
        result = results[card]
        image, page = locate(card)
        try:
            households.append(
                build_record(
                    result.fields,
                    region=region,
                    batch=batch,
                    image=image,
                    page=page,
                    struck=result.struck,
                )
            )
        except (
            ValueError
        ) as error:  # no record_id without municipality, dwelling, household
            log.warning("%s p%d: %s, skipped", image, page, error)
            dwelling.flags.add(ReviewFlag.MISSING_RECORD_ID)
    if not households:
        return None
    if len({h["dwelling"]["municipality"]["value"] for h in households}) > 1:
        dwelling.flags.add(ReviewFlag.MUNICIPALITY_MISMATCH)
        return None

    record = households[0]
    out = record["dwelling"]
    out["households"] = [h["dwelling"]["households"][0] for h in households]

    # A front not read (a run without them, or a failed reading) adds nothing.
    fronts = [
        c for c in dwelling.cards if c.card_type is CardType.FRONT and c in results
    ]
    if not fronts:
        return record
    readings = [build_survey_front(results[c].fields) for c in fronts]
    persons = [p for reading in readings for p in reading.pop("persons")]
    # A later front fills what the first left blank.
    handwritten = readings[0]
    for reading in readings[1:]:
        for key, field in reading.items():
            if field["status"] != "ok":
                continue
            if handwritten[key]["status"] != "ok":
                handwritten[key] = field
            elif handwritten[key]["value"] != field["value"]:
                dwelling.flags.add(ReviewFlag.FRONTS_DISAGREE)
    for key in FRONT_SLOTS:
        out[key] = handwritten.pop(key)
    out["handwritten"] = handwritten
    out["cards"] = [_card(c, SURVEY_FRONT, locate) for c in fronts]
    if len(out["households"]) == 1:
        out["households"][0]["persons"] = persons
    elif persons:
        dwelling.flags.add(ReviewFlag.PERSONS_UNASSIGNED)
    return record


def build_dwelling_records(
    extracted: Extracted,
    *,
    region: str,
    batch: str | None = None,
    locate: Locate = _image_page,
    fronts_read: bool = True,
) -> tuple[list[dict[str, Any]], list[Dwelling], list[SegmentedCard]]:
    """Records, the dwellings they came from (with review flags), and the
    cards that could not be placed.

    A dwelling with no usable coding card, coding cards from different
    municipalities, or a record_id another dwelling also has yields no record:
    there is no one identity to record it under. Nor does one with a coding
    card that has no reading, which would otherwise be recorded a household
    short, or one with a survey front that has no reading this run (its request
    failed, or the run stopped first): it is retried next run, and until then
    the grouping around it can't be trusted. A front whose reading came back
    unusable is passed in with empty fields and counts as a blank front. It stays
    in the dwellings list with its flags. ``fronts_read=False`` says the
    fronts were never read, so their missing readings are expected.

    ``locate`` names each card's place in the scans (D026); the default, the
    card's own image and position, suits cards that are their own scans.
    """
    results = {card: result for card, result in extracted if result is not None}
    dwellings, unplaced = associate(_numbers(extracted))
    # An unread coding card has no dwelling number, so it is never placed; it
    # belongs to the last dwelling started before it.
    for card in unplaced:
        if card.card_type is CardType.NUMERIC_CODING and card not in results:
            before = [d for d in dwellings if d.cards[0].page_index < card.page_index]
            if before:
                before[-1].flags.add(ReviewFlag.UNREAD_CODING_CARD)
    if fronts_read:
        for d in dwellings:
            if any(c.card_type is CardType.FRONT and c not in results for c in d.cards):
                d.flags.add(ReviewFlag.UNREAD_FRONT)
    built = [
        (d, _record(d, results, region=region, batch=batch, locate=locate))
        for d in dwellings
    ]
    ids = Counter(
        h["record_id"] for _, r in built if r for h in r["dwelling"]["households"]
    )
    records = []
    for dwelling, record in built:
        if record is None:
            continue
        if any(ids[h["record_id"]] > 1 for h in record["dwelling"]["households"]):
            dwelling.flags.add(ReviewFlag.DUPLICATE_RECORD_ID)
        else:
            records.append(record)
    return records, dwellings, unplaced

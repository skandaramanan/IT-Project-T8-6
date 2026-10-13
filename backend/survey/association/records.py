"""Segmented, extracted cards to one D007 record per dwelling (FR-04).

Each coding card is a household and gives it its identity (``record_id``); the
survey front adds the address, the dwelling as written, and the person grid.
A household whose identity doesn't check out is still written, with a null
``record_id`` and its dwelling's flags saying why (D007), so a reviewer can
fix it rather than lose it.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Collection, Sequence
from typing import Any

from survey.association.dwelling import (
    Dwelling,
    ReviewFlag,
    associate,
    dwelling_key,
    dwelling_number,
    pair_by_position,
)
from survey.extraction.base import ExtractionResult, Extractor
from survey.extraction.record import build_record, normalise
from survey.extraction.survey_front import SOURCE as SURVEY_FRONT
from survey.extraction.survey_front import build_survey_front
from survey.segmentation.segmenter import CardType, SegmentedCard

Extracted = list[tuple[SegmentedCard, ExtractionResult | None]]
# Where a card sits in the scans, as a record names it: (image, page).
Locate = Callable[[SegmentedCard], tuple[str, int]]

log = logging.getLogger(__name__)

# A household not placed by its dwelling number.
UNSURE = {ReviewFlag.UNPLACED, ReviewFlag.PAIRED_BY_POSITION}

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
        household = build_record(
            result.fields,
            region=region,
            batch=batch,
            image=image,
            page=page,
            struck=result.struck,
        )
        if household["dwelling"]["households"][0]["record_id"] is None:
            # A part blank or unreadable, e.g. a struck number read with its
            # replacement (276303).
            log.warning(
                "%s p%d: no record_id from %s", image, page, _identity(household)
            )
            dwelling.flags.add(ReviewFlag.MISSING_RECORD_ID)
        households.append(household)
    if not households:
        return None
    # The dwelling takes the first card's municipality; each household keeps
    # its own in record_id.
    if len({h["dwelling"]["municipality"]["value"] for h in households}) > 1:
        dwelling.flags.add(ReviewFlag.MUNICIPALITY_MISMATCH)

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
    reread: Collection[SegmentedCard] = (),
) -> tuple[list[dict[str, Any]], list[Dwelling], list[SegmentedCard]]:
    """Records, the dwellings they came from (with review flags), and the
    cards that could not be placed.

    Every coding card read with any value is written. One whose number fits no
    front pairs with the front at the batch's usual offset, flagged
    ``paired_by_position``; one that still fits none is a dwelling of its own,
    flagged ``unplaced``. A household with no record_id,
    or with one another household also has, is written with a null
    ``record_id``. A record's ``flags`` say why it needs a look. A coding card
    with no value at all is a blank page or a reverse, and is left unplaced.

    A dwelling with no coding card yields no record. Nor does one with a coding
    card that has no reading, which would otherwise be recorded a household
    short, or one with a survey front that has no reading this run (its request
    failed, or the run stopped first): it is retried next run, and until then
    the grouping around it can't be trusted. A front whose reading came back
    unusable is passed in with empty fields and counts as a blank front.
    ``fronts_read=False`` says the fronts were never read, so their missing
    readings and numbers are expected.

    ``reread`` are the coding cards whose identity a second reading filled
    in; each one's dwelling is flagged ``identity_reread``.

    ``locate`` names each card's place in the scans (D026); the default, the
    card's own image and position, suits cards that are their own scans.
    """
    results = {card: result for card, result in extracted if result is not None}
    dwellings, unplaced = associate(
        [
            (card, dwelling_number(card, r.fields) if r else None)
            for card, r in extracted
        ]
    )
    # An unread coding card has no dwelling number, so it is never placed; it
    # belongs to the last dwelling started before it.
    for card in unplaced:
        if card.card_type is CardType.NUMERIC_CODING and card not in results:
            before = [d for d in dwellings if d.cards[0].page_index < card.page_index]
            if before:
                before[-1].flags.add(ReviewFlag.UNREAD_CODING_CARD)
    # A read coding card no front fits is a household all the same; one with
    # no value at all is a blank page or a reverse taken for a card.
    strays = [
        c
        for c in unplaced
        if c.card_type is CardType.NUMERIC_CODING and _has_value(results.get(c))
    ]
    for card in strays:
        unplaced.remove(card)
    for card in pair_by_position(dwellings, strays):
        number = dwelling_key(dwelling_number(card, results[card].fields))
        dwellings.append(Dwelling(number, [card], {ReviewFlag.UNPLACED}))
    dwellings.sort(key=lambda d: d.cards[0].page_index)
    if fronts_read:
        for d in dwellings:
            if any(c.card_type is CardType.FRONT and c not in results for c in d.cards):
                d.flags.add(ReviewFlag.UNREAD_FRONT)
    for d in dwellings:
        if any(c in reread for c in d.cards):
            d.flags.add(ReviewFlag.IDENTITY_REREAD)
    built = [
        (d, _record(d, results, region=region, batch=batch, locate=locate))
        for d in dwellings
    ]
    # A record_id two households share is kept by neither, unless only one of
    # them sits with a front by its number and was read whole: a card placed
    # by position alone, or not at all, or whose identity a second reading
    # filled, is the likelier misread.
    second = {locate(c) for c in reread}

    def unsure(dwelling: Dwelling, household: dict[str, Any]) -> bool:
        card = household["cards"][0]
        return bool(dwelling.flags & UNSURE) or (card["image"], card["page"]) in second

    placed, lone = Counter(), Counter()
    for dwelling, record in built:
        for household in record["dwelling"]["households"] if record else []:
            if household["record_id"]:
                is_lone = unsure(dwelling, household)
                (lone if is_lone else placed)[household["record_id"]] += 1
    # Every front is unnumbered when none was read; flagging each is noise.
    quiet = set() if fronts_read else {ReviewFlag.MISSING_DWELLING_NO}
    records = []
    for dwelling, record in built:
        if record is None:
            continue
        for household in record["dwelling"]["households"]:
            record_id = household["record_id"]
            shared = placed[record_id] + lone[record_id] > 1
            if shared and (placed[record_id] != 1 or unsure(dwelling, household)):
                household["record_id"] = None
                dwelling.flags.add(ReviewFlag.DUPLICATE_RECORD_ID)
        if flags := dwelling.flags - quiet:
            record["dwelling"]["flags"] = sorted(map(str, flags))
        records.append(record)
    return records, dwellings, unplaced


def _has_value(result: ExtractionResult | None) -> bool:
    return result is not None and any(map(normalise, result.fields.values()))


def _identity(record: dict[str, Any]) -> str:
    """What was read for record_id, blanks shown as ?: 21-28548-1, 21-487-?."""
    dwelling = record["dwelling"]
    parts = (
        dwelling["municipality"],
        dwelling["dwelling_no"],
        dwelling["households"][0]["household_no"],
    )
    return "-".join(field["value"] or "?" for field in parts)

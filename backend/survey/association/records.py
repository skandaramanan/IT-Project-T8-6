"""Segmented, extracted cards to one D007 record per dwelling (FR-04).

Each coding card is a household and gives it its identity (``record_id``); the
survey front adds the address, the dwelling as written, and the person grid.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from survey.association.dwelling import Dwelling, ReviewFlag, associate, dwelling_number
from survey.extraction.base import ExtractionResult, Extractor
from survey.extraction.record import build_record
from survey.extraction.survey_front import SOURCE as SURVEY_FRONT
from survey.extraction.survey_front import build_survey_front
from survey.segmentation.segmenter import CardType, SegmentedCard

Extracted = list[tuple[SegmentedCard, ExtractionResult | None]]

# Front fields D007 already has a dwelling slot for; the rest go in ``handwritten``.
_SLOTS = ("address", "families_in_dwelling")


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


def _card(card: SegmentedCard, role: str) -> dict[str, Any]:
    image, page = str(card.image_path), card.page_index + 1
    return {"role": role, "image": image, "page": page, "confidence": None}


def _record(
    dwelling: Dwelling,
    results: dict[SegmentedCard, ExtractionResult],
    *,
    region: str,
    batch: str | None,
) -> dict[str, Any] | None:
    households = []
    for card in dwelling.cards:
        if card.card_type is not CardType.NUMERIC_CODING:
            continue
        result = results[card]
        try:
            households.append(
                build_record(
                    result.fields,
                    region=region,
                    batch=batch,
                    image=str(card.image_path),
                    page=card.page_index + 1,
                    struck=result.struck,
                )
            )
        except ValueError:  # no record_id without municipality, dwelling, household
            dwelling.flags.add(ReviewFlag.MISSING_RECORD_ID)
    if not households:
        return None

    record = households[0]
    out = record["dwelling"]
    out["households"] = [h["dwelling"]["households"][0] for h in households]

    fronts = [c for c in dwelling.cards if c.card_type is CardType.FRONT]
    if not fronts:
        return record
    readings = [build_survey_front(results[c].fields) for c in fronts]
    persons = [p for reading in readings for p in reading.pop("persons")]
    for key in _SLOTS:
        out[key] = readings[0].pop(key)
    out["handwritten"] = readings[0]
    out["cards"] = [_card(c, SURVEY_FRONT) for c in fronts]
    if len(out["households"]) == 1:
        out["households"][0]["persons"] = persons
    elif persons:
        dwelling.flags.add(ReviewFlag.PERSONS_UNASSIGNED)
    return record


def build_dwelling_records(
    extracted: Extracted, *, region: str, batch: str | None = None
) -> tuple[list[dict[str, Any]], list[Dwelling], list[SegmentedCard]]:
    """Records, the dwellings they came from (with review flags), and the
    cards that could not be placed.

    A dwelling with no usable coding card has no identity to record under, so
    it yields no record; it stays in the dwellings list with its flags.
    """
    results = {card: result for card, result in extracted if result is not None}
    dwellings, unplaced = associate(
        [
            (card, dwelling_number(card, r.fields) if r else None)
            for card, r in extracted
        ]
    )
    records = [
        record
        for dwelling in dwellings
        if (record := _record(dwelling, results, region=region, batch=batch))
    ]
    return records, dwellings, unplaced

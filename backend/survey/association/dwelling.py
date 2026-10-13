"""Groups segmented cards into dwellings by dwelling number (FR-04).

Takes a batch's cards in scan order, each paired with the dwelling number read
off it (top-left of a front, "Number of Dwelling" on a coding card, none on a
reverse). Proximity groups the cards; dwelling number cross-checks the group. A front
with no number (blank, unusable reading, or not read) takes its coding card's,
flagged, when no other front has that number. Anything else that does not check out is flagged
or left unplaced, never guessed.

A dwelling holds one coding card per household, matching D007's dwelling ->
households nesting; ``build_record`` splits them by "Number of Household".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from survey.extraction.record import normalise
from survey.segmentation.segmenter import CardType, SegmentedCard

# How far a coding card sits from its dwelling's first front, in pages. Across
# the 45 IT-123 folders, coding cards sit 1 to 4 pages before or after their
# front, a few households further; a card more than 8 away that matches by
# number alone is usually a misread.
NEAR_PAGES = 8


class ReviewFlag(StrEnum):
    MISSING_DWELLING_NO = "missing_dwelling_no"
    DUPLICATE_DWELLING_NO = "duplicate_dwelling_no"
    OUT_OF_ORDER = "out_of_order"
    NO_CODING_CARD = "no_coding_card"
    # More than one household, and the front does not say whose column is whose.
    PERSONS_UNASSIGNED = "persons_unassigned"
    # A coding card without municipality, dwelling or household number.
    MISSING_RECORD_ID = "missing_record_id"
    # Coding cards in one dwelling naming different municipalities.
    MUNICIPALITY_MISMATCH = "municipality_mismatch"
    # A record_id another coding card in the batch also has.
    DUPLICATE_RECORD_ID = "duplicate_record_id"
    # A coding card here has no reading (failed, or the run stopped first).
    UNREAD_CODING_CARD = "unread_coding_card"
    # A survey front here has no reading, so the grouping can't be trusted.
    UNREAD_FRONT = "unread_front"
    # Two fronts of one dwelling read differently for the same field; the
    # first front's value is kept.
    FRONTS_DISAGREE = "fronts_disagree"


@dataclass
class Dwelling:
    dwelling_no: str | None
    cards: list[SegmentedCard] = field(default_factory=list)  # scan order
    flags: set[ReviewFlag] = field(default_factory=set)


def dwelling_key(raw: str | None) -> str | None:
    """Leading zeros dropped: a dwelling number is an ordinal, not a code."""
    cleaned = normalise(raw)
    return str(int(cleaned)) if cleaned.isdigit() else None


def dwelling_number(card: SegmentedCard, fields: dict[str, str]) -> str | None:
    """The dwelling number an extractor read off this card, if it carries one."""
    if card.card_type is CardType.FRONT:
        return fields.get("Dwelling Number (top-left corner)")
    if card.card_type is CardType.NUMERIC_CODING:
        return fields.get("Number of Dwelling")
    return None


def associate(
    cards: Sequence[tuple[SegmentedCard, str | None]],
) -> tuple[list[Dwelling], list[SegmentedCard]]:
    """Dwellings, and the cards that could not be placed in one."""
    dwellings: list[Dwelling] = []
    unplaced: list[SegmentedCard] = []
    deferred: list[tuple[SegmentedCard, str, Dwelling | None]] = []
    current: Dwelling | None = None
    previous: CardType | None = None

    for card, raw in cards:
        key = dwelling_key(raw)
        if card.card_type is CardType.FRONT:
            # A second front with the same number is an overflow card.
            if current is None or key is None or key != current.dwelling_no:
                current = Dwelling(key)
                dwellings.append(current)
            current.cards.append(card)
        elif card.card_type is CardType.REVERSE:
            if current and previous is CardType.FRONT:
                current.cards.append(card)
            else:
                unplaced.append(card)
        elif key is None:
            unplaced.append(card)
        elif current and current.dwelling_no == key:
            current.cards.append(card)
        else:
            deferred.append((card, key, current))
        previous = card.card_type

    # A coding card away from its front joins it only if exactly one fits. One
    # whose number no front has joins the front before it if that front has no
    # number (blank, or not read): the card names the dwelling.
    counts = Counter(d.dwelling_no for d in dwellings)
    by_key = {d.dwelling_no: d for d in dwellings}

    def far(card: SegmentedCard, key: str) -> bool:
        return abs(card.page_index - by_key[key].cards[0].page_index) > NEAR_PAGES

    # Near cards first, so a far one sees the dwelling's own card already in it.
    deferred.sort(key=lambda d: counts[d[1]] == 1 and far(d[0], d[1]))
    for card, key, near in deferred:
        if counts[key] == 1 and far(card, key) and _has_coding(by_key[key]):
            # A misread number: the dwelling has its card, and this one would
            # only make a duplicate record_id that drops them both.
            unplaced.append(card)
        elif counts[key] == 1:
            by_key[key].cards.append(card)
            by_key[key].flags.add(ReviewFlag.OUT_OF_ORDER)
        elif counts[key] == 0 and near and near.dwelling_no in (None, key):
            near.dwelling_no = key
            near.cards.append(card)
            near.flags.add(ReviewFlag.MISSING_DWELLING_NO)
        else:
            unplaced.append(card)

    counts = Counter(d.dwelling_no for d in dwellings)  # with the named ones
    for d in dwellings:
        if d.dwelling_no is None:
            d.flags.add(ReviewFlag.MISSING_DWELLING_NO)
        elif counts[d.dwelling_no] > 1:
            d.flags.add(ReviewFlag.DUPLICATE_DWELLING_NO)
        if not _has_coding(d):
            d.flags.add(ReviewFlag.NO_CODING_CARD)
    return dwellings, unplaced


def _has_coding(dwelling: Dwelling) -> bool:
    return any(c.card_type is CardType.NUMERIC_CODING for c in dwelling.cards)

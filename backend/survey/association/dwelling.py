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

import re
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


def similar_numbers(first: str | None, second: str | None) -> bool:
    """Usable dwelling numbers differing by at most one insertion, deletion or
    substitution. Letters name distinct dwellings and must agree exactly."""
    a, b = dwelling_key(first), dwelling_key(second)
    if a is None or b is None:
        return False
    if a[-1].isalpha() or b[-1].isalpha():
        return a == b
    if len(a) > len(b):
        a, b = b, a
    if len(b) - len(a) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    return any(a == b[:i] + b[i + 1 :] for i in range(len(b)))


class ReviewFlag(StrEnum):
    MISSING_DWELLING_NO = "missing_dwelling_no"
    DUPLICATE_DWELLING_NO = "duplicate_dwelling_no"
    OUT_OF_ORDER = "out_of_order"
    NO_CODING_CARD = "no_coding_card"
    # More than one household, and the front does not say whose column is whose.
    PERSONS_UNASSIGNED = "persons_unassigned"
    # A coding card whose municipality, dwelling or household number is blank
    # or unreadable: written with record_id null.
    MISSING_RECORD_ID = "missing_record_id"
    # Coding cards in one dwelling naming different municipalities.
    MUNICIPALITY_MISMATCH = "municipality_mismatch"
    # A record_id another coding card in the batch also has: written null,
    # unless only this card sits with a front.
    DUPLICATE_RECORD_ID = "duplicate_record_id"
    # A coding card here has no reading (failed, or the run stopped first).
    UNREAD_CODING_CARD = "unread_coding_card"
    # A survey front here has no reading, so the grouping can't be trusted.
    UNREAD_FRONT = "unread_front"
    # Two fronts of one dwelling read differently for the same field; the
    # first front's value is kept.
    FRONTS_DISAGREE = "fronts_disagree"
    # A coding card no front fits, written as a dwelling of its own.
    UNPLACED = "unplaced"
    # A coding card whose number fits no front, paired with the front sitting
    # where this batch's coding cards usually sit from theirs.
    PAIRED_BY_POSITION = "paired_by_position"
    # A household whose record_id was completed by a second reading of its
    # card's identity block, which only filled what the first left blank.
    IDENTITY_REREAD = "identity_reread"


# Set from what the survey fronts read, not the coding cards.
FRONT_FLAGS = frozenset(
    {
        ReviewFlag.MISSING_DWELLING_NO,
        ReviewFlag.DUPLICATE_DWELLING_NO,
        ReviewFlag.FRONTS_DISAGREE,
        ReviewFlag.PERSONS_UNASSIGNED,
    }
)


@dataclass
class Dwelling:
    dwelling_no: str | None
    cards: list[SegmentedCard] = field(default_factory=list)  # scan order
    flags: set[ReviewFlag] = field(default_factory=set)


def dwelling_key(raw: str | None) -> str | None:
    """Leading zeros dropped: a dwelling number is an ordinal, not a code. A
    letter after it names another dwelling (487A is not 487), so it is kept."""
    match = re.fullmatch(r"(\d+)([A-Z]?)", normalise(raw).upper())
    return f"{int(match[1])}{match[2]}" if match else None


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


def pair_by_position(
    dwellings: Sequence[Dwelling],
    cards: Sequence[tuple[SegmentedCard, str | None]],
) -> list[SegmentedCard]:
    """Coding cards paired with the front at the batch's usual offset, as
    dwellings that hold one front and one coding card show it. A front only
    takes a card when its dwelling has none and the numbers differ by at most
    one edit. Missing numbers and different lettered dwellings stay unpaired.
    Returns the cards still unpaired."""
    offsets = Counter(
        coding[0].page_index - fronts[0].page_index
        for d in dwellings
        for fronts, coding in [_split(d)]
        if len(fronts) == len(coding) == 1
    )
    if not offsets:
        return [card for card, _ in cards]
    offset = offsets.most_common(1)[0][0]
    by_page = {
        c.page_index: d
        for d in dwellings
        for c in d.cards
        if c.card_type is CardType.FRONT
    }
    left = []
    for card, number in cards:
        d = by_page.get(card.page_index - offset)
        if d is None or _has_coding(d) or not similar_numbers(d.dwelling_no, number):
            left.append(card)
            continue
        d.cards.append(card)
        d.flags.discard(ReviewFlag.NO_CODING_CARD)
        d.flags.add(ReviewFlag.PAIRED_BY_POSITION)
    return left


def _split(dwelling: Dwelling) -> tuple[list[SegmentedCard], list[SegmentedCard]]:
    """The dwelling's fronts and coding cards."""
    return (
        [c for c in dwelling.cards if c.card_type is CardType.FRONT],
        [c for c in dwelling.cards if c.card_type is CardType.NUMERIC_CODING],
    )


def _has_coding(dwelling: Dwelling) -> bool:
    return any(c.card_type is CardType.NUMERIC_CODING for c in dwelling.cards)

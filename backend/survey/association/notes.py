"""Reverse-side interview notes, read verbatim and attached to their dwelling (FR-05).

A survey back says nothing about which dwelling it belongs to, so each note is
placed by the front scanned before it, never by its content:

1. :func:`find_reverses` picks each front's back.
2. :func:`read_notes` reads it into a D007 field object.
3. :func:`attach_notes` adds it to the dwelling's record as ``dwelling.notes``.

A blank back is read too, and comes back ``no_data``, FR-05's explicit empty.
Notes sit on the dwelling, not a household, because the front is one per
dwelling; see D007 for the schema and ``REVERSE_NOTES_PROMPT`` for what
"as written" means.

Not yet handled: printed reverse forms (R1) and confidence (FR-10).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from survey.association.dwelling import Dwelling
from survey.association.records import Locate
from survey.extraction.base import ExtractionResult
from survey.extraction.card_fields import (
    REVERSE_NOTES_LABEL,
    REVERSE_NOTES_SCHEMA_BY_NAME,
)
from survey.extraction.record import build_field, build_omitted_field
from survey.segmentation.segmenter import CardType, SegmentedCard

SOURCE = "survey-back"
FRONT = "survey-front"


class NoteFlag(StrEnum):
    # The card after the front is not its back: the back was not scanned, or
    # was taken for another card type.
    NO_REVERSE_FOUND = "no_reverse_found"
    # More than one page dropped after the front; which, if any, is its back
    # cannot be told from position.
    REVERSE_AMBIGUOUS = "reverse_ambiguous"
    # A front with no dwelling number straight after a front with no back --
    # the pattern a blank back showing its front through would leave.
    POSSIBLE_BLEED_THROUGH = "possible_bleed_through"
    # Text read off a page the segmenter dropped as blank.
    NOTE_ON_BLANK_PAGE = "note_on_blank_page"
    # More than one household in the dwelling, so no one household to name.
    HOUSEHOLD_AMBIGUOUS = "household_ambiguous"


@dataclass(frozen=True)
class ReverseSlot:
    """Where one front's back is, if anywhere.

    ``image`` is None when there is no page to read; ``page`` is the 1-based
    PDF page, not the index into the readable pages.
    """

    front: SegmentedCard
    image: Path | None
    page: int | None
    from_blank_page: bool = False
    flags: frozenset[NoteFlag] = frozenset()


@dataclass
class Note:
    slot: ReverseSlot
    text: dict[str, Any]  # a D007 field object
    flags: set[NoteFlag] = field(default_factory=set)


# --- 1. which page is each front's back --------------------------------------


def find_reverses(
    dwellings: Iterable[Dwelling],
    cards: Sequence[SegmentedCard],
    pages: Sequence[Path],
    page_numbers: Sequence[int],
) -> list[ReverseSlot]:
    """One slot per survey front, in scan order.

    Everything passed in is one scan's: ``cards`` is the segmenter's output,
    ``pages`` the page images it was given (``page_index`` indexes them) and
    ``page_numbers`` their 1-based PDF pages, parallel to ``pages``.
    """
    dwelling_of: dict[SegmentedCard, Dwelling] = {}
    placed: dict[SegmentedCard, SegmentedCard] = {}
    for dwelling in dwellings:
        for card in dwelling.cards:
            dwelling_of[card] = dwelling
        for this, after in zip(dwelling.cards, dwelling.cards[1:]):
            if this.card_type is CardType.FRONT and after.card_type is CardType.REVERSE:
                placed[this] = after

    in_order = sorted(cards, key=lambda card: card.page_index)
    following = dict(zip(in_order, [*in_order[1:], None]))

    def page_of(index: int) -> int:
        return page_numbers[index]

    slots = []
    for front in (c for c in in_order if c.card_type is CardType.FRONT):
        if front in placed:
            reverse = placed[front]
            slots.append(
                ReverseSlot(front, reverse.image_path, page_of(reverse.page_index))
            )
            continue

        nxt = following[front]
        end = nxt.page_index if nxt is not None else len(pages)
        dropped = end - front.page_index - 1
        if dropped == 1:
            index = front.page_index + 1
            slots.append(
                ReverseSlot(front, pages[index], page_of(index), from_blank_page=True)
            )
            continue

        flags = {
            NoteFlag.NO_REVERSE_FOUND if dropped == 0 else NoteFlag.REVERSE_AMBIGUOUS
        }
        if (
            nxt is not None
            and dropped == 0
            and nxt.card_type is CardType.FRONT
            and nxt in dwelling_of
            and dwelling_of[nxt].dwelling_no is None
        ):
            flags.add(NoteFlag.POSSIBLE_BLEED_THROUGH)
        slots.append(ReverseSlot(front, None, None, flags=frozenset(flags)))

    # The suspect front gets the flag too: it may be the bleed-through itself.
    suspects = {
        following[s.front] for s in slots if NoteFlag.POSSIBLE_BLEED_THROUGH in s.flags
    }
    return [
        ReverseSlot(
            s.front,
            s.image,
            s.page,
            s.from_blank_page,
            s.flags | {NoteFlag.POSSIBLE_BLEED_THROUGH},
        )
        if s.front in suspects
        else s
        for s in slots
    ]


# --- 2. reading a back -------------------------------------------------------


def build_note_text(result: ExtractionResult | None) -> dict[str, Any]:
    """The note as a field object.

    A key the extractor never returned -- a failed call included -- is
    ``omitted``: an incomplete reading must not pass for a blank card (D011).
    A returned empty is ``no_data``, the explicit empty.
    """
    if result is None or REVERSE_NOTES_LABEL not in result.fields:
        return build_omitted_field(source=SOURCE)
    spec = REVERSE_NOTES_SCHEMA_BY_NAME[REVERSE_NOTES_LABEL]
    return build_field(
        spec, result.fields[REVERSE_NOTES_LABEL], source=SOURCE, struck=None
    )


def read_notes(
    slots: Iterable[ReverseSlot],
    read: Callable[[ReverseSlot], ExtractionResult | None],
) -> list[Note]:
    """Each slot's page through ``read``, one note per slot.

    ``read`` returns None when it has no reading for the page (the call
    failed, or the run is stopping); the note is then ``omitted``. A slot with
    no page is still a note: an ``omitted`` one carrying the flag that says
    why, so the gap shows in the record instead of vanishing. It has no
    ``source``, since there is no card for it to resolve to.
    """
    notes = []
    for slot in slots:
        flags = set(slot.flags)
        if slot.image is None:
            notes.append(Note(slot, build_omitted_field(), flags))
            continue
        text = build_note_text(read(slot))
        if slot.from_blank_page and text["status"] == "ok":
            flags.add(NoteFlag.NOTE_ON_BLANK_PAGE)
        notes.append(Note(slot, text, flags))
    return notes


# --- 3. onto the records -----------------------------------------------------


def attach_notes(
    records: Iterable[dict[str, Any]], notes: Iterable[Note], locate: Locate
) -> list[Note]:
    """Adds ``dwelling.notes`` and the backs' card entries to ``records``, in
    place. Returns the notes with no record to go on.

    A note finds its record through its front's card entry, which
    ``build_dwelling_records`` writes for every front it read, so ``locate``
    must be the one the records were built with (D026). A dwelling that
    yielded no record (no coding card, no single identity) cannot hold a note,
    and no identity is invented for it.
    """
    by_front: dict[tuple[str, int], dict[str, Any]] = {}
    for record in records:
        for card in record["dwelling"].get("cards", []):
            if card["role"] == FRONT:
                by_front[card["image"], card["page"]] = record

    unattached = []
    for note in notes:
        front = locate(note.slot.front)
        record = by_front.get(front)
        if record is None:
            unattached.append(note)
            continue
        dwelling = record["dwelling"]
        entry: dict[str, Any] = {
            "text": note.text,
            "page": note.slot.page,
            "front_page": front[1],
            "household_id": None,
            "flags": sorted(note.flags),
        }
        assign_household(entry, dwelling["households"])
        dwelling.setdefault("notes", []).append(entry)
        if note.slot.page is not None:
            add_back_card(dwelling, front, note.slot.page)
    return unattached


def assign_household(entry: dict[str, Any], households: list[dict[str, Any]]) -> None:
    """The note entry's ``household_id``, and its ``household_ambiguous`` flag,
    from the dwelling's households as they are now. The merge calls it again,
    since a correction or a joining household changes them after attaching."""
    flags = set(entry.get("flags", [])) - {NoteFlag.HOUSEHOLD_AMBIGUOUS}
    if len(households) == 1:
        entry["household_id"] = households[0]["record_id"]
    else:
        entry["household_id"] = None
        flags.add(NoteFlag.HOUSEHOLD_AMBIGUOUS)
    if flags:
        entry["flags"] = sorted(flags)
    else:
        entry.pop("flags", None)


def add_back_card(dwelling: dict[str, Any], front: tuple[str, int], page: int) -> None:
    """The back's card entry, straight after its front's, so the record lists
    each sheet's two sides together. The back is in the front's scan."""
    cards = dwelling.setdefault("cards", [])
    image, _ = front
    back = {"role": SOURCE, "image": image, "page": page, "confidence": None}
    at = next(
        (
            i + 1
            for i, c in enumerate(cards)
            if c["role"] == FRONT and (c["image"], c["page"]) == front
        ),
        len(cards),
    )
    cards.insert(at, back)

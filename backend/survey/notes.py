"""Reverse-side interview notes, read verbatim and attached to their dwelling
(FR-05, IT-89).

The back of a survey card carries the interviewer's free prose. Nothing on it
says which dwelling it belongs to: the only link is that it was scanned
straight after its own front. So a note is placed by its front, never by its
content, in three steps:

1. :func:`find_reverses` decides, for every survey front, which page is its
   back. ``associate()`` (FR-04) is the source of truth for a reverse it
   already placed; the page list is consulted only where a front has none.
2. :func:`read_notes` reads each of those pages with a reverse-notes
   extractor and turns the answer into one D007 field object.
3. :func:`attach_notes` adds the notes to the dwelling records built from the
   same dwellings.

**Notes belong to the dwelling.** The survey front is one per dwelling (D007),
and its back is the same sheet, so a note cannot be pinned to one household
from the card. ``household_id`` is filled only when the dwelling has exactly
one household and is left null, flagged, otherwise -- the same call
``build_dwelling_records`` makes for the person grid. No note is linked to an
individual: the back has no columns to link by.

**A blank back is a stated empty, not a missing one.** The segmenter drops a
page under its blank-ink cutoff, so the blank back of a front never becomes a
card. Exactly one dropped page between a front and the next card is that
front's back, and it is read anyway: an empty answer becomes ``no_data``,
which is FR-05's explicit empty. Anything the model does find there is kept,
because a short note can fall under the cutoff, but flagged
``note_on_blank_page`` so a note invented on a blank card is never passed off
as a clean reading.

**Verbatim**, as the prompt (``json_extraction.REVERSE_NOTES_PROMPT``) and the
fixtures' expected text both apply it:

- spelling, abbreviations, punctuation and word order are kept as written;
- struck words are left out and their replacements kept (D020 counts a
  correction to back-of-card text as part of it);
- an unreadable word is written ``[illegible]``;
- line breaks are kept as returned.

``clean_text`` (via ``build_field``) only strips the ends and treats a
dash-only answer as blank, which is right for notes too.

Deliberately not done here:

- Printed reverse forms (R1 in the IT-73 spike) are not told apart from
  handwritten notes; whether they are in scope is open.
- No confidence (FR-10) and no ``illegible`` status (FR-09).
- Pipeline wiring. Every function takes plain data, so ``pipeline.py`` only
  has to call them once it builds dwelling records.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from survey.association.dwelling import Dwelling
from survey.extraction.base import ExtractionResult, Extractor
from survey.extraction.card_fields import (
    REVERSE_NOTES_LABEL,
    REVERSE_NOTES_SCHEMA_BY_NAME,
)
from survey.extraction.record import build_field, build_omitted_field
from survey.segmentation.segmenter import CardType, SegmentedCard

log = logging.getLogger(__name__)

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


def read_notes(slots: Iterable[ReverseSlot], extractor: Extractor) -> list[Note]:
    """Each slot's page through ``extractor``, one note per slot.

    A slot with no page is still a note: an ``omitted`` one carrying the flag
    that says why, so the gap shows in the record instead of vanishing. It has
    no ``source``, since there is no card for it to resolve to.
    """
    notes = []
    for slot in slots:
        flags = set(slot.flags)
        if slot.image is None:
            notes.append(Note(slot, build_omitted_field(), flags))
            continue
        try:
            result = extractor.extract(slot.image)
        except Exception:  # one bad back must not cost the batch its notes
            log.exception(
                "%s p%s: note extraction failed", slot.front.source_scan.name, slot.page
            )
            result = None
        text = build_note_text(result)
        if slot.from_blank_page and text["status"] == "ok":
            flags.add(NoteFlag.NOTE_ON_BLANK_PAGE)
        notes.append(Note(slot, text, flags))
    return notes


# --- 3. onto the records -----------------------------------------------------


def attach_notes(
    records: Iterable[dict[str, Any]], notes: Iterable[Note]
) -> list[Note]:
    """Adds ``dwelling.notes`` and the backs' card entries to ``records``, in
    place. Returns the notes with no record to go on.

    A note finds its record through its front's card entry, which
    ``build_dwelling_records`` writes for every front. A dwelling that yielded
    no record (no coding card, no single identity) cannot hold a note, and no
    identity is invented for it.
    """
    by_front: dict[str, dict[str, Any]] = {}
    for record in records:
        for card in record["dwelling"].get("cards", []):
            if card["role"] == FRONT:
                by_front[card["image"]] = record

    unattached = []
    for note in notes:
        record = by_front.get(str(note.slot.front.image_path))
        if record is None:
            unattached.append(note)
            continue
        dwelling = record["dwelling"]
        households = dwelling["households"]
        flags = set(note.flags)
        if len(households) == 1:
            household_id = households[0]["record_id"]
        else:
            household_id = None
            flags.add(NoteFlag.HOUSEHOLD_AMBIGUOUS)
        entry: dict[str, Any] = {
            "text": note.text,
            "page": note.slot.page,
            "household_id": household_id,
        }
        if flags:
            entry["flags"] = sorted(flags)
        dwelling.setdefault("notes", []).append(entry)
        if note.slot.image is not None:
            _add_card(dwelling, note.slot)
    return unattached


def _add_card(dwelling: dict[str, Any], slot: ReverseSlot) -> None:
    """The back's card entry, straight after its front's, so the record lists
    each sheet's two sides together."""
    cards = dwelling.setdefault("cards", [])
    back = {
        "role": SOURCE,
        "image": str(slot.image),
        "page": slot.page,
        "confidence": None,
    }
    front = str(slot.front.image_path)
    at = next(
        (
            i + 1
            for i, c in enumerate(cards)
            if c["role"] == FRONT and c["image"] == front
        ),
        len(cards),
    )
    cards.insert(at, back)

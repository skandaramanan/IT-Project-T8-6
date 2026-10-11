"""FR-05: a survey back's notes, read verbatim and attached to its dwelling.

Covers IT-89's ACs without a model: AC1's verbatim capture against a stub
extractor (the live check is ``test_reverse_note_extraction.py``), AC2's link
through real segmentation and association on the fixture cards, AC3's explicit
empty for a blank back, and AC4's provenance.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

import survey.extraction.gemini as gemini_extractor
from survey.association.dwelling import associate
from survey.association.notes import (
    NoteFlag,
    ReverseSlot,
    attach_notes,
    build_note_text,
    find_reverses,
    read_notes,
)
from survey.association.records import build_dwelling_records
from survey.extraction.base import ExtractionResult
from survey.extraction.card_fields import REVERSE_NOTES_SCHEMA_BY_NAME
from survey.extraction.gemini import GeminiExtractor
from survey.extraction.json_extraction import REVERSE_NOTES_PROMPT, parse_json_fields
from survey.segmentation.segmenter import CardType, SegmentedCard, segment_scan

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = json.loads(
    (FIXTURES.parent.parent / "schema/record-envelope.schema.json").read_text()
)
F, R, C = CardType.FRONT, CardType.REVERSE, CardType.NUMERIC_CODING
NOTES = "Interview Notes"


class FakeReader:
    """Answers by page file name; None is a page with no reading (a failed
    call), as the pipeline's reader gives it."""

    def __init__(self, answers: dict[str, str | None] | None = None) -> None:
        self.answers = answers or {}
        self.seen: list[str] = []

    def __call__(self, slot: ReverseSlot) -> ExtractionResult | None:
        self.seen.append(slot.image.name)
        answer = self.answers.get(slot.image.name, "")
        return None if answer is None else ExtractionResult(fields={NOTES: answer})


def _locate(card: SegmentedCard) -> tuple[str, int]:
    """As the pipeline names a card (D026): its scan, and its page there."""
    return card.source_scan.name, card.page_index + 1


def _front(number: str) -> ExtractionResult:
    return ExtractionResult(fields={"Dwelling Number (top-left corner)": number})


def _coding(number: str) -> ExtractionResult:
    """``"5"`` is household 1 of dwelling 5; ``"5/2"`` household 2."""
    dwelling, _, household = number.partition("/")
    return ExtractionResult(
        fields={
            "Municipality": "27",
            "Number of Dwelling": dwelling,
            "Number of Household": household or "1",
        },
        struck={},
    )


def _scan(*pages):
    """Pages in scan order: ``(card type, dwelling number)``, or None for a
    page the segmenter dropped as blank."""
    paths = [Path(f"p{i}.jpg") for i in range(len(pages))]
    cards = [
        (SegmentedCard(page[0], paths[i], Path("b.pdf"), i), page[1])
        for i, page in enumerate(pages)
        if page is not None
    ]
    return cards, paths


def _slots(*pages, page_numbers=None):
    cards, paths = _scan(*pages)
    dwellings, _ = associate(cards)
    numbers = page_numbers or list(range(1, len(paths) + 1))
    return find_reverses(dwellings, [c for c, _ in cards], paths, numbers)


def _run(*pages, answers=None, page_numbers=None):
    """Records with notes attached, and the notes with nowhere to go."""
    cards, paths = _scan(*pages)
    readers = {F: _front, C: _coding}
    extracted = [
        (card, readers[card.card_type](number) if card.card_type in readers else None)
        for card, number in cards
    ]
    records, dwellings, _ = build_dwelling_records(
        extracted, region="williamstown", locate=_locate
    )
    numbers = page_numbers or list(range(1, len(paths) + 1))
    slots = find_reverses(dwellings, [c for c, _ in cards], paths, numbers)
    unattached = attach_notes(records, read_notes(slots, FakeReader(answers)), _locate)
    return records, unattached


# --- which page is each front's back ----------------------------------------


def test_a_reverse_association_placed_is_the_fronts_back():
    (slot,) = _slots((F, "6"), (R, None), (C, "6"), None)
    assert (slot.image, slot.page, slot.from_blank_page, slot.flags) == (
        Path("p1.jpg"),
        2,
        False,
        frozenset(),
    )


@pytest.mark.parametrize(
    "pages",
    [
        ((F, "6"), None, (C, "6"), None),  # blank back, then the coding card
        ((F, "6"), None),  # blank back is the last page of the scan
    ],
)
def test_one_dropped_page_behind_a_front_is_its_blank_back(pages):
    (slot,) = _slots(*pages)
    assert (slot.image, slot.page, slot.from_blank_page) == (Path("p1.jpg"), 2, True)
    assert not slot.flags


def test_no_page_between_a_front_and_the_next_card_is_no_back_found():
    (slot,) = _slots((F, "6"), (C, "6"))
    assert (slot.image, slot.page) == (None, None)
    assert slot.flags == {NoteFlag.NO_REVERSE_FOUND}


def test_two_dropped_pages_are_too_many_to_call():
    (slot,) = _slots((F, "6"), None, None, (C, "6"))
    assert slot.image is None
    assert slot.flags == {NoteFlag.REVERSE_AMBIGUOUS}


def test_a_numberless_front_straight_after_a_backless_one_is_flagged_on_both():
    """A blank back showing its front through reads as a front with no
    dwelling number (IT-73 spike)."""
    real, suspect = _slots((F, "6"), (F, None), (C, "6"))
    assert real.flags == {NoteFlag.NO_REVERSE_FOUND, NoteFlag.POSSIBLE_BLEED_THROUGH}
    assert NoteFlag.POSSIBLE_BLEED_THROUGH in suspect.flags


def test_each_overflow_front_keeps_its_own_back():
    slots = _slots((F, "7"), (R, None), (F, "7"), (R, None), (C, "7"))
    assert [(s.image, s.page) for s in slots] == [
        (Path("p1.jpg"), 2),
        (Path("p3.jpg"), 4),
    ]


def test_a_back_with_no_front_before_it_belongs_to_nothing():
    slots = _slots((R, None), (F, "6"), (R, None), (C, "6"))
    assert [s.image for s in slots] == [Path("p2.jpg")]


def test_page_is_the_pdf_page_not_the_readable_page_index():
    """AC4: PDF page 3 had no readable image, so readable index 3 is page 5."""
    _, slot = _slots((F, "6"), (C, "6"), (F, "7"), (R, None), page_numbers=[1, 2, 4, 5])
    assert slot.page == 5


# --- reading a back ---------------------------------------------------------


@pytest.mark.parametrize(
    "fields, status, value",
    [
        (
            {NOTES: "Very big house.\nVery good garden - fish pond"},
            "ok",
            "Very big house.\nVery good garden - fish pond",
        ),
        ({NOTES: "  Lives with in-laws.  "}, "ok", "Lives with in-laws."),
        ({NOTES: ""}, "no_data", None),
        ({NOTES: "-"}, "no_data", None),
        ({}, "omitted", None),
    ],
)
def test_the_note_is_kept_as_written_and_a_missing_answer_is_omitted(
    fields, status, value
):
    text = build_note_text(ExtractionResult(fields=fields))
    assert (text["status"], text["value"]) == (status, value)
    assert text["source"] == "survey-back"
    assert text["confidence"] is None and "negated" not in text
    jsonschema.validate(text, {"$defs": SCHEMA["$defs"], "$ref": "#/$defs/field"})


def test_a_failed_read_is_omitted_not_blank():
    """AC3's explicit empty must only ever mean a blank back was seen."""
    slot = ReverseSlot(
        SegmentedCard(F, Path("p0.jpg"), Path("b.pdf"), 0), Path("p1.jpg"), 2
    )
    (note,) = read_notes([slot], FakeReader({"p1.jpg": None}))
    assert note.text["status"] == "omitted"


def test_text_on_a_dropped_page_is_kept_and_flagged():
    """A short note can fall under the blank-ink cutoff; so can a note the
    model invented. Either way a reviewer has to see it."""
    front = SegmentedCard(F, Path("p0.jpg"), Path("b.pdf"), 0)
    slot = ReverseSlot(front, Path("p1.jpg"), 2, from_blank_page=True)
    (sparse,) = read_notes([slot], FakeReader({"p1.jpg": "Nil"}))
    (blank,) = read_notes([slot], FakeReader({"p1.jpg": ""}))
    assert (sparse.text["value"], sparse.flags) == (
        "Nil",
        {NoteFlag.NOTE_ON_BLANK_PAGE},
    )
    assert (blank.text["status"], blank.flags) == ("no_data", set())


def test_a_front_without_a_back_is_not_sent_to_the_model():
    front = SegmentedCard(F, Path("p0.jpg"), Path("b.pdf"), 0)
    slot = ReverseSlot(front, None, None, flags=frozenset({NoteFlag.NO_REVERSE_FOUND}))
    reader = FakeReader()
    (note,) = read_notes([slot], reader)
    assert reader.seen == []
    assert note.text["status"] == "omitted" and "source" not in note.text
    assert note.flags == {NoteFlag.NO_REVERSE_FOUND}


# --- onto the records -------------------------------------------------------


def test_a_one_household_dwelling_gets_its_note_and_the_backs_card():
    """AC1, AC2, AC4."""
    (record,), unattached = _run(
        (F, "6"), (R, None), (C, "6"), answers={"p1.jpg": "Very big house."}
    )
    dwelling = record["dwelling"]
    assert unattached == []
    assert dwelling["notes"] == [
        {
            "text": build_note_text(
                ExtractionResult(fields={NOTES: "Very big house."})
            ),
            "page": 2,
            "household_id": "27-0006-01",
        }
    ]
    assert [(c["role"], c["image"], c["page"]) for c in dwelling["cards"]] == [
        ("survey-front", "b.pdf", 1),
        ("survey-back", "b.pdf", 2),
    ]
    jsonschema.validate(record, SCHEMA)


def test_a_blank_back_is_an_explicit_empty_note():
    """AC3: present, empty, and no error."""
    (record,), _ = _run((F, "6"), None, (C, "6"), None)
    (note,) = record["dwelling"]["notes"]
    assert (note["text"]["status"], note["text"]["value"], note["page"]) == (
        "no_data",
        None,
        2,
    )
    assert "flags" not in note
    jsonschema.validate(record, SCHEMA)


def test_a_missing_back_shows_in_the_record_with_why():
    (record,), _ = _run((F, "6"), (C, "6"))
    (note,) = record["dwelling"]["notes"]
    assert (note["text"]["status"], note["page"], note["flags"]) == (
        "omitted",
        None,
        ["no_reverse_found"],
    )
    assert [c["role"] for c in record["dwelling"]["cards"]] == ["survey-front"]
    jsonschema.validate(record, SCHEMA)


def test_two_households_leave_the_note_on_the_dwelling_unassigned():
    (record,), _ = _run(
        (F, "5"), (R, None), (C, "5"), (C, "5/2"), answers={"p1.jpg": "Two families."}
    )
    (note,) = record["dwelling"]["notes"]
    assert (note["household_id"], note["flags"]) == (None, ["household_ambiguous"])
    jsonschema.validate(record, SCHEMA)


def test_overflow_fronts_give_two_notes_in_order_never_one_joined():
    (record,), _ = _run(
        (F, "7"),
        (R, None),
        (F, "7"),
        (R, None),
        (C, "7"),
        answers={"p1.jpg": "First card.", "p3.jpg": "Continued."},
    )
    dwelling = record["dwelling"]
    assert [n["text"]["value"] for n in dwelling["notes"]] == [
        "First card.",
        "Continued.",
    ]
    assert [n["page"] for n in dwelling["notes"]] == [2, 4]
    assert [(c["role"], c["page"]) for c in dwelling["cards"]] == [
        ("survey-front", 1),
        ("survey-back", 2),
        ("survey-front", 3),
        ("survey-back", 4),
    ]
    jsonschema.validate(record, SCHEMA)


def test_a_dwelling_with_no_record_cannot_hold_its_note():
    records, unattached = _run((F, "9"), (R, None), answers={"p1.jpg": "Nobody home."})
    assert records == []
    assert [n.text["value"] for n in unattached] == ["Nobody home."]


def test_fixture_backs_reach_their_dwellings_through_segmentation_and_association():
    """AC2 on real scans: the segmenter finds each r0N back, association puts
    it behind its front, and the note lands on that dwelling's record."""
    numbers = {"r01": "6", "r02": "7", "r03": "12", "r04": "14", "r05": "23"}
    roles = ("survey-front", "survey-back", "coding-front", "coding-back")
    scans, extracted = [], []
    for record, number in numbers.items():
        pages = [FIXTURES / f"{record}-{role}.jpg" for role in roles]
        cards = [
            c
            for c in segment_scan(pages, source_scan=Path(f"{record}.pdf")).values()
            if c
        ]
        scans.append((cards, pages))
        readers = {F: _front, C: _coding}
        extracted += [
            (
                c,
                readers[c.card_type](number.zfill(2))
                if c.card_type in readers
                else None,
            )
            for c in cards
        ]
    records, dwellings, unplaced = build_dwelling_records(
        extracted, region="williamstown", locate=_locate
    )
    assert unplaced == []

    reader = FakeReader({f"{r}-survey-back.jpg": f"notes for {r}" for r in numbers})
    for cards, pages in scans:
        slots = find_reverses(dwellings, cards, pages, [1, 2, 3, 4])
        assert attach_notes(records, read_notes(slots, reader), _locate) == []

    for record, (name, number) in zip(records, numbers.items()):
        (note,) = record["dwelling"]["notes"]
        assert note["text"]["value"] == f"notes for {name}"
        assert note["household_id"] == f"27-{number.zfill(4)}-01"
        assert note["page"] == 2
        assert ("survey-back", f"{name}.pdf", 2) in [
            (c["role"], c["image"], c["page"]) for c in record["dwelling"]["cards"]
        ]
        jsonschema.validate(record, SCHEMA)


# --- the extractor ----------------------------------------------------------


def test_the_reverse_notes_extractor_asks_for_the_notes_alone(tmp_path, monkeypatch):
    from google import genai

    sent = []

    def generate_content(**kwargs):
        sent.append(kwargs["contents"][1])
        return SimpleNamespace(text='{"Interview Notes": null}', usage_metadata=None)

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(genai, "Client", lambda *a, **k: client)
    monkeypatch.setattr(gemini_extractor.time, "sleep", lambda _seconds: None)
    image = tmp_path / "back.jpg"
    image.write_bytes(b"not decoded by the stub")

    extractor = GeminiExtractor(reverse_notes=True)
    result = extractor.extract(image)

    assert extractor.name.endswith("-reverse-notes")
    assert sent == [REVERSE_NOTES_PROMPT]  # one call: a blank answer is not retried
    assert result.fields == {NOTES: ""}
    assert build_note_text(result)["status"] == "no_data"


def test_a_blank_answer_is_a_usable_answer():
    """The parser rejects a response sharing no key with the schema; a blank
    back's ``null`` still shares the one key there is."""
    assert parse_json_fields(
        '{"Interview Notes": null}', REVERSE_NOTES_SCHEMA_BY_NAME
    ) == {NOTES: ""}
    assert parse_json_fields('{"Notes": "x"}', REVERSE_NOTES_SCHEMA_BY_NAME) is None


def test_the_prompt_shows_the_blank_answer_the_parser_accepts():
    """A blank back came back as {"text": null} until the prompt spelled out
    the key; the shape it shows must be one the parser takes."""
    blank = re.search(r'\{"[^"]+": null\}', REVERSE_NOTES_PROMPT).group(0)
    assert parse_json_fields(blank, REVERSE_NOTES_SCHEMA_BY_NAME) == {NOTES: ""}


def test_one_extractor_reads_one_side():
    with pytest.raises(ValueError):
        GeminiExtractor(survey_front=True, reverse_notes=True)

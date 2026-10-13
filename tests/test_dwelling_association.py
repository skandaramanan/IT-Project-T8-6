"""FR-04: segmented cards grouped into dwellings, and into D007 records."""

import json
from pathlib import Path

import jsonschema

from survey.association.dwelling import ReviewFlag as Flag
from survey.association.dwelling import associate
from survey.association.records import build_dwelling_records, extract
from survey.extraction.base import ExtractionResult
from survey.extraction.card_fields import survey_front_label
from survey.segmentation.segmenter import CardType, SegmentedCard, segment_scan

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = json.loads(
    (FIXTURES.parent.parent / "schema/record-envelope.schema.json").read_text()
)
F, R, C = CardType.FRONT, CardType.REVERSE, CardType.NUMERIC_CODING


def _front(number: str, *people: str) -> ExtractionResult:
    """Stand-in survey-front extraction, keyed as the real extractor keys it."""
    fields = {
        "Dwelling Number (top-left corner)": number,
        "Address": f"{number} Hall St.",
        "Type of Dwelling": "D",
    }
    for column, relationship in enumerate(people, 1):
        fields[survey_front_label("Relationship", column)] = relationship
    return ExtractionResult(fields=fields)


def _coding(
    number: str, household: str = "1", municipality: str = "27"
) -> ExtractionResult:
    fields = {"Municipality": municipality, "Number of Dwelling": number}
    if household:
        fields["Number of Household"] = household
    return ExtractionResult(fields=fields, struck={})


def _records(*cards: tuple[CardType, ExtractionResult | None]):
    extracted = [
        (SegmentedCard(kind, Path(f"{i}.jpg"), Path("b.pdf"), i), result)
        for i, (kind, result) in enumerate(cards)
    ]
    return build_dwelling_records(extracted, region="williamstown", batch="b")


def _people(household: dict) -> list:
    return [p["relationship"]["value"] for p in household.get("persons", [])]


def _run(*cards: tuple[CardType, str | None]):
    """Pages and flags per dwelling, then unplaced pages."""
    batch = [
        (SegmentedCard(kind, Path(f"{i}.jpg"), Path("b.pdf"), i), number)
        for i, (kind, number) in enumerate(cards)
    ]
    dwellings, unplaced = associate(batch)
    return (
        [([c.page_index for c in d.cards], d.flags) for d in dwellings],
        [c.page_index for c in unplaced],
    )


def test_cards_group_by_dwelling_with_overflow_fronts_and_households():
    assert _run(
        (F, "6"),
        (R, None),
        (C, "06"),
        (F, "7"),
        (R, None),
        (F, "7"),
        (C, "7"),
        (C, "7"),
    ) == ([([0, 1, 2], set()), ([3, 4, 5, 6, 7], set())], [])


def test_out_of_order_coding_card_joins_its_dwelling_flagged():
    assert _run((F, "20"), (R, None), (F, "90"), (R, None), (C, "20"), (C, "90")) == (
        [([0, 1, 4], {Flag.OUT_OF_ORDER}), ([2, 3, 5], set())],
        [],
    )


def test_a_far_card_does_not_join_a_dwelling_that_has_its_card():
    """Page 12 reads 21, which is dwelling 30's card misread: joining 21 would
    give two 21s and drop both. Dwelling 9 has no card, so its far one joins."""
    pages = [(F, "9"), (F, "21"), (C, "21")]
    for n in ("22", "23", "24", "25"):
        pages += [(F, n), (C, n)]
    pages += [(F, "30"), (C, "21"), (C, "9")]
    dwellings, unplaced = _run(*pages)
    assert dwellings[0] == ([0, 13], {Flag.OUT_OF_ORDER})
    assert dwellings[1] == ([1, 2], set())
    assert dwellings[-1] == ([11], {Flag.NO_CODING_CARD})
    assert unplaced == [12]


def test_unchecked_cards_are_flagged_or_unplaced_not_guessed():
    dwellings, unplaced = _run(
        (R, None),  # no front before it
        (F, "5"),
        (C, "9"),  # adjacent, but another dwelling
        (F, None),
        (R, None),
        (F, "5"),
        (C, ""),  # unreadable
        (F, "8"),
        (C, "5"),  # two dwelling 5s to choose from
    )
    assert dwellings == [
        ([1], {Flag.DUPLICATE_DWELLING_NO, Flag.NO_CODING_CARD}),
        ([3, 4], {Flag.MISSING_DWELLING_NO, Flag.NO_CODING_CARD}),
        ([5], {Flag.DUPLICATE_DWELLING_NO, Flag.NO_CODING_CARD}),
        ([7], {Flag.NO_CODING_CARD}),
    ]
    assert sorted(unplaced) == [0, 2, 6, 8]


def test_a_front_with_no_number_takes_its_coding_cards_number():
    """A run that does not read fronts still groups by scan order."""
    missing, duplicate = Flag.MISSING_DWELLING_NO, Flag.DUPLICATE_DWELLING_NO
    assert _run(
        (F, None),
        (R, None),
        (C, "6"),
        (C, "6"),  # second household
        (F, None),
        (C, "7"),
        (C, "8"),  # the front is 7 now
    ) == ([([0, 1, 2, 3], {missing}), ([4, 5], {missing})], [6])
    assert _run((F, None), (C, "6"), (F, None), (C, "6")) == (
        [([0, 1], {missing, duplicate}), ([2, 3], {missing, duplicate})],
        [],
    )


def test_fixture_batch_from_extraction_to_records():
    numbers = {"r01": "6", "r02": "7", "r03": "12", "r04": "14", "r05": "23"}
    roles = ("survey-front", "survey-back", "coding-front", "coding-back")
    extracted = []
    for record, number in numbers.items():
        scan = segment_scan(
            [FIXTURES / f"{record}-{r}.jpg" for r in roles], source_scan=Path("s.pdf")
        )
        front, reverse, coding = scan[F], scan[R], scan[C]
        assert front and reverse and coding
        extracted += [
            (front, _front(number, "Head", "Wife")),
            (reverse, None),
            (coding, _coding(number.zfill(2))),
        ]

    records, dwellings, unplaced = build_dwelling_records(
        extracted, region="williamstown", batch="s"
    )

    assert unplaced == [] and not any(d.flags for d in dwellings)
    assert [r["dwelling"]["households"][0]["record_id"] for r in records] == [
        f"27-{n.zfill(4)}-01" for n in numbers.values()
    ]
    for record, number in zip(records, numbers.values()):
        jsonschema.validate(record, SCHEMA)
        dwelling = record["dwelling"]
        assert dwelling["address"]["value"] == f"{number} Hall St."
        assert dwelling["handwritten"]["type_of_dwelling"]["source"] == "survey-front"
        assert _people(dwelling["households"][0]) == ["Head", "Wife"]
        assert [c["role"] for c in dwelling["cards"]] == ["survey-front"]
    assert (
        build_dwelling_records(extracted, region="williamstown", batch="s")[0]
        == records
    )


def test_overflow_fronts_add_their_people_to_the_household():
    records, _, _ = _records(
        (F, _front("7", "Head", "Wife")), (F, _front("7", "Son")), (C, _coding("7"))
    )
    assert _people(records[0]["dwelling"]["households"][0]) == ["Head", "Wife", "Son"]


def test_a_front_that_failed_extraction_starts_its_own_flagged_dwelling():
    records, dwellings, _ = _records(
        (F, _front("7", "Head")), (F, None), (C, _coding("7"))
    )
    assert _people(records[0]["dwelling"]["households"][0]) == ["Head"]
    assert dwellings[1].flags == {
        Flag.MISSING_DWELLING_NO,
        Flag.NO_CODING_CARD,
        Flag.UNREAD_FRONT,
    }


def test_a_later_front_fills_blanks_and_flags_disagreement():
    overflow = ExtractionResult(
        fields={
            "Dwelling Number (top-left corner)": "7",
            "Address": "",
            "Type of Dwelling": "S",
            "Structural Material": "Brick",
        }
    )
    records, dwellings, _ = _records(
        (F, _front("7", "Head")), (F, overflow), (C, _coding("7"))
    )
    dwelling = records[0]["dwelling"]
    assert dwelling["address"]["value"] == "7 Hall St."
    assert dwelling["handwritten"]["type_of_dwelling"]["value"] == "D"
    assert dwelling["handwritten"]["structural_material"]["value"] == "Brick"
    assert dwellings[0].flags == {Flag.FRONTS_DISAGREE}


def test_coding_cards_from_two_municipalities_are_written_flagged():
    records, _, _ = _records(
        (F, _front("5")), (C, _coding("5")), (C, _coding("5", "2", municipality="28"))
    )
    dwelling = records[0]["dwelling"]
    assert [h["record_id"] for h in dwelling["households"]] == [
        "27-0005-01",
        "28-0005-02",
    ]
    assert dwelling["flags"] == ["municipality_mismatch"]
    jsonschema.validate(records[0], SCHEMA)


def test_a_repeated_record_id_is_written_null_in_both_dwellings():
    records, _, _ = _records(
        (F, _front("5")),
        (C, _coding("5")),
        (F, _front("8")),
        (C, _coding("8")),
        (F, _front("5")),
        (C, _coding("5")),
    )
    assert [r["dwelling"]["households"][0]["record_id"] for r in records] == [
        None,
        "27-0008-01",
        None,
    ]
    assert [r["dwelling"].get("flags") for r in records] == [
        ["duplicate_dwelling_no", "duplicate_record_id"],
        None,
        ["duplicate_dwelling_no", "duplicate_record_id"],
    ]
    for record in records:
        jsonschema.validate(record, SCHEMA)


def test_an_unplaced_card_is_its_own_dwelling_and_a_blank_one_is_left_out():
    blank = ExtractionResult(fields={"Municipality": "", "Number of Dwelling": "null"})
    records, _, unplaced = _records(
        (F, _front("5")), (C, _coding("5")), (C, _coding("9")), (C, blank)
    )
    assert [r["dwelling"]["households"][0]["record_id"] for r in records] == [
        "27-0005-01",
        "27-0009-01",
    ]
    lone = records[1]["dwelling"]
    assert (lone["flags"], "cards" in lone) == (["unplaced"], False)
    assert [c.page_index for c in unplaced] == [3]
    jsonschema.validate(records[1], SCHEMA)


def test_a_card_no_number_fits_pairs_with_the_front_at_the_usual_offset():
    """Coding cards here follow their front; page 3's number is misread, so it
    pairs with page 2's front by position. Page 5 sits after a front that
    already has its card, so it stays unplaced."""
    records, _, _ = _records(
        (F, _front("5")),
        (C, _coding("5")),
        (F, _front("6")),
        (C, _coding("8")),
        (F, _front("7")),
        (C, _coding("7")),
        (C, _coding("9")),
    )
    paired, lone = records[1]["dwelling"], records[3]["dwelling"]
    assert paired["households"][0]["record_id"] == "27-0008-01"
    assert paired["handwritten"]["dwelling_no"]["value"] == "6"
    assert paired["flags"] == ["paired_by_position"]
    assert lone["flags"] == ["unplaced"]
    for record in records:
        jsonschema.validate(record, SCHEMA)


def test_a_card_with_its_front_keeps_a_record_id_a_lone_card_also_claims():
    """Page 10 reads 5, far from dwelling 5, which has its card: the lone card
    is the likelier misread, so only it loses the record_id."""
    pages = []
    for n in ("5", "6", "7", "8", "9"):
        pages += [(F, _front(n)), (C, _coding(n))]
    records, _, _ = _records(*pages, (C, _coding("5")))
    first, lone = records[0]["dwelling"], records[-1]["dwelling"]
    assert first["households"][0]["record_id"] == "27-0005-01"
    assert "flags" not in first
    assert lone["households"][0]["record_id"] is None
    assert lone["flags"] == ["duplicate_record_id", "unplaced"]


def test_a_card_read_whole_keeps_a_record_id_a_reread_card_also_claims():
    """Page 5's identity was filled by a second reading and now matches page
    1's, read whole: the filled one is the likelier misread."""
    pages = [(F, "5"), (C, "5"), (F, "6"), (C, "6"), (F, "5"), (C, "5")]
    cards = [
        (
            SegmentedCard(kind, Path(f"{i}.jpg"), Path("b.pdf"), i),
            _front(n) if kind is F else _coding(n),
        )
        for i, (kind, n) in enumerate(pages)
    ]
    records, _, _ = build_dwelling_records(
        cards, region="williamstown", batch="b", reread={cards[5][0]}
    )
    whole, filled = records[0]["dwelling"], records[2]["dwelling"]
    assert whole["households"][0]["record_id"] == "27-0005-01"
    assert filled["households"][0]["record_id"] is None
    assert {"duplicate_record_id", "identity_reread"} <= set(filled["flags"])


def test_a_lettered_dwelling_is_not_the_numbered_one():
    records, _, _ = _records(
        (F, _front("487")),
        (C, _coding("487")),
        (F, _front("487a")),
        (C, _coding("487 A")),
    )
    assert [r["dwelling"]["households"][0]["record_id"] for r in records] == [
        "27-0487-01",
        "27-0487A-01",
    ]
    assert not any("flags" in r["dwelling"] for r in records)


def test_two_households_leave_people_unassigned_and_flagged():
    records, dwellings, _ = _records(
        (F, _front("5", "Head", "Boarder")), (C, _coding("5")), (C, _coding("5", "2"))
    )
    households = records[0]["dwelling"]["households"]
    assert [h["record_id"] for h in households] == ["27-0005-01", "27-0005-02"]
    assert not any(_people(h) for h in households)
    assert Flag.PERSONS_UNASSIGNED in dwellings[0].flags
    jsonschema.validate(records[0], SCHEMA)


def test_a_card_without_an_identity_is_written_null_and_a_front_alone_is_not():
    records, dwellings, _ = _records(
        (F, _front("9", "Head")), (R, None), (F, _front("4")), (C, _coding("4", ""))
    )
    [record] = records
    assert record["dwelling"]["households"][0]["record_id"] is None
    assert record["dwelling"]["flags"] == ["missing_record_id"]
    assert Flag.NO_CODING_CARD in dwellings[0].flags
    jsonschema.validate(record, SCHEMA)


def test_each_card_goes_to_the_extractor_for_its_type():
    class Fake:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def extract(self, image_path: Path) -> ExtractionResult:
            self.seen.append(image_path.name)
            return ExtractionResult()

    coding, front = Fake(), Fake()
    cards = [
        SegmentedCard(k, Path(f"{k}.jpg"), Path("b.pdf"), i)
        for i, k in enumerate((F, R, C))
    ]
    results = extract(cards, coding=coding, front=front)  # type: ignore[arg-type]
    assert (front.seen, coding.seen) == (["front.jpg"], ["numeric_coding.jpg"])
    assert results[1] == (cards[1], None)

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
    assert dwellings[1].flags == {Flag.MISSING_DWELLING_NO, Flag.NO_CODING_CARD}


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


def test_coding_cards_from_two_municipalities_yield_no_record():
    records, dwellings, _ = _records(
        (F, _front("5")), (C, _coding("5")), (C, _coding("5", "2", municipality="28"))
    )
    assert records == []
    assert Flag.MUNICIPALITY_MISMATCH in dwellings[0].flags


def test_a_repeated_record_id_yields_no_record_for_either_dwelling():
    records, dwellings, _ = _records(
        (F, _front("5")),
        (C, _coding("5")),
        (F, _front("8")),
        (C, _coding("8")),
        (F, _front("5")),
        (C, _coding("5")),
    )
    assert [r["dwelling"]["households"][0]["record_id"] for r in records] == [
        "27-0008-01"
    ]
    assert [Flag.DUPLICATE_RECORD_ID in d.flags for d in dwellings] == [
        True,
        False,
        True,
    ]


def test_two_households_leave_people_unassigned_and_flagged():
    records, dwellings, _ = _records(
        (F, _front("5", "Head", "Boarder")), (C, _coding("5")), (C, _coding("5", "2"))
    )
    households = records[0]["dwelling"]["households"]
    assert [h["record_id"] for h in households] == ["27-0005-01", "27-0005-02"]
    assert not any(_people(h) for h in households)
    assert Flag.PERSONS_UNASSIGNED in dwellings[0].flags
    jsonschema.validate(records[0], SCHEMA)


def test_dwellings_without_an_identity_yield_no_record():
    records, dwellings, _ = _records(
        (F, _front("9", "Head")), (R, None), (F, _front("4")), (C, _coding("4", ""))
    )
    assert records == []
    assert Flag.NO_CODING_CARD in dwellings[0].flags
    assert Flag.MISSING_RECORD_ID in dwellings[1].flags


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

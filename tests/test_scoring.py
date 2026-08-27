"""Scoring treats "no code here" as one answer, and still separates extractors.

The transcriber wrote a cell with no numeric code as "-" on some cards and ""
on others, so those have to compare equal -- but that makes empty output score
well on a mostly-empty card, which is why coded_fields exists. Both halves are
guarded here: drop either and a do-nothing extractor looks competitive.
"""

from ground_truth import BenchmarkCard
from scoring import score_structured

CARD = BenchmarkCard(
    page_id=1,
    source_page=1,
    image_path=None,
    fields={"a": "56", "b": "04", "c": "-", "d": "", "e": "--"},
)


def test_dash_and_blank_are_the_same_answer():
    score = score_structured(CARD, {"a": "56", "b": "04", "c": "", "d": "-", "e": None})
    assert score.correct_fields == 5
    assert (score.correct_coded_fields, score.coded_fields) == (2, 2)


def test_empty_extraction_scores_no_coded_fields():
    score = score_structured(CARD, {})
    assert score.correct_fields == 3  # the three no-code cells, for free
    assert score.correct_coded_fields == 0


def test_leading_zero_is_not_the_same_code():
    score = score_structured(CARD, {"a": "56", "b": "4"})
    assert score.correct_coded_fields == 1
    assert ("b", "04", "4") in score.mismatches


def test_coder_void_marks_count_as_no_code():
    """A "B" per code column is how the card itself says "no code here"."""
    card = BenchmarkCard(
        page_id=2,
        source_page=2,
        image_path=None,
        fields={"a": "-", "b": "-", "c": "-", "d": "8"},
    )
    score = score_structured(card, {"a": "B", "b": "BB", "c": "BBB", "d": "8"})
    assert score.correct_fields == 4
    assert (score.correct_coded_fields, score.coded_fields) == (1, 1)


def test_b_where_the_card_holds_a_digit_is_still_wrong():
    card = BenchmarkCard(
        page_id=3, source_page=3, image_path=None, fields={"poverty": "3"}
    )
    score = score_structured(card, {"poverty": "B"})
    assert score.correct_coded_fields == 0
    assert ("poverty", "3", "") in score.mismatches

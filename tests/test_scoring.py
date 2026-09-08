"""Scoring treats "no code here" as one answer, and still separates extractors.

The transcriber wrote a cell with no numeric code as "-" on some cards and ""
on others, so those have to compare equal -- but that makes empty output score
well on a mostly-empty card, which is why coded_fields exists. Both halves are
guarded here: drop either and a do-nothing extractor looks competitive.
"""

from ground_truth import BenchmarkCard
from scoring import score_structured

CARD = BenchmarkCard(
    page_id="1",
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
    assert ("b", "04", "4", "4") in score.mismatches


def test_coder_void_marks_count_as_no_code():
    """A "B" per code column is how the card itself says "no code here"."""
    card = BenchmarkCard(
        page_id="2",
        source_page=2,
        image_path=None,
        fields={"a": "-", "b": "-", "c": "-", "d": "8"},
    )
    score = score_structured(card, {"a": "B", "b": "BB", "c": "BBB", "d": "8"})
    assert score.correct_fields == 4
    assert (score.correct_coded_fields, score.coded_fields) == (1, 1)


def test_b_where_the_card_holds_a_digit_is_still_wrong():
    card = BenchmarkCard(
        page_id="3", source_page=3, image_path=None, fields={"poverty": "3"}
    )
    score = score_structured(card, {"poverty": "B"})
    assert score.correct_coded_fields == 0
    # The raw "B" is kept beside the normalised "": a mismatch row showing only
    # the empty value cannot tell a model that read a void mark from one that
    # read nothing at all, and that is the first thing a reviewer checks.
    assert ("poverty", "3", "B", "") in score.mismatches


def test_leader_dots_are_not_part_of_the_value():
    """The dotted line joining label to value gets read as digits: "1." for 1."""
    card = BenchmarkCard(
        page_id="4", source_page=4, image_path=None, fields={"a": "1", "b": "15"}
    )
    score = score_structured(card, {"a": "1.", "b": "1.5."})
    assert score.correct_coded_fields == 2
    assert score.mismatches == []


def test_letter_lookalikes_fold_to_digits():
    """Handwritten 0 and 1 come back as O/Q and !/L/I. No code holds a letter."""
    card = BenchmarkCard(
        page_id="5",
        source_page=5,
        image_path=None,
        fields={"a": "0", "b": "0", "c": "1", "d": "1"},
    )
    score = score_structured(card, {"a": "O", "b": "Q", "c": "!", "d": "L"})
    assert score.correct_coded_fields == 4


def test_folding_never_rescues_a_different_code():
    card = BenchmarkCard(
        page_id="6", source_page=6, image_path=None, fields={"a": "0", "b": "04"}
    )
    score = score_structured(card, {"a": "8", "b": "4"})
    assert score.correct_coded_fields == 0


def test_void_mark_wins_over_lookalike_folding():
    """A coder's "B" means no code -- it must not fold to a digit."""
    card = BenchmarkCard(
        page_id="7", source_page=7, image_path=None, fields={"a": "-", "b": "1"}
    )
    score = score_structured(card, {"a": "B.", "b": "L"})
    assert score.correct_fields == 2
    assert (score.correct_coded_fields, score.coded_fields) == (1, 1)


# --- agreement between two extractors (IT-98 AC2) ---------------------------
# Same comparison the scorer uses, so a pair of readings can never count as
# agreeing while scoring as a mismatch.

import pytest
from scoring import agrees


@pytest.mark.parametrize(
    "first, second",
    [
        ("56", "56"),  # the easy case
        ("1", "1."),  # leader dots read as part of the number
        ("15", "1.5."),
        ("0", "O"),  # handwritten 0 comes back as a letter
        ("0", "Q"),
        ("1", "!"),
        ("1", "L"),
        ("", "-"),  # the transcriber's blank vs their dash
        ("-", "B"),  # ... vs the coder's void mark on the card
        ("B", "BBB"),
        (None, ""),  # a model omitting the key vs returning it empty
        (None, "-"),
        (" 3 ", "3"),  # surrounding whitespace
    ],
)
def test_noise_only_differences_agree(first, second):
    assert agrees(first, second)
    assert agrees(second, first)  # order can't matter


@pytest.mark.parametrize("first, second", [("04", "4"), ("4", "04"), ("060", "60")])
def test_leading_zero_is_a_real_disagreement(first, second):
    """IT-98's AC2 originally asked for these to agree. Dropped: under a
    fixed-width code book they are different codes, so one model has misread a
    real value. Papering over it would hide the disagreement a reviewer needs
    (D011, and test_leading_zero_is_not_the_same_code above)."""
    assert not agrees(first, second)


@pytest.mark.parametrize("first, second", [("3", "8"), ("0", "8"), ("1", "7")])
def test_different_codes_disagree(first, second):
    assert not agrees(first, second)


def test_a_value_never_agrees_with_no_value():
    """The case that would silently inflate every confidence score downstream:
    one model read a code, the other read nothing. That is a disagreement, not
    a match."""
    for blank in ("", "-", "B", None):
        assert not agrees("3", blank)
        assert not agrees(blank, "3")


def test_agreement_matches_the_scorer():
    """agrees() and score_structured() must never disagree about equality --
    two definitions of "same value" is the bug this shares one function to
    avoid."""
    pairs = [("04", "4"), ("1", "1."), ("0", "O"), ("-", "B"), ("3", "8"), ("56", "56")]
    card = BenchmarkCard(
        page_id="8",
        source_page=8,
        image_path=None,
        fields={f"f{i}": expected for i, (expected, _) in enumerate(pairs)},
    )
    score = score_structured(card, {f"f{i}": got for i, (_, got) in enumerate(pairs)})
    scored_ok = {f"f{i}" for i in range(len(pairs))} - {m[0] for m in score.mismatches}
    assert scored_ok == {f"f{i}" for i, (a, b) in enumerate(pairs) if agrees(a, b)}

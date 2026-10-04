"""IT-85: one confidence score per card, from its field scores (FR-20).

One test per acceptance criterion. AC1 (every record from a run carries the
score) lives with pair_cards in test_dual_extract.py; this file covers the
function itself.
"""

import random

import pytest

from survey.confidence.card import assert_every_card_scored, card_confidence

# D016's flat class constants, copied rather than imported to keep this file
# off the pipeline's import chain. Inputs here, never asserted.
AGREE = 0.97
BOTH_BLANK = 0.97
ONE_BLANK_LOW = 0.14


def test_deterministic():
    """AC2."""
    scores = [0.97] * 50 + [0.75] * 8 + [0.14] * 4
    assert card_confidence(scores) == card_confidence(scores)


def test_order_does_not_matter():
    """AC2: the formula is over the set of scores, not their position."""
    scores = [0.97] * 50 + [0.75] * 8 + [0.14] * 4
    shuffled = scores[:]
    random.Random(0).shuffle(shuffled)
    assert card_confidence(shuffled) == card_confidence(scores)


def test_a_few_weak_fields_are_not_masked():
    """AC3: 56 clean fields and 6 bad ones must not read as a clean card."""
    scores = [AGREE] * 56 + [ONE_BLANK_LOW] * 6
    plain_mean = sum(scores) / len(scores)
    card = card_confidence(scores)

    assert plain_mean > 0.85, "the plain mean would hide them"
    assert card < 0.75, f"card scored {card}, reads as confident"
    assert card < plain_mean


def test_more_weak_fields_score_lower_than_fewer():
    """AC3: unlike min(), the card can rank one weak field against many."""
    one_weak = card_confidence([AGREE] * 61 + [ONE_BLANK_LOW])
    six_weak = card_confidence([AGREE] * 56 + [ONE_BLANK_LOW] * 6)
    assert six_weak < one_weak < AGREE


@pytest.mark.parametrize("uniform", [1.0, 0.0, AGREE])
def test_uniform_fields_give_that_score(uniform):
    """AC4: every field at 1.0 is 1.0; every field at the floor is the floor."""
    assert card_confidence([uniform] * 62) == uniform


def test_an_all_blank_card_is_the_both_blank_constant():
    """AC5: blank on both arms is a scored class, so the card scores it."""
    assert card_confidence([BOTH_BLANK] * 62) == BOTH_BLANK


def test_a_card_with_no_fields_scores_zero():
    """AC5: no evidence at all is 0.0, not an error."""
    assert card_confidence([]) == 0.0


def test_accepts_any_iterable():
    assert card_confidence(s for s in (0.5, 0.5, 0.5, 0.5)) == 0.5


@pytest.mark.parametrize("bad", [None, "0.9", True, 1.5, -0.1])
def test_a_bad_score_is_rejected(bad):
    with pytest.raises((TypeError, ValueError)):
        card_confidence([0.97, bad, 0.97])


def test_result_stays_in_range():
    scores = [random.Random(1).random() for _ in range(62)]
    assert 0.0 <= card_confidence(scores) <= 1.0


@pytest.mark.parametrize(
    "record",
    [
        {"page_id": "p1"},  # the score was never written
        {"page_id": "p1", "card_confidence": None},
        {"page_id": "p1", "card_confidence": 1.5},
    ],
)
def test_the_assertion_rejects_an_unscored_card(record):
    """AC1: the schema assertion, so a run cannot quietly ship a card
    without a usable score."""
    with pytest.raises(AssertionError):
        assert_every_card_scored([record])

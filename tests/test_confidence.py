"""Agreement class to a number (IT-99).

Every constant here is measured, and the test that proves it is
test_constants_still_match_the_benchmark. The rest of this file guards the
properties the formula has to hold whatever the numbers are: in range,
ordered, deterministic, and never treating a missing arm as agreement.
"""

import pytest
from confidence import CONFIDENCE_BY_CLASS, STANDALONE_ACCURACY, confidence_for
from dual_extract import AGREE, BOTH_BLANK, DISAGREE, NO_SECOND_OPINION, ONE_BLANK


def test_every_class_has_a_score():
    """AC1: a class with no constant is a field with no confidence."""
    assert set(CONFIDENCE_BY_CLASS) == {
        AGREE,
        DISAGREE,
        ONE_BLANK,
        BOTH_BLANK,
        NO_SECOND_OPINION,
    }


@pytest.mark.parametrize("agreement", [AGREE, DISAGREE, ONE_BLANK, BOTH_BLANK])
def test_scores_are_in_range(agreement):
    assert 0.0 <= confidence_for(agreement) <= 1.0


def test_agreement_scores_higher_than_disagreement():
    """AC2: the whole point. Agreement high, disagreement materially lower."""
    assert confidence_for(AGREE) > confidence_for(ONE_BLANK)
    assert confidence_for(ONE_BLANK) > confidence_for(DISAGREE)
    assert confidence_for(AGREE) - confidence_for(DISAGREE) > 0.1


def test_a_missing_arm_never_scores_as_agreement():
    """AC4, and the mistake IT-98 built a whole class to prevent. A hosted
    failure must not read as two models concurring."""
    assert confidence_for(NO_SECOND_OPINION, "gemini-3.5-flash") < confidence_for(AGREE)


def test_a_missing_arm_is_scored_by_which_arm_survived():
    """One qwen reading is worth much less than one gemini reading, and a
    single constant would flatter the weaker of the two."""
    assert confidence_for(NO_SECOND_OPINION, "gemini-3.5-flash") > confidence_for(
        NO_SECOND_OPINION, "qwen2.5-vl"
    )


def test_no_reading_at_all_scores_zero():
    """Both arms failed the card: no evidence, and the one place 0.0 is honest."""
    assert confidence_for(NO_SECOND_OPINION, None) == 0.0


def test_an_unknown_surviving_model_falls_back_to_the_weakest():
    """An arm with no measured accuracy must not inherit gemini's. Understating
    routes a field to review; overstating ships it unchecked."""
    assert confidence_for(NO_SECOND_OPINION, "some-new-model") == min(
        STANDALONE_ACCURACY.values()
    )


def test_deterministic():
    """AC5."""
    assert [confidence_for(AGREE) for _ in range(5)] == [confidence_for(AGREE)] * 5


def test_an_unknown_class_is_an_error_not_a_default():
    """A silent default here is a field carrying a number that means nothing."""
    with pytest.raises(KeyError):
        confidence_for("probably_fine")

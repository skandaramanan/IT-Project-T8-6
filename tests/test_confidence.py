"""Agreement class to a number (IT-99).

Every constant here is measured, and the test that proves it is
test_constants_still_match_the_benchmark. The rest of this file guards the
properties the formula has to hold whatever the numbers are: in range,
ordered, deterministic, and never treating a missing arm as agreement.
"""

from collections import Counter

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


# --- scoring a whole card ---------------------------------------------------

from confidence import assert_every_field_scored, score_fields
from dual_extract import compare_fields

MODELS = {"a": "gemini-3.5-flash", "b": "qwen2.5-vl"}
FIELDS = ["Municipality", "Weekly Rent", "Garden"]


def test_each_field_gets_the_triple():
    """AC1: {value, confidence, source_agreement} on every field."""
    paired = compare_fields({"Municipality": "56"}, {"Municipality": "56"}, FIELDS)
    scored = score_fields(paired, MODELS)
    assert set(scored["Municipality"]) == {"value", "confidence", "source_agreement"}
    assert scored["Municipality"]["source_agreement"] == AGREE
    assert scored["Municipality"]["confidence"] == 0.99


def test_the_value_is_the_primary_arms_reading():
    """The score was measured about arm A's reading, so it travels with it.
    IT-86 may overwrite the value; the score then has to be recomputed."""
    paired = compare_fields({"Municipality": "56"}, {"Municipality": "57"}, FIELDS)
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["value"] == "56"
    assert scored["Municipality"]["source_agreement"] == DISAGREE


def test_a_blank_primary_reading_is_still_the_primary_reading():
    """A dropped key is a reading of "no code", not a dead arm. The one_blank
    constant is P(gemini correct) measured over exactly these cases, so the
    value has to stay gemini's blank -- swapping in qwen's value would attach
    0.85 to a reading it was never measured about. This is the Washouse shape:
    qwen omits the key on 29 of 30 cards, and there gemini's blank is the one
    that was right."""
    paired = compare_fields({"Municipality": None}, {"Municipality": "56"}, FIELDS)
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["source_agreement"] == ONE_BLANK
    assert scored["Municipality"]["value"] == ""
    assert scored["Municipality"]["confidence"] == 0.85


def test_a_missing_arm_is_scored_by_the_surviving_one():
    """AC4 end to end: gemini answered, qwen did not."""
    paired = compare_fields({"Municipality": "56"}, None, FIELDS)
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["source_agreement"] == NO_SECOND_OPINION
    assert scored["Municipality"]["confidence"] == 0.94
    assert scored["Municipality"]["value"] == "56"


def test_the_surviving_arm_can_be_the_second_one():
    """gemini died, qwen answered -- worth less, and the score must say so."""
    paired = compare_fields(None, {"Municipality": "56"}, FIELDS)
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["confidence"] == 0.75
    assert scored["Municipality"]["value"] == "56"


def test_a_card_neither_arm_read_scores_zero():
    paired = compare_fields(None, None, FIELDS)
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["confidence"] == 0.0
    assert scored["Municipality"]["value"] == ""


def test_assertion_passes_a_fully_scored_card():
    paired = compare_fields({"Municipality": "56"}, {"Municipality": "56"})
    assert_every_field_scored(score_fields(paired, MODELS))  # 62 fields, no raise


def test_assertion_fails_a_missing_score():
    """AC1: the run must fail, not warn."""
    scored = score_fields(compare_fields({}, {}), MODELS)
    del scored["Municipality"]["confidence"]
    with pytest.raises(AssertionError, match="Municipality"):
        assert_every_field_scored(scored)


def test_assertion_fails_an_out_of_range_score():
    scored = score_fields(compare_fields({}, {}), MODELS)
    scored["Municipality"]["confidence"] = 1.4
    with pytest.raises(AssertionError, match="1.4"):
        assert_every_field_scored(scored)


def test_assertion_fails_a_short_card():
    """62, not 60. An assertion hardcoded to the C3 count fails every real
    card -- the correction IT-99 was reopened for."""
    scored = score_fields(compare_fields({}, {}, FIELDS), MODELS)
    with pytest.raises(AssertionError, match="62"):
        assert_every_field_scored(scored)


def test_a_non_numeric_score_is_rejected():
    """AC1 says numeric. A band string here would validate as 'present' under
    a truthiness check and breach D007's number type on the way out."""
    scored = score_fields(compare_fields({}, {}), MODELS)
    scored["Municipality"]["confidence"] = "high"
    with pytest.raises(AssertionError, match="Municipality"):
        assert_every_field_scored(scored)


# --- the constants are measured, and stay measured --------------------------

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
GROUND_TRUTH = REPO_ROOT / "data/benchmark/c1c2/coding-card-c1-c2-ground-truth.xlsx"
RESULTS = REPO_ROOT / "data/benchmark/results"


@pytest.mark.skipif(
    not GROUND_TRUTH.is_file(),
    reason="needs data/ (Drive), absent in CI -- see D004",
)
def test_constants_still_match_the_benchmark():
    """AC3/AC6: the constants are measured, not chosen. This re-derives them
    from the saved arms and fails if they have drifted -- which is what adding
    cards to the benchmark should do, as a prompt to recalibrate D016 rather
    than a silent divergence between the doc and the code.

    Reads the sheet, never writes it.
    """
    from dual_extract import pair_cards
    from ground_truth import DEFAULT_IMAGES_DIR, load_ground_truth
    from scoring import normalise

    cards = load_ground_truth(GROUND_TRUTH, REPO_ROOT / DEFAULT_IMAGES_DIR)
    truth = {c.page_id: c.fields for c in cards}
    records = pair_cards(
        "gemini-3.5-flash",
        "qwen2.5-vl",
        RESULTS,
        page_ids=[c.page_id for c in cards],
    )

    right: Counter = Counter()
    seen: Counter = Counter()
    for record in records:
        for name, field in record["fields"].items():
            if name not in truth[record["page_id"]]:
                continue
            seen[field["agreement"]] += 1
            right[field["agreement"]] += field["a"] == normalise(
                truth[record["page_id"]][name]
            )

    for agreement in (AGREE, ONE_BLANK, DISAGREE):
        measured = right[agreement] / seen[agreement]
        assert abs(measured - CONFIDENCE_BY_CLASS[agreement]) < 0.03, (
            f"{agreement}: constant is {CONFIDENCE_BY_CLASS[agreement]}, "
            f"benchmark now says {measured:.3f} over {seen[agreement]} fields. "
            f"Recalibrate D016 rather than widening this tolerance."
        )


@pytest.mark.skipif(
    not GROUND_TRUTH.is_file(),
    reason="needs data/ (Drive), absent in CI -- see D004",
)
def test_the_unmeasured_classes_are_still_unmeasured():
    """both_blank and no_second_opinion have n=0 on this benchmark, which is
    why their constants are reasoned rather than measured. If a future
    benchmark produces some, D016's caveat is stale and needs rewriting."""
    from dual_extract import pair_cards
    from ground_truth import DEFAULT_IMAGES_DIR, load_ground_truth

    cards = load_ground_truth(GROUND_TRUTH, REPO_ROOT / DEFAULT_IMAGES_DIR)
    records = pair_cards(
        "gemini-3.5-flash",
        "qwen2.5-vl",
        RESULTS,
        page_ids=[c.page_id for c in cards],
    )
    observed: Counter = Counter()
    for record in records:
        observed.update(record["counts"])

    assert observed[BOTH_BLANK] == 0 and observed[NO_SECOND_OPINION] == 0, (
        "a class D016 records as unmeasured now has data -- measure it and "
        "replace the reasoned constant"
    )

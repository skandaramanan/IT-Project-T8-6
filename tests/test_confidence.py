"""Agreement class to a number (IT-99).

Every constant here is measured, and the tests that prove it are
test_constants_still_match_the_benchmark and test_band_constants_still_match_
the_live_run. The rest of this file guards the properties the formula has to
hold whatever the numbers are: in range, ordered, deterministic, and never
treating a missing arm as agreement.

Calibrated to gemini-3.5-flash-lite (the model that ships), not flash --
recalibrated 2026-09-09 after pairing flash-lite against qwen directly and
finding it meaningfully less reliable in every class than flash, worst on
ONE_BLANK (73.7% vs flash's 85.1%).
"""

from collections import Counter

import pytest

from survey.confidence.agreement import (
    AGREE,
    BOTH_BLANK,
    DISAGREE,
    NO_SECOND_OPINION,
    ONE_BLANK,
)
from survey.confidence.field import (
    BAND_ACCURACY_BY_CLASS,
    CONFIDENCE_BY_CLASS,
    NO_SECOND_OPINION_BAND_ACCURACY,
    STANDALONE_ACCURACY,
    confidence_for,
)


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
    """AC2: the whole point. Agreement high, disagreement materially lower.

    AC2 does not require one_blank to outrank disagree, only that both sit
    well below agree -- and on flash-lite they no longer do (73.7% vs 75.1%,
    a near-tie, reversed from flash's 85.1% vs 79.1%). Asserting that
    ordering here would be testing an artefact of which model got measured,
    not a property the formula actually promises."""
    assert confidence_for(AGREE) > confidence_for(ONE_BLANK)
    assert confidence_for(AGREE) > confidence_for(DISAGREE)
    assert confidence_for(AGREE) - confidence_for(DISAGREE) > 0.1
    assert confidence_for(AGREE) - confidence_for(ONE_BLANK) > 0.1


def test_a_missing_arm_never_scores_as_agreement():
    """AC4, and the mistake IT-98 built a whole class to prevent. A hosted
    failure must not read as two models concurring."""
    assert confidence_for(NO_SECOND_OPINION, "gemini-3.5-flash-lite") < confidence_for(
        AGREE
    )


def test_a_missing_arm_is_scored_by_which_arm_survived():
    """One qwen reading is worth much less than one gemini-lite reading, and
    a single constant would flatter the weaker of the two."""
    assert confidence_for(NO_SECOND_OPINION, "gemini-3.5-flash-lite") > confidence_for(
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

from survey.confidence.agreement import compare_fields
from survey.confidence.field import (
    assert_every_field_scored,
    resolve_primary_value,
    score_fields,
)

MODELS = {"a": "gemini-3.5-flash-lite", "b": "qwen2.5-vl"}
FIELDS = ["Municipality", "Weekly Rent", "Garden"]


def test_each_field_gets_the_triple():
    """AC1: {value, confidence, source_agreement} on every field."""
    paired = compare_fields({"Municipality": "56"}, {"Municipality": "56"}, FIELDS)
    scored = score_fields(paired, MODELS)
    assert set(scored["Municipality"]) == {"value", "confidence", "source_agreement"}
    assert scored["Municipality"]["source_agreement"] == AGREE
    assert scored["Municipality"]["confidence"] == 0.97


def test_the_value_is_the_primary_arms_reading():
    """D021 selects arm A, the reading the score was measured about.

    A future policy that selects arm B must recalibrate the score against the
    value it writes.
    """
    paired = compare_fields({"Municipality": "56"}, {"Municipality": "57"}, FIELDS)
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["value"] == "56"
    assert scored["Municipality"]["source_agreement"] == DISAGREE


def test_a_blank_primary_reading_is_still_the_primary_reading():
    """A dropped key is a reading of "no code", not a dead arm. The one_blank
    constant is P(gemini-lite correct) measured over exactly these cases, so
    the value has to stay gemini-lite's blank -- swapping in qwen's value
    would attach 0.74 to a reading it was never measured about."""
    paired = compare_fields({"Municipality": None}, {"Municipality": "56"}, FIELDS)
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["source_agreement"] == ONE_BLANK
    assert scored["Municipality"]["value"] == ""
    assert scored["Municipality"]["confidence"] == 0.74


@pytest.mark.parametrize(
    "first, second, expected",
    [
        ("56", "56", "56"),  # agree
        ("56", "57", "56"),  # disagree
        ("56", None, "56"),  # Gemini value, Qwen blank
        (None, "56", ""),  # Gemini blank, Qwen value
        (None, None, ""),  # both blank
    ],
)
def test_all_paired_outcomes_keep_gemini_as_primary(first, second, expected):
    """IT-86: a field-level blank is a Gemini result, not an arm failure.

    Selecting Qwen whenever it is the only non-blank value would make the
    authority rule depend on output shape and would detach ONE_BLANK's measured
    confidence from the selected reading.
    """
    field = compare_fields({"Municipality": first}, {"Municipality": second}, FIELDS)[
        "Municipality"
    ]
    assert resolve_primary_value(field) == expected


def test_a_missing_arm_is_scored_by_the_surviving_one():
    """AC4 end to end: gemini-lite answered, qwen did not."""
    paired = compare_fields({"Municipality": "56"}, None, FIELDS)
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["source_agreement"] == NO_SECOND_OPINION
    assert scored["Municipality"]["confidence"] == 0.91
    assert scored["Municipality"]["value"] == "56"


def test_the_surviving_arm_can_be_the_second_one():
    """gemini-lite died, qwen answered -- worth less, and the score must say
    so."""
    paired = compare_fields(None, {"Municipality": "56"}, FIELDS)
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["confidence"] == 0.75
    assert scored["Municipality"]["value"] == "56"


def test_qwen_is_selected_only_when_gemini_arm_failed():
    """IT-86 distinguishes a whole-arm failure from Gemini returning blank."""
    field = compare_fields(None, {"Municipality": "56"}, FIELDS)["Municipality"]
    assert field["agreement"] == NO_SECOND_OPINION
    assert resolve_primary_value(field) == "56"


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


# --- the self-reported band, inside AGREE/DISAGREE/ONE_BLANK ----------------
#
# Extended 2026-09-09: pairing the banded gemini-3.5-flash-lite run against
# qwen (rather than scoring it standalone) gives real (class, band) accuracy,
# not just accuracy-by-band unconditioned on class. Cells with n < 10
# (agree/low n=2, disagree/low n=8) are deliberately excluded from
# BAND_ACCURACY_BY_CLASS and fall back to the flat class constant -- one
# documented threshold, not a per-cell judgement call.


def test_a_recognised_band_overrides_agree():
    """agree/high (96.9%) tracks the flat constant closely; agree/medium
    (91.3%) is a real, measurable drop -- worth surfacing rather than
    flattening into the same 0.97 every agree field gets."""
    assert (
        confidence_for(AGREE, band="medium")
        == BAND_ACCURACY_BY_CLASS[(AGREE, "medium")]
    )
    assert confidence_for(AGREE, band="medium") < confidence_for(AGREE)


def test_a_recognised_band_overrides_disagree():
    """A disagreeing field where gemini-lite also sounds unsure (medium) is
    barely better than a coin flip -- far below the flat disagree constant,
    and worth knowing separately from a disagreeing field gemini-lite called
    high."""
    assert (
        confidence_for(DISAGREE, band="medium")
        == BAND_ACCURACY_BY_CLASS[(DISAGREE, "medium")]
    )
    assert confidence_for(DISAGREE, band="medium") < confidence_for(DISAGREE)
    assert confidence_for(DISAGREE, band="medium") < 0.5


def test_a_recognised_band_overrides_one_blank():
    """one_blank/low (13.6%) is worse than any flat class constant in this
    formula -- the strongest single signal the table produces."""
    assert (
        confidence_for(ONE_BLANK, band="low")
        == BAND_ACCURACY_BY_CLASS[(ONE_BLANK, "low")]
    )
    assert confidence_for(ONE_BLANK, band="low") < confidence_for(DISAGREE)


def test_a_too_thin_cell_falls_back_to_the_flat_constant():
    """agree/low and disagree/low both measured n < 10 -- excluded from
    BAND_ACCURACY_BY_CLASS on purpose, so they read as the flat class
    constant rather than an unmeasured guess."""
    assert (AGREE, "low") not in BAND_ACCURACY_BY_CLASS
    assert confidence_for(AGREE, band="low") == confidence_for(AGREE)
    assert (DISAGREE, "low") not in BAND_ACCURACY_BY_CLASS
    assert confidence_for(DISAGREE, band="low") == confidence_for(DISAGREE)


def test_both_blank_never_gets_a_band_override():
    """BOTH_BLANK has n=1 total, band or not -- nowhere near enough to
    calibrate a band cell. It always reads as the flat (inherited) constant."""
    assert confidence_for(BOTH_BLANK, band="low") == confidence_for(BOTH_BLANK)
    assert confidence_for(BOTH_BLANK, band="high") == confidence_for(BOTH_BLANK)


def test_no_band_falls_back_to_the_flat_class_constant():
    """The normal case for an unbanded run: no regression for every field
    scored before band-awareness existed."""
    assert confidence_for(AGREE) == 0.97
    assert confidence_for(DISAGREE) == 0.75
    assert confidence_for(ONE_BLANK) == 0.74
    assert confidence_for(AGREE, band=None) == confidence_for(AGREE)


def test_an_unrecognised_band_string_is_ignored_for_every_class():
    """parse_confidence_bands already restricts bands to low/medium/high, but
    confidence_for must not trust an unvalidated caller either."""
    assert confidence_for(AGREE, band="extremely sure") == confidence_for(AGREE)
    assert confidence_for(DISAGREE, band="extremely sure") == confidence_for(DISAGREE)


def test_score_fields_passes_the_primary_arms_band_through_on_agree():
    """End to end: both arms agree, and gemini-lite's band still prices it."""
    paired = compare_fields(
        {"Municipality": "56"},
        {"Municipality": "56"},
        FIELDS,
        first_bands={"Municipality": "medium"},
    )
    scored = score_fields(paired, MODELS)
    assert (
        scored["Municipality"]["confidence"]
        == BAND_ACCURACY_BY_CLASS[(AGREE, "medium")]
    )


def test_score_fields_passes_the_primary_arms_band_through_on_disagree():
    paired = compare_fields(
        {"Municipality": "56"},
        {"Municipality": "57"},
        FIELDS,
        first_bands={"Municipality": "low"},
    )
    scored = score_fields(paired, MODELS)
    # disagree/low is too thin (n=8) -- falls back to the flat constant.
    assert scored["Municipality"]["confidence"] == confidence_for(DISAGREE)


# --- the self-reported band, for NO_SECOND_OPINION ---------------------------


def test_a_band_refines_no_second_opinion():
    """A self-reported high band is close to the flat flash-lite constant;
    low is far below it. Both have to move the flat 0.91 in the right
    direction, or the band is being ignored rather than used."""
    flat = confidence_for(NO_SECOND_OPINION, "gemini-3.5-flash-lite")
    assert confidence_for(NO_SECOND_OPINION, "gemini-3.5-flash-lite", band="low") < flat
    assert (
        confidence_for(NO_SECOND_OPINION, "gemini-3.5-flash-lite", band="high") > flat
    )


def test_low_band_beats_disagree_as_a_warning_signal():
    """9.1% right is a stronger 'do not trust this' than disagree's 75.1% --
    the band is worth using precisely because it is more decisive."""
    assert confidence_for(
        NO_SECOND_OPINION, "gemini-3.5-flash-lite", band="low"
    ) < confidence_for(DISAGREE)


def test_no_band_falls_back_to_the_flat_no_second_opinion_constant():
    assert confidence_for(NO_SECOND_OPINION, "gemini-3.5-flash-lite") == 0.91
    assert confidence_for(NO_SECOND_OPINION, "gemini-3.5-flash-lite", band=None) == 0.91


def test_score_fields_passes_the_surviving_arms_band_through():
    """End to end: gemini-lite answered with a band, qwen never ran."""
    paired = compare_fields(
        {"Municipality": "56"},
        None,
        FIELDS,
        first_bands={"Municipality": "low"},
    )
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["confidence"] == confidence_for(
        NO_SECOND_OPINION, "gemini-3.5-flash-lite", band="low"
    )
    assert scored["Municipality"]["confidence"] < confidence_for(
        NO_SECOND_OPINION, "gemini-3.5-flash-lite"
    )


def test_score_fields_uses_the_second_arms_band_when_it_survived():
    """gemini died, qwen never bands -- but if the arm that survived is a
    banded gemini call, its band has to travel with it, not the dead arm's."""
    paired = compare_fields(
        None,
        {"Municipality": "56"},
        FIELDS,
        second_bands={"Municipality": "high"},
    )
    scored = score_fields(paired, {"a": "qwen2.5-vl", "b": "gemini-3.5-flash-lite"})
    assert scored["Municipality"]["confidence"] == confidence_for(
        NO_SECOND_OPINION, "gemini-3.5-flash-lite", band="high"
    )


# --- the constants are measured, and stay measured --------------------------

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
GROUND_TRUTH = REPO_ROOT / "data/benchmark/c1c2/coding-card-c1-c2-ground-truth.xlsx"
RESULTS = REPO_ROOT / "data/benchmark/results"
PRIMARY_ARM = "gemini-3.5-flash-lite"


@pytest.mark.skipif(
    not GROUND_TRUTH.is_file(),
    reason="needs data/ (Drive), absent in CI -- see D004",
)
def test_constants_still_match_the_benchmark():
    """AC3/AC6: the constants are measured, not chosen. Re-derives them from
    gemini-3.5-flash-lite paired against qwen -- the model that ships -- and
    fails if they have drifted. Reads the sheet, never writes it.
    """
    from dual_extract import pair_cards
    from ground_truth import DEFAULT_IMAGES_DIR, load_ground_truth
    from survey.extraction.record import normalise

    cards = load_ground_truth(GROUND_TRUTH, REPO_ROOT / DEFAULT_IMAGES_DIR)
    truth = {c.page_id: c.fields for c in cards}
    records = pair_cards(
        PRIMARY_ARM,
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
def test_both_blank_is_still_too_thin_to_measure():
    """BOTH_BLANK moved from n=0 (flash vs qwen) to n=1 (flash-lite vs qwen)
    once recalibrated -- still far short of anything trustworthy. Fails
    loudly once a benchmark produces enough to replace the inherited AGREE
    constant with a real measurement."""
    from dual_extract import pair_cards
    from ground_truth import DEFAULT_IMAGES_DIR, load_ground_truth

    cards = load_ground_truth(GROUND_TRUTH, REPO_ROOT / DEFAULT_IMAGES_DIR)
    records = pair_cards(
        PRIMARY_ARM,
        "qwen2.5-vl",
        RESULTS,
        page_ids=[c.page_id for c in cards],
    )
    observed: Counter = Counter()
    for record in records:
        observed.update(record["counts"])

    assert observed[BOTH_BLANK] < 10, (
        "both_blank now has enough fields to measure -- replace the "
        "inherited AGREE constant with a real one in D016"
    )
    assert observed[NO_SECOND_OPINION] == 0, (
        "no arm has ever failed on this benchmark -- if one now has, "
        "NO_SECOND_OPINION is reachable here and worth a dedicated check"
    )


@pytest.mark.skipif(
    not (RESULTS / "gemini-3.5-flash-lite-banded" / "raw").is_dir(),
    reason="needs the banded run's saved output, absent in CI -- see D004",
)
def test_band_constants_still_match_the_live_run():
    """The band constants are measured against a real API call, not assumed.
    Re-derives NO_SECOND_OPINION_BAND_ACCURACY (standalone) from the saved
    banded output, and BAND_ACCURACY_BY_CLASS (paired against qwen) from the
    same run -- wider tolerance than the flat constants' because every one of
    these cells has thinner support.
    """
    from dual_extract import pair_cards
    from ground_truth import DEFAULT_IMAGES_DIR, load_ground_truth
    from survey.extraction.json_extraction import (
        parse_confidence_bands,
        parse_json_fields,
    )
    from survey.extraction.record import normalise

    banded_raw = RESULTS / "gemini-3.5-flash-lite-banded" / "raw"
    cards = load_ground_truth(GROUND_TRUTH, REPO_ROOT / DEFAULT_IMAGES_DIR)

    # Standalone: band alone, unconditioned on class (NO_SECOND_OPINION's case).
    right: Counter = Counter()
    seen: Counter = Counter()
    for card in cards:
        path = banded_raw / f"{card.page_id}.txt"
        if not path.is_file():
            continue
        text = path.read_text()
        fields = parse_json_fields(text) or {}
        bands = parse_confidence_bands(text)
        for name, expected in card.fields.items():
            band = bands.get(name)
            if band is None:
                continue
            seen[band] += 1
            right[band] += normalise(fields.get(name)) == normalise(expected)

    for band in ("high", "medium", "low"):
        measured = right[band] / seen[band]
        assert abs(measured - NO_SECOND_OPINION_BAND_ACCURACY[band]) < 0.05, (
            f"{band}: constant is {NO_SECOND_OPINION_BAND_ACCURACY[band]}, live "
            f"run now says {measured:.3f} over {seen[band]} fields. "
            f"Recalibrate D016."
        )

    # Paired against qwen: (class, band), BAND_ACCURACY_BY_CLASS's case.
    truth = {c.page_id: c.fields for c in cards}
    records = pair_cards(
        "gemini-3.5-flash-lite-banded",
        "qwen2.5-vl",
        RESULTS,
        page_ids=[c.page_id for c in cards],
    )
    class_right: Counter = Counter()
    class_seen: Counter = Counter()
    for record in records:
        for name, field in record["fields"].items():
            if name not in truth[record["page_id"]]:
                continue
            band = field.get("a_band")
            key = (field["agreement"], band)
            class_seen[key] += 1
            class_right[key] += field["a"] == normalise(truth[record["page_id"]][name])

    for key, constant in BAND_ACCURACY_BY_CLASS.items():
        n = class_seen[key]
        assert n >= 10, f"{key}: only {n} fields now -- below the n>=10 threshold"
        measured = class_right[key] / n
        assert abs(measured - constant) < 0.05, (
            f"{key}: constant is {constant}, live run now says {measured:.3f} "
            f"over {n} fields. Recalibrate D016."
        )

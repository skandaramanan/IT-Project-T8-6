"""Confidence for the current normalized Q6 pairing (IT-125, D016 addendum D).

Synthetic policy checks always run; saved-input checks pin exact denominators
and rounded constants when the local benchmark inputs are available.
"""

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
    """AC2: agreement materially outranks both disagreement classes.

    Their relative ordering is measured, not a requirement of the formula.
    """
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
    assert scored["Municipality"]["confidence"] == 0.98


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
    """An explicit null is a blank reading, not an unavailable arm. The one_blank
    constant is P(gemini-lite correct) measured over exactly these cases, so
    the value has to stay gemini-lite's blank -- swapping in qwen's value
    would attach 0.51 to a reading it was never measured about."""
    paired = compare_fields({"Municipality": None}, {"Municipality": "56"}, FIELDS)
    scored = score_fields(paired, MODELS)
    assert scored["Municipality"]["source_agreement"] == ONE_BLANK
    assert scored["Municipality"]["value"] == ""
    assert scored["Municipality"]["confidence"] == 0.51


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
    assert scored["Municipality"]["confidence"] == 0.85
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
# Recomputed 2026-10-17: pairing the saved banded gemini-3.5-flash-lite run against
# qwen (rather than scoring it standalone) gives real (class, band) accuracy,
# not just accuracy-by-band unconditioned on class. Cells with n < 10
# (agree/low n=4, disagree/low n=7) are deliberately excluded from
# BAND_ACCURACY_BY_CLASS and fall back to the flat class constant -- one
# documented threshold, not a per-cell judgement call.


def test_a_recognised_band_overrides_agree():
    """agree/high (98.5%) tracks the flat constant closely; agree/medium
    (88.5%) is a real, measurable drop -- worth surfacing rather than
    flattening into the same 0.98 every agree field gets."""
    assert (
        confidence_for(AGREE, band="medium")
        == BAND_ACCURACY_BY_CLASS[(AGREE, "medium")]
    )
    assert confidence_for(AGREE, band="medium") < confidence_for(AGREE)


def test_a_recognised_band_overrides_disagree():
    """A disagreeing field where gemini-lite also sounds unsure (medium) is
    worse than a coin flip -- far below the flat disagree constant,
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
    """BOTH_BLANK has n=0 total, band or not -- nowhere near enough to
    calibrate a band cell. It always reads as the flat (inherited) constant."""
    assert confidence_for(BOTH_BLANK, band="low") == confidence_for(BOTH_BLANK)
    assert confidence_for(BOTH_BLANK, band="high") == confidence_for(BOTH_BLANK)


def test_no_band_falls_back_to_the_flat_class_constant():
    """D028's unbanded run uses the newly measured flat constants."""
    assert confidence_for(AGREE) == 0.98
    assert confidence_for(DISAGREE) == 0.64
    assert confidence_for(ONE_BLANK) == 0.51
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
    # disagree/low is too thin (n=7) -- falls back to the flat constant.
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
    """9.1% right is a stronger 'do not trust this' than disagree's 63.9% --
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


# --- reproducible supplied-Q6 benchmark regression --------------------------

import json
from pathlib import Path

from calibrate_confidence import calibrate, compact_calibration, measure_pair

REPO_ROOT = Path(__file__).parent.parent
GROUND_TRUTH = REPO_ROOT / "data/benchmark/c1c2/coding-card-c1-c2-ground-truth.xlsx"
RESULTS = REPO_ROOT / "data/benchmark/results"
Q6_RAW = (
    REPO_ROOT
    / "data/it124-review-20261017/handoff/data/benchmark/results/q6-2mp-rp1.05/raw"
)
SAVED_INPUTS = (
    GROUND_TRUTH.is_file()
    and Q6_RAW.is_dir()
    and all(
        (RESULTS / model / "raw").is_dir()
        for model in ("gemini-3.5-flash-lite", "gemini-3.5-flash-lite-banded")
    )
)


PINNED_CALIBRATION = REPO_ROOT / "docs/runs/it125-calibration.json"


@pytest.fixture(scope="module", params=["pinned", "live"])
def calibration(request):
    """Tracked evidence always checks constants; raw remeasurement checks drift."""
    pinned = json.loads(PINNED_CALIBRATION.read_text())
    if request.param == "pinned":
        return pinned
    if not SAVED_INPUTS:
        pytest.skip(
            "raw remeasurement requires supplied Q6 handoff and benchmark inputs (D004)"
        )
    measured = calibrate(
        GROUND_TRUTH,
        RESULTS / "gemini-3.5-flash-lite/raw",
        RESULTS / "gemini-3.5-flash-lite-banded/raw",
        Q6_RAW,
    )
    assert compact_calibration(measured) == pinned
    return measured


def test_tracked_calibration_evidence_is_complete_and_portable():
    report = json.loads(PINNED_CALIBRATION.read_text())
    assert "paths" not in report
    assert report["minimum_band_sample"] == 10
    assert len(report["ground_truth_sha256"]) == 64
    for mode in ("unbanded", "banded"):
        measurement = report[mode]
        assert measurement["cards"] == 30
        assert measurement["fields"] == 1860
        assert sum(cell["total"] for cell in measurement["classes"].values()) == 1860
        assert (
            sum(cell["correct"] for cell in measurement["classes"].values())
            == measurement["standalone"]["a"]["correct"]
        )
        for table in ("classes", "class_bands", "standalone", "standalone_bands"):
            for cell in measurement[table].values():
                assert cell["accuracy"] == cell["correct"] / cell["total"]
                assert 0 <= cell["correct"] <= cell["total"]
        for arm in ("a", "b"):
            assert sum(measurement["field_states"][arm].values()) == 1860
            manifest = measurement["raw_input_manifests"][arm]
            assert manifest["readings"] == 30
            assert len(manifest["sha256"]) == 64


def test_constants_still_match_the_benchmark(calibration):
    """Pin the actual unbanded production pairing, including omitted fields."""
    measured = calibration["unbanded"]
    expected = {
        AGREE: (1486, 1523),
        DISAGREE: (191, 299),
        ONE_BLANK: (18, 35),
        NO_SECOND_OPINION: (0, 3),
    }
    assert measured["fields"] == 1860
    assert {
        k: (v["correct"], v["total"]) for k, v in measured["classes"].items()
    } == expected
    for agreement in (AGREE, DISAGREE, ONE_BLANK):
        assert CONFIDENCE_BY_CLASS[agreement] == round(
            measured["classes"][agreement]["accuracy"], 2
        )
    assert measured["standalone"]["a"] == {
        "correct": 1695,
        "total": 1860,
        "accuracy": 1695 / 1860,
    }
    assert measured["standalone"]["b"] == {
        "correct": 1574,
        "total": 1860,
        "accuracy": 1574 / 1860,
    }
    assert STANDALONE_ACCURACY["qwen2.5-vl"] == round(1574 / 1860, 2)
    assert STANDALONE_ACCURACY["gemini-3.5-flash-lite"] == round(1695 / 1860, 2)
    assert measured["field_states"]["a"]["omitted"] == 3
    assert measured["field_states"]["b"] == {"blank": 1, "value": 1859}


def test_band_constants_still_match_the_live_run(calibration):
    """Only n>=10 cells qualify; pin measurements without drift tolerances."""
    measured = calibration["banded"]
    expected = {
        AGREE: (1450, 1490),
        DISAGREE: (177, 320),
        ONE_BLANK: (12, 49),
        NO_SECOND_OPINION: (0, 1),
    }
    assert {
        k: (v["correct"], v["total"]) for k, v in measured["classes"].items()
    } == expected
    qualifying = {
        tuple(key.split("/")): round(cell["accuracy"], 2)
        for key, cell in measured["class_bands"].items()
        if cell["total"] >= 10
    }
    assert BAND_ACCURACY_BY_CLASS == qualifying
    assert NO_SECOND_OPINION_BAND_ACCURACY == {
        band: round(cell["accuracy"], 2)
        for band, cell in measured["standalone_bands"].items()
    }
    assert measured["standalone"]["a"]["correct"] == 1639
    assert STANDALONE_ACCURACY["gemini-3.5-flash-lite-banded"] == round(1639 / 1860, 2)


def test_both_blank_is_still_too_thin_to_measure(calibration):
    for config in ("unbanded", "banded"):
        assert calibration[config]["classes"].get(BOTH_BLANK, {}).get("total", 0) == 0
    # A reasoned inherited fallback, never a newly measured blank probability.
    assert CONFIDENCE_BY_CLASS[BOTH_BLANK] == CONFIDENCE_BY_CLASS[AGREE]


def test_omitted_primary_is_not_substituted_or_scored_as_blank():
    paired = compare_fields({}, {"Municipality": "56"}, ["Municipality"])
    field = paired["Municipality"]
    assert field["a_available"] is True
    assert field["a_state"] == "omitted"
    scored = score_fields(paired, MODELS)["Municipality"]
    assert scored == {
        "value": "",
        "confidence": 0.0,
        "source_agreement": NO_SECOND_OPINION,
    }


def test_explicit_primary_blank_survives_an_omitted_secondary_field():
    paired = compare_fields({"Municipality": None}, {}, ["Municipality"])
    scored = score_fields(paired, MODELS)["Municipality"]
    assert scored == {
        "value": "",
        "confidence": 0.91,
        "source_agreement": NO_SECOND_OPINION,
    }


def test_qwen_band_does_not_inherit_gemini_band_calibration():
    assert confidence_for(NO_SECOND_OPINION, "qwen2.5-vl", "high") == 0.85
    assert confidence_for(NO_SECOND_OPINION, "unknown-model", "high") == min(
        STANDALONE_ACCURACY.values()
    )


def test_calibration_counts_omissions_as_incorrect_even_when_truth_is_blank(tmp_path):
    from ground_truth import BenchmarkCard

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "p.txt").write_text('{"Municipality": null}')
    (second / "p.txt").write_text('{"Municipality": null, "Garden": null}')
    cards = [
        BenchmarkCard("p", 1, tmp_path / "p.png", {"Municipality": "", "Garden": ""})
    ]
    measured = measure_pair(cards, first, second)
    assert measured["classes"][BOTH_BLANK] == {
        "correct": 1,
        "total": 1,
        "accuracy": 1.0,
    }
    assert measured["classes"][NO_SECOND_OPINION] == {
        "correct": 0,
        "total": 1,
        "accuracy": 0.0,
    }
    assert measured["standalone"]["a"]["correct"] == 1
    assert measured["field_states"]["a"] == {"blank": 1, "omitted": 1}


def test_calibration_does_not_drop_absent_or_failed_benchmark_arms(tmp_path):
    from ground_truth import BenchmarkCard

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "failed.txt").write_text("no usable reading")
    cards = [
        BenchmarkCard(page, 1, tmp_path / "p.png", {"Municipality": ""})
        for page in ("failed", "absent")
    ]
    measured = measure_pair(cards, first, second)
    assert measured["classes"] == {
        NO_SECOND_OPINION: {"correct": 0, "total": 2, "accuracy": 0.0}
    }
    assert [item["state"] for item in measured["raw_inputs"]["a"]] == [
        "failed",
        "absent",
    ]
    assert measured["standalone"]["a"]["total"] == 2


@pytest.mark.parametrize("raw_primary", [None, "", "56"])
def test_legacy_no_second_opinion_requires_explicit_availability(raw_primary):
    field = {
        "a": raw_primary or "",
        "b": "57",
        "a_raw": raw_primary,
        "b_raw": "57",
        "agreement": NO_SECOND_OPINION,
    }
    with pytest.raises(ValueError, match="a_available is required"):
        resolve_primary_value(field)
    with pytest.raises(ValueError, match="a_available is required"):
        score_fields({"Municipality": field}, MODELS)


def test_availability_metadata_cannot_be_a_truthy_string():
    paired = compare_fields(None, {"Municipality": "56"}, ["Municipality"])
    paired["Municipality"]["a_available"] = "false"
    with pytest.raises(ValueError, match="explicit boolean"):
        score_fields(paired, MODELS)

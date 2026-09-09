"""Turns an agreement class into a per-field confidence score (IT-99).

FR-10 wants a number on every field and no benchmarked engine produces one, so
IT-98 manufactures the evidence -- two independent readings of every card --
and this module prices it.

**The rule, stated once:** a field's confidence is the measured probability
that the primary arm's reading is correct, given the agreement class it fell
into, refined by the primary arm's self-reported band when it gave one. One
rule for all 62 fields, no per-field tuning (AC3). That is the whole formula;
everything below is where the numbers came from.

**Calibrated to gemini-3.5-flash-lite, not flash.** Recalibrated 2026-09-09:
flash-lite is what ships to production (D012 / the IT-98 findings doc), and
the class constants were originally measured on a flash-vs-qwen pairing --
the model that does *not* ship. Pairing flash-lite against qwen instead found
flash-lite meaningfully less reliable in every class, worst on ONE_BLANK
(73.7% vs flash's 85.1%, an 11-point gap). The numbers below replace the
flash-based ones rather than sit alongside them.
test_constants_still_match_the_benchmark re-derives them and fails if they
drift. Full working in docs/decisions/D016-agreement-to-confidence.md.

The self-reported confidence band (``GEMINI_CONFIDENCE_BAND``, IT-98) now
prices AGREE, DISAGREE and ONE_BLANK, not only NO_SECOND_OPINION --
``gemini_extractor.py`` names this module as the place that decision belongs:
"turning 'high' into 0.9 is IT-99's decision, not this adapter's."

Deliberately not done here:

- **Choosing which value wins a disagreement.** That is IT-86. The score
  attaches to the primary arm's reading because that is what it was measured
  about; if IT-86 writes the other arm's value instead, the score has to be
  recomputed against what it actually wrote.
- **Writing into a D007 record.** ``src/extraction/record.py`` still emits
  ``confidence: None``. The envelope's field object is
  ``additionalProperties: false`` with no ``source_agreement`` key, so carrying
  this triple into a real record needs a D007 amendment first -- IT-86's call,
  not one to take by widening the schema here.
- **Banding BOTH_BLANK.** n=1 for that class, banded, still inherits AGREE's
  flat constant unband-conditioned -- see BOTH_BLANK below.
"""

from __future__ import annotations

from dual_extract import AGREE, BOTH_BLANK, DISAGREE, NO_SECOND_OPINION, ONE_BLANK

# P(the primary arm's reading is correct | class), gemini-3.5-flash-lite vs
# qwen2.5-vl, 30 cards, 1,860 comparisons, measured 2026-09-09. The fallback
# used whenever no recognised band is attached to the field -- see
# BAND_ACCURACY_BY_CLASS below for what a band overrides it with.
#
#   class              n      measured    -> constant
#   agree           1,343       97.0%        0.97
#   disagree          398       75.1%        0.75
#   one_blank         118       73.7%        0.74
#
# Superseded 2026-09-09: this ticket originally measured these three on
# gemini-3.5-flash (99.0% / 79.1% / 85.1%), the model the earlier dual-pairing
# work happened to use. flash does not ship -- flash-lite does, at 20x flash's
# free-tier throughput -- so a formula calibrated on flash was pricing
# confidence for a model nobody runs. one_blank moved the most: 85.1% -> 73.7%,
# an 11-point gap. See D016 sec. 1 for the full before/after.
CONFIDENCE_BY_CLASS = {
    AGREE: 0.97,
    ONE_BLANK: 0.74,
    DISAGREE: 0.75,
    # Never observed with a code on this benchmark -- one field, banded "low",
    # wrong -- n=1 is not a measurement. Inherits AGREE's flat constant on the
    # same argument as before: two independent readings corroborating each
    # other, about emptiness rather than about a code.
    # ponytail: unmeasured (n=1). A single wrong observation is weak evidence
    # either way. Re-measure on a sparser benchmark before trusting this at
    # corpus scale -- test_the_unmeasured_classes_are_still_unmeasured flags
    # the moment more data exists.
    BOTH_BLANK: 0.97,
    # Not a fixed number -- see confidence_for. What one surviving reading is
    # worth depends on which arm survived.
    NO_SECOND_OPINION: None,
}

# P(correct | class, band), gemini-3.5-flash-lite-banded vs qwen2.5-vl, same
# 30 cards -- pairing the banded run against qwen for the first time, rather
# than scoring it standalone. Only cells with n >= 10 are included; thinner
# ones fall back to CONFIDENCE_BY_CLASS's flat constant for that class, which
# is the one rule every class follows uniformly (AC3), not a per-cell choice:
#
#   class      band      n      accuracy   -> constant
#   agree      high    1,211      96.9%       0.97
#   agree      medium    104      91.3%       0.91
#   agree      low         2       0.0%       (n<10, falls back to 0.97)
#   disagree   high      332      75.0%       0.75
#   disagree   medium     78      44.9%       0.45
#   disagree   low         8       0.0%       (n<10, falls back to 0.75 --
#                                               0/8 is suggestive, not enough
#                                               to act on)
#   one_blank  high       90      82.2%       0.82
#   one_blank  medium     11      72.7%       0.73
#   one_blank  low        22      13.6%       0.14
#
# disagree/medium (0.45) and one_blank/low (0.14) are the two numbers this
# table earns its keep on: a plain "disagree" field reads as 0.75 regardless
# of how sure Gemini sounded, but a disagreeing field where Gemini also says
# "medium" is barely better than a coin flip, and one_blank/low is worse than
# any flat class constant in this formula.
BAND_ACCURACY_BY_CLASS = {
    (AGREE, "high"): 0.97,
    (AGREE, "medium"): 0.91,
    (DISAGREE, "high"): 0.75,
    (DISAGREE, "medium"): 0.45,
    (ONE_BLANK, "high"): 0.82,
    (ONE_BLANK, "medium"): 0.73,
    (ONE_BLANK, "low"): 0.14,
}

# Coded-field accuracy, harness-scored, from the IT-98 findings doc. Used only
# for NO_SECOND_OPINION: with no second opinion the field has exactly the
# reliability of the one model that read it, which is a measured quantity
# rather than a judgement call.
STANDALONE_ACCURACY = {
    "gemini-3.5-flash": 0.94,
    "gemini-3.5-flash-lite": 0.91,
    "qwen2.5-vl": 0.75,
}

# P(correct | band), unconditioned on class -- gemini-3.5-flash-lite scored
# standalone against ground truth (not paired against qwen), 2026-09-09.
# NO_SECOND_OPINION's own case: with no second opinion there is no agreement
# class to condition on, only the one reading and whatever it says about
# itself.
#
#   band       n      accuracy   -> constant
#   high    1,633       91.7%       0.92
#   medium    193       71.5%       0.72
#   low        33        9.1%       0.09
#
# Overrides STANDALONE_ACCURACY's flat 0.91 for gemini-3.5-flash-lite when a
# band is present: low is a far stronger "do not trust this" than the flat
# constant, or even than DISAGREE's 0.75 -- worth acting on precisely because
# it is more decisive. Banding cost 2.5 points of raw accuracy against the
# unbanded run (91.3% -> 88.8% coded), the exact risk the BANDED_EXTRACTION_
# PROMPT docstring flagged as unmeasured; the separation between bands is
# worth that cost.
NO_SECOND_OPINION_BAND_ACCURACY = {
    "high": 0.92,
    "medium": 0.72,
    # ponytail: n=33. The direction (far below medium and high) is
    # unambiguous; the second decimal is not. Re-measure alongside any future
    # banded run before leaning on this figure at corpus scale.
    "low": 0.09,
}


def confidence_for(
    agreement: str, surviving_model: str | None = None, band: str | None = None
) -> float:
    """This class's confidence, in 0.0-1.0.

    ``surviving_model`` matters only for NO_SECOND_OPINION: it is the arm
    that did answer. ``None`` there means neither arm read the card at all --
    no evidence, so 0.0, the one case where a zero is honest rather than a
    claim that the value is wrong.

    ``band`` is the primary arm's self-reported confidence, when it gave
    one -- only ever from a Gemini variant (BANDED_EXTRACTION_PROMPT), never
    from qwen. For NO_SECOND_OPINION it looks up NO_SECOND_OPINION_BAND_
    ACCURACY (unconditioned on class -- there is no class without a second
    reading); for every other class it looks up BAND_ACCURACY_BY_CLASS,
    keyed on (class, band). Either way, a recognised band overrides the flat
    constant because it is more specific evidence about this exact field. An
    unrecognised or absent band, or a (class, band) pair too thin to measure,
    falls back to the flat constant -- which is also the whole of what
    confidence_for did before band-awareness existed.

    An unrecognised model falls back to the weakest measured arm rather than
    the strongest. Understating routes a good field to review, which is
    recoverable; overstating ships an unchecked one, which is not (NFR-01).

    Raises KeyError on an unknown class. A default here would hand out a number
    that means nothing, which is worse than no number at all.
    """
    if agreement not in CONFIDENCE_BY_CLASS:
        raise KeyError(f"no confidence rule for agreement class {agreement!r}")
    if agreement == NO_SECOND_OPINION:
        if surviving_model is None:
            return 0.0
        if band in NO_SECOND_OPINION_BAND_ACCURACY:
            return NO_SECOND_OPINION_BAND_ACCURACY[band]
        return STANDALONE_ACCURACY.get(
            surviving_model, min(STANDALONE_ACCURACY.values())
        )
    return BAND_ACCURACY_BY_CLASS.get((agreement, band), CONFIDENCE_BY_CLASS[agreement])


def score_fields(
    paired: dict[str, dict[str, str | None]],
    models: dict[str, str],
) -> dict[str, dict[str, object]]:
    """One card's paired fields, priced.

    ``paired`` is what ``dual_extract.compare_fields`` returns; ``models`` is
    the ``{"a": ..., "b": ...}`` block ``pair_cards`` already puts on every
    record.

    ``value`` is arm A's normalised reading -- the one the confidence was
    measured about -- and stays A's **even when A read a blank**. The
    one_blank constant is P(A correct), measured over cases that include A
    correctly reading an empty cell; emitting B's value there would attach a
    number to a reading it was never measured about. Only when A is dead
    entirely does B's reading stand in, and NO_SECOND_OPINION is what says so.

    This is not a resolution policy (IT-86 owns that); it is naming which
    reading the number refers to, because a confidence with no value attached
    says nothing.
    """
    scored: dict[str, dict[str, object]] = {}
    for name, field in paired.items():
        agreement = field["agreement"]
        surviving = None
        value = field["a"]
        if agreement == NO_SECOND_OPINION:
            # The only case where an arm is *dead* rather than merely blank.
            # a_raw is None for both, so the class is what separates them:
            # inside any other class, a None a_raw means A answered the card
            # and omitted this key, which is a real reading of "no code".
            if field["a_raw"] is not None:
                surviving = models.get("a")
                band = field.get("a_band")
            elif field["b_raw"] is not None:
                surviving = models.get("b")
                value = field["b"]
                band = field.get("b_band")
            else:
                band = None
        else:
            # AGREE/DISAGREE/ONE_BLANK/BOTH_BLANK: value is always arm A's
            # reading, so the band that prices it is arm A's self-reported
            # one, when it gave one.
            band = field.get("a_band")
        scored[name] = {
            "value": value,
            "confidence": confidence_for(agreement, surviving, band),
            "source_agreement": agreement,
        }
    return scored


def assert_every_field_scored(
    scored: dict[str, dict[str, object]], expected_fields: int = 62
) -> None:
    """AC1. Raises rather than warns: a field that reaches the Archives with no
    confidence is indistinguishable from one that was checked.

    62 is the C1/C2 card, 98% of the coding cards. 60 is the C3 sheet, which
    D015 gives its own schema -- an assertion hardcoded to 60 fails on every
    real card, which is what this ticket was reopened to correct.
    """
    assert len(scored) == expected_fields, (
        f"expected {expected_fields} scored fields, got {len(scored)}"
    )
    for name, field in scored.items():
        score = field.get("confidence")
        assert isinstance(score, (int, float)) and not isinstance(score, bool), (
            f"{name}: confidence must be numeric, got {score!r}"
        )
        assert 0.0 <= score <= 1.0, f"{name}: confidence {score} is outside 0.0-1.0"

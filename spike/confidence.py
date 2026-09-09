"""Turns an agreement class into a per-field confidence score (IT-99).

FR-10 wants a number on every field and no benchmarked engine produces one, so
IT-98 manufactures the evidence -- two independent readings of every card --
and this module prices it.

**The rule, stated once:** a field's confidence is the measured probability
that the primary arm's reading is correct, given the agreement class it fell
into. One rule for all 62 fields, no per-field tuning (AC3). That is the whole
formula; everything below is where the numbers came from.

Measured 2026-09-09 by replaying the saved arms (gemini-3.5-flash x
qwen2.5-vl, 30 cards, 1,860 comparisons) against the hand-typed sheet --
test_constants_still_match_the_benchmark re-derives them and fails if they
drift. Full working in docs/decisions/D016-agreement-to-confidence.md.

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
- **The self-reported confidence band.** Gemini can optionally say how sure it
  is of a value (``GEMINI_CONFIDENCE_BAND``, IT-98), but no banded run has ever
  been saved -- ``results/`` has no ``-banded`` directory -- so there is no
  data to price it against. The band survives into the paired output as
  ``a_band``/``b_band`` and is simply unused here. Folding it in would mean
  splitting each class three ways (low/medium/high) and measuring nine cells
  instead of five; IT-100 is where that run belongs.
"""

from __future__ import annotations

from dual_extract import AGREE, BOTH_BLANK, DISAGREE, NO_SECOND_OPINION, ONE_BLANK

# P(the primary arm's reading is correct | class), from the 30-card benchmark.
#
#   class              n      measured    -> constant
#   agree           1,333       99.0%        0.99
#   one_blank         121       85.1%        0.85
#   disagree          406       79.1%        0.79
#
# one_blank gets its own constant rather than sharing disagree's: one arm
# omitting a key is weaker evidence against the other arm than a head-on
# contradiction, and the six points between them say so. The IT-98 findings doc
# reports a single 80.5% over both classes merged; splitting them reconciles
# exactly (406*0.791 + 121*0.851 = 424, the doc's count).
#
# Two decimal places, not three. n=30, and the findings doc's own caveat
# applies -- the direction is clear, the second decimal place is not.
CONFIDENCE_BY_CLASS = {
    AGREE: 0.99,
    ONE_BLANK: 0.85,
    DISAGREE: 0.79,
    # Never observed on this benchmark: all 30 cards are dense, 1,834 of 1,860
    # fields carry a code. Inherits agree's constant on the argument that it is
    # the same thing -- two independent readings corroborating each other, about
    # emptiness rather than about a code.
    # ponytail: unmeasured (n=0). Two models both missing a faint code look
    # identical to two models correctly reading an empty cell, and this constant
    # cannot tell them apart. Measure on a sparser sample before trusting it at
    # corpus scale.
    BOTH_BLANK: 0.99,
    # Not a fixed number -- see confidence_for. What one surviving reading is
    # worth depends on which arm survived.
    NO_SECOND_OPINION: None,
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


def confidence_for(agreement: str, surviving_model: str | None = None) -> float:
    """This class's confidence, in 0.0-1.0.

    ``surviving_model`` matters only for NO_SECOND_OPINION, and is the arm that
    did answer. ``None`` there means neither arm read the card at all: no
    evidence, so 0.0 -- the one case where a zero is honest rather than a claim
    that the value is wrong.

    An unrecognised model falls back to the weakest measured arm rather than
    the strongest. Understating routes a good field to review, which is
    recoverable; overstating ships an unchecked one, which is not (NFR-01).

    Raises KeyError on an unknown class. A default here would hand out a number
    that means nothing, which is worse than no number at all.
    """
    if agreement not in CONFIDENCE_BY_CLASS:
        raise KeyError(f"no confidence rule for agreement class {agreement!r}")
    if agreement != NO_SECOND_OPINION:
        return CONFIDENCE_BY_CLASS[agreement]
    if surviving_model is None:
        return 0.0
    return STANDALONE_ACCURACY.get(surviving_model, min(STANDALONE_ACCURACY.values()))

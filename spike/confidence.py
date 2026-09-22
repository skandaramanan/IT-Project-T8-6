"""Turns an agreement class into a per-field confidence score (IT-99).

Rule: a field's confidence is P(primary arm's reading is correct | agreement
class), refined by the primary arm's self-reported band when it gave one.
Same rule for all 62 fields, no per-field tuning (AC3).

Calibrated to gemini-3.5-flash-lite vs qwen2.5-vl (D016). Not done here:
choosing which value wins a disagreement (IT-86), or writing into a D007
record (needs a schema amendment first -- IT-86's call).
"""

from __future__ import annotations

from dual_extract import AGREE, BOTH_BLANK, DISAGREE, NO_SECOND_OPINION, ONE_BLANK

# P(primary arm correct | class). flash-lite vs qwen, 30 cards, 1,860
# comparisons, 2026-09-09. Fallback when no band is attached (see
# BAND_ACCURACY_BY_CLASS for band-conditioned values). Full numbers in D016.
CONFIDENCE_BY_CLASS = {
    AGREE: 0.97,
    ONE_BLANK: 0.74,
    DISAGREE: 0.75,
    # ponytail: n=1, unmeasured. Inherits AGREE's constant; re-measure once
    # there's more data (test_both_blank_is_still_too_thin_to_measure flags it).
    BOTH_BLANK: 0.97,
    NO_SECOND_OPINION: None,  # not fixed -- see confidence_for
}

# P(correct | class, band), same benchmark. Cells with n < 10 are omitted
# and fall back to CONFIDENCE_BY_CLASS. Full table in D016.
BAND_ACCURACY_BY_CLASS = {
    (AGREE, "high"): 0.97,
    (AGREE, "medium"): 0.91,
    (DISAGREE, "high"): 0.75,
    (DISAGREE, "medium"): 0.45,
    (ONE_BLANK, "high"): 0.82,
    (ONE_BLANK, "medium"): 0.73,
    (ONE_BLANK, "low"): 0.14,
}

# Coded-field accuracy per model, harness-scored (IT-98 findings doc). Used
# only for NO_SECOND_OPINION, where there's no agreement class to condition on.
STANDALONE_ACCURACY = {
    "gemini-3.5-flash": 0.94,
    "gemini-3.5-flash-lite": 0.91,
    "qwen2.5-vl": 0.75,
}

# P(correct | band), flash-lite standalone vs ground truth, unconditioned on
# class. Overrides STANDALONE_ACCURACY's flat value when a band is present.
NO_SECOND_OPINION_BAND_ACCURACY = {
    "high": 0.92,
    "medium": 0.72,
    "low": 0.09,  # ponytail: n=33, direction clear, exact value not
}


def confidence_for(
    agreement: str, surviving_model: str | None = None, band: str | None = None
) -> float:
    """This class's confidence, in 0.0-1.0.

    ``surviving_model`` only matters for NO_SECOND_OPINION; ``None`` means
    neither arm read the card, so 0.0. ``band`` overrides the flat constant
    when recognised and measured; an unrecognised model falls back to the
    weakest measured arm (understating is recoverable, overstating isn't).

    Raises KeyError on an unknown class rather than default to a meaningless
    number.
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


def resolve_primary_value(field: dict[str, str | None]) -> str | None:
    """Return the deterministic value selected from one paired field.

    Gemini (arm ``a``) is the primary extractor. Its normalised reading wins
    every normal paired outcome, including a per-field blank. Qwen (arm ``b``)
    is selected only when Gemini did not return a usable result for the entire
    card (``NO_SECOND_OPINION``). This keeps the selected value aligned with
    the benchmarked confidence constants in D016 and the IT-86 policy.
    """
    if field["agreement"] != NO_SECOND_OPINION:
        return field["a"]
    return field["a"] if field["a_raw"] is not None else field["b"]


def score_fields(
    paired: dict[str, dict[str, str | None]],
    models: dict[str, str],
) -> dict[str, dict[str, object]]:
    """One card's paired fields, priced.

    ``value`` is arm A's reading, even when A read blank -- the one_blank
    constant was measured over A-correctly-blank cases too. B's reading only
    stands in when A is dead entirely (NO_SECOND_OPINION, a_raw is None).
    """
    scored: dict[str, dict[str, object]] = {}
    for name, field in paired.items():
        agreement = field["agreement"]
        surviving = None
        value = resolve_primary_value(field)
        if agreement == NO_SECOND_OPINION:
            if field["a_raw"] is not None:
                surviving = models.get("a")
                band = field.get("a_band")
            elif field["b_raw"] is not None:
                surviving = models.get("b")
                band = field.get("b_band")
            else:
                band = None
        else:
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
    """AC1. Raises rather than warns -- an unscored field reaching the
    Archives is indistinguishable from one that was checked.

    62 is the C1/C2 card; C3 (60 fields) gets its own schema per D015.
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

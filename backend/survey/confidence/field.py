"""Turns an agreement class into a per-field confidence score (IT-99).

Rule: a field's confidence is P(primary arm's reading is correct | agreement
class), refined by the primary arm's self-reported band when it gave one.
Same rule for all 62 fields, no per-field tuning (AC3).

Calibrated to D028 unbanded Flash-Lite vs supplied Qwen Q6_K 2MP (IT-125).
D021 selects the primary reading before scoring; survey.merge_runs writes the
result into preserved D007 dataset envelopes.
"""

from __future__ import annotations

from survey.confidence.agreement import (
    AGREE,
    BOTH_BLANK,
    DISAGREE,
    NO_SECOND_OPINION,
    ONE_BLANK,
)

# IT-125: current label aliases, supplied Q6_K / 2MP / rp1.05 raw benchmark,
# paired with the unbanded Flash-Lite benchmark matching D028. Rounded to two
# decimals; exact numerators, denominators and raw hashes are in the reproducible
# docs/runs/it125-calibration.json and D016 Addendum D.
CONFIDENCE_BY_CLASS = {
    AGREE: 0.98,  # 1486 / 1523
    ONE_BLANK: 0.51,  # 18 / 35; three omitted Gemini fields are not blanks
    DISAGREE: 0.64,  # 191 / 299
    # No BOTH_BLANK observations in Q6 pairing. Retain D016's reasoned
    # agreement fallback, explicitly unvalidated for review bypass.
    BOTH_BLANK: 0.98,
    NO_SECOND_OPINION: None,
}

# Saved banded Flash-Lite x Q6 benchmark, with the same current normalisation.
# Only cells with n >= 10 qualify. Other cells use the actual production
# (unbanded) class fallback above; bands are off in the D028 corpus.
BAND_ACCURACY_BY_CLASS = {
    (AGREE, "high"): 0.98,  # 1334 / 1355
    (AGREE, "medium"): 0.89,  # 116 / 131
    (DISAGREE, "high"): 0.62,  # 155 / 251
    (DISAGREE, "medium"): 0.35,  # 22 / 62
    (ONE_BLANK, "high"): 0.33,  # 9 / 27
    (ONE_BLANK, "low"): 0.14,  # 3 / 22
}

# Model names describe the calibrated configuration, not arbitrary Qwen
# quantisations/resolutions. IT-125 uses qwen2.5-vl for the supplied Q6 arm.
STANDALONE_ACCURACY = {
    "gemini-3.5-flash": 0.94,  # retained historical measurement, not used by IT-125
    "gemini-3.5-flash-lite": 0.91,  # 1695 / 1860
    "gemini-3.5-flash-lite-banded": 0.88,  # 1639 / 1860
    "qwen2.5-vl": 0.85,  # Q6_K, 2MP, rp1.05: 1574 / 1860
}

# Band-only evidence applies to the saved Flash-Lite banded configuration,
# never to a different model merely because it supplies a band string.
NO_SECOND_OPINION_BAND_ACCURACY = {
    "high": 0.92,  # 1498 / 1633
    "medium": 0.72,  # 138 / 193
    "low": 0.09,  # 3 / 33
}
BANDED_PRIMARY_MODELS = {"gemini-3.5-flash-lite", "gemini-3.5-flash-lite-banded"}


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
        if (
            surviving_model in BANDED_PRIMARY_MODELS
            and band in NO_SECOND_OPINION_BAND_ACCURACY
        ):
            return NO_SECOND_OPINION_BAND_ACCURACY[band]
        return STANDALONE_ACCURACY.get(
            surviving_model, min(STANDALONE_ACCURACY.values())
        )
    return BAND_ACCURACY_BY_CLASS.get((agreement, band), CONFIDENCE_BY_CLASS[agreement])


def _available(field: dict, arm: str) -> bool:
    """Read explicit whole-arm availability, never infer it from a raw null.

    Old nonfailure paired classes establish that both arms were available.
    Legacy NO_SECOND_OPINION records cannot distinguish a blank/omitted field
    from an unavailable arm: refuse them and require re-pairing the raw inputs.
    """
    key = f"{arm}_available"
    if key in field:
        if not isinstance(field[key], bool):
            raise ValueError(f"{key} must be an explicit boolean")
        return field[key]
    if field["agreement"] != NO_SECOND_OPINION:
        return True
    raise ValueError(
        f"{key} is required for no_second_opinion; re-pair raw inputs "
        "to distinguish an omitted/blank field from an unavailable arm"
    )


def resolve_primary_value(field: dict) -> str | None:
    """D021: retain Gemini even when its individual field is omitted/blank.

    Substitute Qwen only when the entire Gemini arm is unavailable. New paired
    records carry explicit arm availability, because a_raw=None cannot tell a
    deliberate null from an unavailable arm.
    """
    if field["agreement"] != NO_SECOND_OPINION or _available(field, "a"):
        return field["a"]
    return field["b"]


def score_fields(
    paired: dict[str, dict],
    models: dict[str, str],
) -> dict[str, dict[str, object]]:
    """Attach confidence to the actual primary-selected reading.

    An omitted selected field has no reading to calibrate and scores zero.
    An explicit blank is a reading and receives its applicable class/standalone
    confidence. Neither case permits selecting Qwen while Gemini is available.
    """
    scored: dict[str, dict[str, object]] = {}
    for name, field in paired.items():
        agreement = field["agreement"]
        selected = "a" if _available(field, "a") else "b"
        surviving = models.get(selected) if _available(field, selected) else None
        band = field.get(f"{selected}_band")
        state = field.get(f"{selected}_state")
        score = (
            0.0 if state == "omitted" else confidence_for(agreement, surviving, band)
        )
        scored[name] = {
            "value": resolve_primary_value(field),
            "confidence": score,
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

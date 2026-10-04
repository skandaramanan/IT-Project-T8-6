"""How two extractors' readings of one field relate (IT-98).

The five agreement classes and the field-by-field comparison that assigns them.
``survey.confidence.field`` turns a class into a confidence score (D016).
"""

from __future__ import annotations

from survey.extraction.field_schema import FIELD_SCHEMA
from survey.extraction.record import normalise

# Every card emits every schema field so a dropped field shows up as a
# comparison against nothing rather than vanishing (D011).
SCHEMA_FIELD_NAMES = [spec.name for spec in FIELD_SCHEMA]

# NO_SECOND_OPINION is its own class, not folded into AGREE -- collapsing them
# would inflate every downstream confidence number (IT-99 AC4).
AGREE = "agree"
DISAGREE = "disagree"
ONE_BLANK = "one_blank"
BOTH_BLANK = "both_blank"
NO_SECOND_OPINION = "no_second_opinion"


def classify(first: str | None, second: str | None) -> str:
    """The agreement class for one field, given both arms' readings.

    Blankness is judged after normalisation (see ``survey.extraction.record.normalise``).
    Leading zeros are not collapsed -- `04` vs `4` is a real disagreement
    (IT-98 AC2b).
    """
    a, b = normalise(first), normalise(second)
    if not a and not b:
        return BOTH_BLANK
    if not a or not b:
        return ONE_BLANK
    return AGREE if a == b else DISAGREE


def compare_fields(
    first: dict[str, str] | None,
    second: dict[str, str] | None,
    field_names: list[str] | None = None,
    first_bands: dict[str, str] | None = None,
    second_bands: dict[str, str] | None = None,
) -> dict[str, dict[str, str | None]]:
    """One card's fields, paired.

    ``None`` for an arm means it produced nothing usable for this card, so
    every field reads NO_SECOND_OPINION rather than BOTH_BLANK -- a failed
    run isn't the same as two models agreeing the card is empty.

    A band key appears only where the model actually reported one; absent is
    not "low" (IT-99 needs to tell "never asked" from "asked and unsure" apart).
    """
    names = SCHEMA_FIELD_NAMES if field_names is None else field_names
    missing_arm = first is None or second is None
    paired: dict[str, dict[str, str | None]] = {}
    for name in names:
        first_raw = None if first is None else first.get(name)
        second_raw = None if second is None else second.get(name)
        field: dict[str, str | None] = {
            "a": normalise(first_raw),
            "b": normalise(second_raw),
            # What each model literally said, so a reviewer chasing one field
            # doesn't have to re-parse the raw response blob (AC4).
            "a_raw": first_raw,
            "b_raw": second_raw,
            "agreement": NO_SECOND_OPINION
            if missing_arm
            else classify(first_raw, second_raw),
        }
        for key, bands in (("a_band", first_bands), ("b_band", second_bands)):
            if bands and name in bands:
                field[key] = bands[name]
        paired[name] = field
    return paired

"""The survey front's extracted fields as D007 field objects (FR-03)."""

from __future__ import annotations

import re
from typing import Any

from survey.extraction.card_fields import (
    SURVEY_FRONT_COLUMNS,
    SURVEY_FRONT_DWELLING_FIELDS,
    SURVEY_FRONT_PERSON_ROWS,
    SURVEY_FRONT_SCHEMA_BY_NAME,
    survey_front_label,
)
from survey.extraction.record import build_field, build_omitted_field

SOURCE = "survey-front"

# D007's names where it already has one; every other label is snake-cased.
_D007_KEYS = {
    "Dwelling Number (top-left corner)": "dwelling_no",
    "No. of Families in Dwelling": "families_in_dwelling",
}


def record_key(label: str) -> str:
    return _D007_KEYS.get(label) or re.sub(r"\W+", "_", label.lower()).strip("_")


def build_survey_front(fields: dict[str, str]) -> dict[str, Any]:
    """Dwelling fields and persons from one front alone.

    A column with nothing read in it is an unused column, not a person.
    """

    def field(label: str) -> dict[str, Any]:
        if label not in fields:
            return build_omitted_field(source=SOURCE)
        spec = SURVEY_FRONT_SCHEMA_BY_NAME[label]
        return build_field(spec, fields[label], source=SOURCE, struck=None)

    columns = (
        {
            record_key(r): field(survey_front_label(r, n))
            for r in SURVEY_FRONT_PERSON_ROWS
        }
        for n in range(1, SURVEY_FRONT_COLUMNS + 1)
    )
    front: dict[str, Any] = {
        record_key(label): field(label) for label in SURVEY_FRONT_DWELLING_FIELDS
    }
    front["persons"] = [
        p for p in columns if any(f["status"] == "ok" for f in p.values())
    ]
    return front

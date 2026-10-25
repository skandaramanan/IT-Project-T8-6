"""Review descriptors drawn from the established extraction definitions."""

import re
from dataclasses import dataclass, replace

from survey.extraction.card_fields import (
    FIELD_SCHEMA,
    FIELD_SCHEMA_BY_NAME,
    REVERSE_NOTES_SCHEMA,
    SURVEY_FRONT_DWELLING_FIELDS,
    SURVEY_FRONT_SCHEMA_BY_NAME,
    FieldSpec,
)
from survey.extraction.record import FIELD_MAP
from survey.extraction.survey_front import record_key

MAX_TEXT_CORRECTION_LENGTH = 10_000
# Reruns regroup cards by the front's dwelling number, so it follows the
# coding card's rule rather than free text.
DWELLING_NUMBER = r"[0-9]{1,4}[A-Za-z]?"


@dataclass(frozen=True)
class Descriptor:
    spec: FieldSpec
    group: str
    role: str
    accept_only: bool = False

    @property
    def identity_kind(self):
        if self.role != "coding-front":
            return None
        return {
            "Municipality": "municipality",
            "Number of Dwelling": "dwelling",
            "Number of Household": "household",
        }.get(self.spec.name)

    @property
    def front_dwelling_number(self):
        return (
            self.role == "survey-front" and record_key(self.spec.name) == "dwelling_no"
        )

    def valid_correction(self, value):
        if self.identity_kind or self.front_dwelling_number:
            pattern = (
                r"[0-9]{1,2}"
                if self.identity_kind in {"municipality", "household"}
                else DWELLING_NUMBER
            )
            return isinstance(value, str) and bool(re.fullmatch(pattern, value))
        if self.spec.kind == "text":
            return (
                isinstance(value, str)
                and bool(value.strip())
                and len(value) <= MAX_TEXT_CORRECTION_LENGTH
                and "\x00" not in value
            )
        return isinstance(value, str) and bool(re.fullmatch(r"[0-9]{1,64}", value))


def descriptor(pointer: str) -> Descriptor | None:
    if re.fullmatch(r"/dwelling/households/[0-9]+/municipality", pointer):
        return Descriptor(
            FIELD_SCHEMA_BY_NAME["Municipality"], "household", "coding-front"
        )
    normalized = re.sub(r"/households/[0-9]+/", "/households/*/", pointer)
    for label, path, group in field_pointers():
        if normalized == path:
            if group == "front":
                return Descriptor(
                    replace(SURVEY_FRONT_SCHEMA_BY_NAME[label], kind="text")
                    if record_key(label) == "dwelling_no"
                    else SURVEY_FRONT_SCHEMA_BY_NAME[label],
                    group,
                    "survey-front",
                )
            return Descriptor(
                FIELD_SCHEMA_BY_NAME[label],
                group,
                "coding-front",
            )
    if re.fullmatch(r"/dwelling/notes/[0-9]+/text", pointer):
        return Descriptor(REVERSE_NOTES_SCHEMA[0], "notes", "survey-back")
    return None


def field_pointers(index="*", *, household_municipality=False, include_shared=True):
    """Yield labels, pointers and groups for descriptors and review context."""
    for spec in FIELD_SCHEMA:
        label = spec.name
        key, group = FIELD_MAP[label]
        if label == "Municipality" and household_municipality:
            group = "household"
        if group in {"dwelling", "house"} and not include_shared:
            continue
        path = (
            f"/dwelling/{key}"
            if group == "dwelling"
            else f"/dwelling/house/{key}"
            if group == "house"
            else f"/dwelling/households/{index}/{key}"
            if group == "household"
            else f"/dwelling/households/{index}/{group}/{key}"
        )
        yield label, path, group
    for label in SURVEY_FRONT_DWELLING_FIELDS:
        key = record_key(label)
        path = (
            f"/dwelling/{key}"
            if key in {"address", "families_in_dwelling"}
            else f"/dwelling/handwritten/{key}"
        )
        yield label, path, "front"

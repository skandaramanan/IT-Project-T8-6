"""Review descriptors drawn from the established extraction definitions."""

import re
from dataclasses import dataclass

from survey.extraction.card_fields import (
    FIELD_SCHEMA_BY_NAME,
    REVERSE_NOTES_SCHEMA,
    SURVEY_FRONT_DWELLING_FIELDS,
    SURVEY_FRONT_SCHEMA_BY_NAME,
    FieldSpec,
)
from survey.extraction.record import FIELD_MAP
from survey.extraction.survey_front import record_key


@dataclass(frozen=True)
class Descriptor:
    spec: FieldSpec
    group: str
    role: str
    accept_only: bool = False

    def valid_correction(self, value):
        if self.spec.kind == "text":
            return isinstance(value, str) and bool(value.strip())
        return isinstance(value, str) and bool(re.fullmatch(r"[0-9]{1,64}", value))


def descriptor(pointer: str) -> Descriptor | None:
    if re.fullmatch(r"/dwelling/households/[0-9]+/municipality", pointer):
        return Descriptor(
            FIELD_SCHEMA_BY_NAME["Municipality"], "household", "coding-front", True
        )
    for label, (key, group) in FIELD_MAP.items():
        path = (
            f"/dwelling/{key}"
            if group == "dwelling"
            else f"/dwelling/house/{key}"
            if group == "house"
            else f"/dwelling/households/*/{key}"
            if group == "household"
            else f"/dwelling/households/*/{group}/{key}"
        )
        if re.sub(r"/households/[0-9]+/", "/households/*/", pointer) == path:
            return Descriptor(
                FIELD_SCHEMA_BY_NAME[label],
                group,
                "coding-front",
                group in {"dwelling", "household"},
            )
    for label in SURVEY_FRONT_DWELLING_FIELDS:
        key = record_key(label)
        path = (
            f"/dwelling/{key}"
            if key in {"address", "families_in_dwelling"}
            else f"/dwelling/handwritten/{key}"
        )
        if pointer == path:
            return Descriptor(
                SURVEY_FRONT_SCHEMA_BY_NAME[label],
                "front",
                "survey-front",
                key in {"dwelling_no", "municipality", "number"},
            )
    if re.fullmatch(r"/dwelling/notes/[0-9]+/text", pointer):
        return Descriptor(REVERSE_NOTES_SCHEMA[0], "notes", "survey-back")
    return None

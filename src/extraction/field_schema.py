"""The 60 numeric-coding-card fields, typed from the 20-card ground truth.

Derived by cross-referencing every field's *observed* values (all 20 cards)
against code_book.py's tables — not guessed from field names alone. Several
name-obvious guesses turned out wrong once checked against real values (e.g.
"House Kitchen" reaches 9, but code_book's Kitchen category only defines
0–5), so every category link here was confirmed against actual data.

Four kinds:

- ``categorical`` — confirmed: every observed value is a valid code in the
  linked CLOSED_CATEGORIES table.
- ``numeric_sentinel`` — confirmed: an actual sentinel code (e.g. 997) was
  observed, linking it to a SENTINEL_CODES table.
- ``numeric_free`` — a plain count or amount with no code book table.
- ``unknown`` — genuine open question: either no code book coverage exists
  (Family Structure, Overcrowding, Poverty — already flagged as gaps in
  code_book.py), or the field name suggests a category but observed values
  fall outside it (Grade of Occ. of Head, House State of Repair, House
  Kitchen, House No. of Sleepouts) — don't resolve these by guessing, the
  ``notes`` field says what's actually wrong.

3 fields had zero observations in the 20-card sample (Facilities Shared,
House No. of Families O/C. Liv.A/B) — ``kind="no_data"``, unclassifiable
from this sample alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from extraction.code_book import CLOSED_CATEGORIES, SENTINEL_CODES

FieldKind = Literal[
    "categorical", "numeric_sentinel", "numeric_free", "unknown", "no_data"
]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: FieldKind
    code_book_category: str | None = None
    notes: str = ""


FIELD_SCHEMA: list[FieldSpec] = [
    FieldSpec(
        "Municipality",
        "categorical",
        "Municipality",
        "observed values (36, 56) aren't in the code book's 00-32/99 list -- "
        "likely a different/updated municipality scheme; unresolved",
    ),
    FieldSpec(
        "No. of Dwelling",
        "numeric_free",
        notes="record identifier within municipality, not a count",
    ),
    FieldSpec("No. of Households", "numeric_free"),
    FieldSpec("Total Resident Members", "numeric_free"),
    FieldSpec("Number under 5", "numeric_free"),
    FieldSpec("Number 5-10", "numeric_free"),
    FieldSpec("Number over 10 M.", "numeric_free"),
    FieldSpec("Number over 10 F.", "numeric_free"),
    FieldSpec(
        "Dominant Family T.A.I.",
        "numeric_sentinel",
        "Aggregate Household Income - Earnings of Head",
        "997 observed",
    ),
    FieldSpec(
        "Dominant Family Income from S.Letting",
        "numeric_free",
        notes="shillings amount; no sentinel code observed in this sample",
    ),
    FieldSpec(
        "Dominant Family Net Rent of Family",
        "numeric_free",
        notes="shape matches code book's Rent category; no sentinel code (00/01/02) observed",
    ),
    FieldSpec("Dominant Family Rooms Available Shared", "numeric_free"),
    FieldSpec("Dominant Family Rooms Available Unshared", "numeric_free"),
    FieldSpec(
        "Dominant Family Family Structure",
        "unknown",
        notes="no code book coverage found",
    ),
    FieldSpec(
        "Dominant Family Overcrowding", "unknown", notes="no code book coverage found"
    ),
    FieldSpec(
        "Dominant Family Poverty", "unknown", notes="no code book coverage found"
    ),
    FieldSpec(
        "Rent of House",
        "numeric_free",
        notes="shape matches Rent category; no sentinel observed",
    ),
    FieldSpec(
        "Grade of Occ. of Head",
        "unknown",
        notes="name suggests code book's Grade of Occupation of Head (0-4,9) but observed "
        "values include 5,6,8 -- likely a different per-family scale not in this excerpt",
    ),
    FieldSpec(
        "Family 2 Tenure",
        "categorical",
        "Tenure",
        notes="one outlier value '66' observed -- likely a transcription anomaly",
    ),
    FieldSpec(
        "Family 2 T.A.I.",
        "numeric_sentinel",
        "Aggregate Household Income - Earnings of Head",
        "997 observed",
    ),
    FieldSpec("Family 2 Rent", "numeric_free"),
    FieldSpec("Family 2 Rooms Available Shared", "numeric_free"),
    FieldSpec("Family 2 Rooms Available Unshared", "numeric_free"),
    FieldSpec(
        "Family 2 Family Structure", "unknown", notes="no code book coverage found"
    ),
    FieldSpec("Family 2 Overcrowding", "unknown", notes="no code book coverage found"),
    FieldSpec("Family 2 Poverty", "unknown", notes="no code book coverage found"),
    FieldSpec(
        "Family 2 Grade of Occ. of Head",
        "unknown",
        notes="same Grade-of-Occ ambiguity as the dominant family field",
    ),
    FieldSpec("Family 3 Tenure", "categorical", "Tenure"),
    FieldSpec(
        "Family 3 T.A.I.",
        "numeric_sentinel",
        "Aggregate Household Income - Earnings of Head",
        "997 observed",
    ),
    FieldSpec("Family 3 Rent", "numeric_free"),
    FieldSpec("Family 3 Rooms Available Shared", "numeric_free"),
    FieldSpec("Family 3 Rooms Available Unshared", "numeric_free"),
    FieldSpec(
        "Family 3 Family Structure", "unknown", notes="no code book coverage found"
    ),
    FieldSpec("Family 3 Overcrowding", "unknown", notes="no code book coverage found"),
    FieldSpec("Family 3 Poverty", "unknown", notes="no code book coverage found"),
    FieldSpec(
        "House Type of Dwelling", "categorical", "Type of Dwelling and No. of Storeys"
    ),
    FieldSpec("House Structural Material", "categorical", "Structural Material"),
    FieldSpec(
        "House Age of House",
        "numeric_free",
        notes="shape matches Probable Age's sentinel scheme; no sentinel code observed in this sample",
    ),
    FieldSpec("House Garden", "categorical", "Garden and Yard"),
    FieldSpec(
        "House State of Repair",
        "unknown",
        notes="name suggests code book's Repairs (0-5) but observed value '6' is out of range",
    ),
    FieldSpec("House Tenure of Main Family", "categorical", "Tenure"),
    FieldSpec(
        "Grade of Occup. of Fam.3",
        "unknown",
        notes="same Grade-of-Occ ambiguity as the dominant family field",
    ),
    FieldSpec("Facilities Shared", "no_data", notes="0/20 filled in this sample"),
    FieldSpec(
        "Total No. of Rooms",
        "numeric_free",
        notes="code book's Total Number rule ('0 for over 11') doesn't match observed value '16' appearing literally",
    ),
    FieldSpec("Family 4 Tenure", "categorical", "Tenure"),
    FieldSpec(
        "Family 4 T.A.I.",
        "numeric_sentinel",
        "Aggregate Household Income - Earnings of Head",
        "997 observed",
    ),
    FieldSpec(
        "House No. of Sleepouts",
        "unknown",
        notes="name suggests code book's Sleepouts (0-4) but observed values 5,6 are out of range "
        "-- likely a literal count despite the name",
    ),
    FieldSpec("House Bathroom", "categorical", "Bathroom"),
    FieldSpec("House W.C.", "categorical", "W.C."),
    FieldSpec(
        "House Washouse",
        "numeric_free",
        notes="no confirmed code book link despite similarity to Washing Facilities",
    ),
    FieldSpec(
        "House Kitchen",
        "unknown",
        notes="name suggests code book's Kitchen (0-5) but observed values 6-9 are out of range "
        "-- likely a literal count despite the name",
    ),
    FieldSpec("Family 4 Rent", "numeric_free"),
    FieldSpec("Family 4 Rooms Available Shared", "numeric_free"),
    FieldSpec("Family 4 Rooms Available Unshared", "numeric_free"),
    FieldSpec(
        "Family 4 Family Structure", "unknown", notes="no code book coverage found"
    ),
    FieldSpec("Family 4 Overcrowding", "unknown", notes="no code book coverage found"),
    FieldSpec("Family 4 Poverty", "unknown", notes="no code book coverage found"),
    FieldSpec(
        "Family 4 Grade of Occ. of Head",
        "unknown",
        notes="same Grade-of-Occ ambiguity as the dominant family field",
    ),
    FieldSpec(
        "House No. of Families O/C. (Liv.B)",
        "no_data",
        notes="0/20 filled in this sample",
    ),
    FieldSpec(
        "House No. of Families O/C. (Liv.A)",
        "no_data",
        notes="0/20 filled in this sample",
    ),
]

FIELD_SCHEMA_BY_NAME: dict[str, FieldSpec] = {spec.name: spec for spec in FIELD_SCHEMA}


def describe_field(spec: FieldSpec) -> str:
    """One line per field, for embedding in a VLM extraction prompt."""
    if spec.kind == "categorical" and spec.code_book_category:
        codes = CLOSED_CATEGORIES[spec.code_book_category]
        options = "; ".join(f"{code}={label}" for code, label in codes.items())
        return f"{spec.name}: code, one of [{options}]"
    if spec.kind == "numeric_sentinel" and spec.code_book_category:
        sentinels = SENTINEL_CODES[spec.code_book_category]
        options = "; ".join(f"{code}={label}" for code, label in sentinels.items())
        return (
            f"{spec.name}: numeric amount, OR one of these special codes: [{options}]"
        )
    if spec.kind == "numeric_free":
        return f"{spec.name}: numeric value (count or amount)"
    # unknown / no_data: genuinely uncertain -- say so rather than imply a scheme that isn't confirmed
    return f"{spec.name}: code or numeric value, exact coding scheme not confirmed"


def build_extraction_prompt_schema() -> str:
    """All 60 fields as a prompt-ready block, one per line, in card order.

    A VLM extractor asks for a JSON object with exactly these keys -- see
    describe_field() for what each line tells the model about valid values.
    """
    return "\n".join(describe_field(spec) for spec in FIELD_SCHEMA)

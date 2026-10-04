"""The coding-card fields, typed from the hand-transcribed ground truth.

Two schemas, because there are two coding cards and they share almost nothing:

- ``FIELD_SCHEMA`` — **C1/C2, 62 fields.** IT-73's structure spike measured C1
  at 67% and C2 at 31% of all coding cards, so this is the FR-01 extraction
  target and the default everything here uses. C2 adds ``No. of Family
  Boarders`` and prints two labels over two lines where C1 fits them on one;
  the recorded field set is otherwise identical, so one schema covers both.
- ``C3_FIELD_SCHEMA`` — **the multi-family punch-card sheet, 60 fields.** 4
  pages in one unit, ~2% of coding cards, and it shares 0 of 62 printed labels
  with C1/C2. Kept because C3 is still a real card type (D009), not because it
  is interchangeable.

Both are derived the same way, and the method matters more than the result:
match each field to the code-book table it is *named after*, then check that
every value observed across the whole ground-truth sheet falls inside that
table. Set-containment on its own proves nothing — a field observing {0,1,2}
sits inside a dozen tables — and name-matching on its own is how you get a
schema that tells a model to emit codes the cards never carry.

Four kinds:

- ``categorical`` — confirmed: the named table exists and every observed value
  is a valid code in it.
- ``numeric_sentinel`` — confirmed: an actual sentinel (997, 98, 99 …) was
  observed, linking the field to a SENTINEL_CODES table. FR-08 makes these
  Must-keep-distinct, so they have to be named in the extraction prompt or a
  model reads 997 as an income of nine hundred and ninety-seven.
- ``numeric_free`` — a plain count or amount with no code book table.
- ``unknown`` — a genuine open question. Either no code book coverage exists,
  or a named table exists and the observed values fall outside it. Recorded
  with the evidence rather than resolved by guessing; ``notes`` says what is
  actually wrong.

``FieldKind`` describes the expected type or shape of a source field.
``FieldStatus`` describes the result of extracting an individual field. They
are independent vocabularies: an ``unknown`` kind may still be extracted
successfully, and a known kind may have no source value.

Two things the C1/C2 sheet settled that the C3 sample had got wrong, both
because C3 is one unit and one unit is not the archive:

- ``Municipality`` — C3 observed 36 and 56, outside the code book's 00–32/99
  list, and was recorded as unresolved. All 30 C1/C2 cards are in range. The
  code book is fine; unit 216463 uses a different scheme.
- ``Grade of Occup. of H.`` — C3 observed 5, 6, 8 and was left ``unknown``.
  C1/C2 observes only 0, 1, 2, 9, all valid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from extraction.code_book import CLOSED_CATEGORIES, SENTINEL_CODES

FieldKind = Literal["categorical", "numeric_sentinel", "numeric_free", "unknown"]

FieldStatus = Literal["ok", "no_data", "illegible", "damaged", "omitted"]

FIELD_STATUS_DEFINITIONS: dict[FieldStatus, str] = {
    "ok": "The field was read successfully and contains a usable value.",
    "no_data": "The source field is present but contains no value to extract.",
    "illegible": "The source field contains markings that cannot be read reliably.",
    "damaged": "The source field cannot be read because its source area is damaged or obscured.",
    "omitted": "The expected field was not returned by the extractor.",
}


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: FieldKind
    code_book_category: str | None = None
    notes: str = ""


# --- C1/C2: the primary extraction target (FR-01) ---------------------------
# In card reading order: left column top to bottom, then middle, then right.
# "observed" counts below are over all 30 benchmark cards.

FIELD_SCHEMA: list[FieldSpec] = [
    # --- left column ---
    FieldSpec("Municipality", "categorical", "Municipality"),
    FieldSpec(
        "Number of Dwelling",
        "numeric_free",
        notes="record identifier within municipality, not a count",
    ),
    FieldSpec(
        "Number of Household",
        "numeric_free",
        notes="every card in this sample is 1; multi-household dwellings exist "
        "on C3 but were not sampled here",
    ),
    FieldSpec("Type of Family", "categorical", "Type of Family"),
    FieldSpec("Total No. Resident Members", "numeric_free"),
    FieldSpec("Number under 5", "numeric_free"),
    FieldSpec("Number 5-10", "numeric_free"),
    FieldSpec("Number over 10 M.", "numeric_free"),
    FieldSpec("Number over 10 F.", "numeric_free"),
    FieldSpec(
        "Military Service",
        "categorical",
        "Relation to Present Head of Persons on Military Service",
    ),
    FieldSpec("No. of Boarders", "numeric_free"),
    FieldSpec(
        "No. of Family Boarders",
        "numeric_free",
        notes="C2 only -- absent from the C1 card entirely, so blank on 26 of 30 "
        "rows. Observed 0 on all 4 C2 cards that carry it, and struck through on "
        "the card in most cases (FR-06 / IT-80)",
    ),
    FieldSpec("No. of Participating Members", "numeric_free"),
    FieldSpec("No. of Adult M. Breadwinners", "numeric_free"),
    FieldSpec("No. of Adult F. Breadwinners", "numeric_free"),
    FieldSpec("No. of Juvenile Breadwinners (under 21)", "numeric_free"),
    FieldSpec("Children under 14", "numeric_free"),
    FieldSpec("Retired and Indep. Persons", "numeric_free"),
    FieldSpec("Home Duties", "numeric_free"),
    FieldSpec("Other", "numeric_free"),
    # --- middle column ---
    FieldSpec(
        "Normal Household I.",
        "numeric_sentinel",
        "Aggregate Household Income - Earnings of Head",
        "all three sentinels observed (997, 998, 999)",
    ),
    FieldSpec("Weekly Rent", "numeric_sentinel", "Rent", "02 observed"),
    FieldSpec(
        "Total Available I.",
        "numeric_sentinel",
        "Aggregate Household Income - Earnings of Head",
        "all three sentinels observed (997, 998, 999)",
    ),
    FieldSpec(
        "Earnings of Head",
        "numeric_sentinel",
        "Aggregate Household Income - Earnings of Head",
        "all three sentinels observed (997, 998, 999)",
    ),
    FieldSpec(
        "Head's Unearned I.",
        "numeric_sentinel",
        "Amount of Unearned Income of Head",
        "00 and 01 observed; 99 also appears and is not in this table -- reads "
        "like a not-known code the excerpt doesn't cover",
    ),
    FieldSpec(
        "Main Source of Head's Unearned I.",
        "categorical",
        "Main Source of Income of Head Other Than Earnings",
    ),
    FieldSpec(
        "Subsidiary Source of Head's I.",
        "unknown",
        notes="shares Main Source's single-digit shape and observes 0, 5, 7 -- "
        "but also 50, which no single-digit source code explains. Not linked "
        "until that value is accounted for",
    ),
    FieldSpec(
        "Industry of H.",
        "unknown",
        notes="3-digit external industry classification (000-802 observed); the "
        "code book excerpt does not cover it, so it can never be validated here",
    ),
    FieldSpec(
        "Occupation of H.",
        "unknown",
        notes="4-digit external occupation classification (0000-5550 observed); "
        "same gap as Industry of H.",
    ),
    FieldSpec("Grade of Occup. of H.", "categorical", "Grade of Occupation of Head"),
    FieldSpec(
        "Place of Work",
        "unknown",
        notes="two-digit, shaped exactly like Municipality (02-31 observed) but "
        "with no table of its own; 99 also appears and reads as not-known",
    ),
    FieldSpec("Age of Head", "numeric_sentinel", "Age of Head", "00 observed"),
    FieldSpec("Sex of Head", "categorical", "Sex of Head"),
    FieldSpec("Regularity of Work", "categorical", "Regularity of Work"),
    FieldSpec("Pre-War Occupation", "categorical", "Pre-War Occupation"),
    FieldSpec(
        "Removal",
        "unknown",
        notes="observed 0, 1, 3, 4, 5 -- a small closed-looking code set, but the "
        "code book excerpt defines no Removal table",
    ),
    FieldSpec("Type of Dwelling", "categorical", "Type of Dwelling and No. of Storeys"),
    FieldSpec("Structural Material", "categorical", "Structural Material"),
    FieldSpec(
        "Age of House",
        "numeric_sentinel",
        "Probable Age",
        "98 observed, which is Probable Age's sentinel scheme -- the C3 sample "
        "saw none and could only note the resemblance",
    ),
    FieldSpec("Garden", "categorical", "Garden and Yard"),
    FieldSpec("State of Repair", "categorical", "Repairs"),
    FieldSpec("Tenure", "categorical", "Tenure"),
    # --- right column ---
    FieldSpec(
        "Length of Residence",
        "numeric_sentinel",
        "Length of Residence",
        "00 and 99 both observed",
    ),
    FieldSpec("Total Number of Rooms", "numeric_free"),
    FieldSpec("Number of Bedrooms", "numeric_free"),
    FieldSpec("Number of Living Rooms", "numeric_free"),
    FieldSpec(
        "Whether used as Bedrooms",
        "unknown",
        notes="conflict: the code book's Whether Used as Bedrooms table defines "
        "5-8, and all 30 cards observe 0 -- not one value in range. Either the "
        "excerpt is wrong for this field or the field records something else. "
        "Left unresolved rather than guessed",
    ),
    FieldSpec("Rooms not in Daily Use", "numeric_free"),
    FieldSpec("Number of Sleepouts", "categorical", "Sleepouts"),
    FieldSpec("Bathroom", "categorical", "Bathroom"),
    FieldSpec("W.C.", "categorical", "W.C."),
    FieldSpec("Washouse", "categorical", "Washing Facilities"),
    FieldSpec("Kitchen", "categorical", "Kitchen"),
    FieldSpec("Sink and Water Service", "categorical", "Water Supply"),
    FieldSpec("Cooking Facilities", "categorical", "Cooking Facilities"),
    FieldSpec(
        "Food Storage",
        "unknown",
        notes="conflict: the code book's Food Storage table defines 0-7 and one "
        "card observes 8 (216420_p0448, a hand-verified reading). 29 of 30 fit, "
        "so this is one out-of-range code rather than a wrong link -- but the "
        "excerpt doesn't explain it, so it isn't claimed as categorical",
    ),
    FieldSpec("Rooms Shared", "categorical", "Shared"),
    FieldSpec("Persons Sharing", "categorical", "Shared"),
    FieldSpec("Children other than those at home", "numeric_free"),
    FieldSpec("Children of H. or wife: Living", "numeric_free"),
    FieldSpec("Children of H. or wife: Dead", "numeric_free"),
    FieldSpec(
        "Children of H. or wife: Total",
        "numeric_free",
        notes="Living + Dead; the identity holds on all 30 cards and is one of "
        "the checks used to catch a slipped row during transcription",
    ),
]


# --- C3: the multi-family punch-card sheet ----------------------------------
# Derived from the 20-card C3 ground truth. Several entries stay ``unknown``
# because that sample is one unit; where the C1/C2 sheet later settled the
# same question, the module docstring says so.

C3_FIELD_SCHEMA: list[FieldSpec] = [
    FieldSpec(
        "Municipality",
        "categorical",
        "Municipality",
        "observed values (36, 56) aren't in the code book's 00-32/99 list -- "
        "unit 216463 uses a different scheme; C1/C2 is fully in range",
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
    FieldSpec("Facilities Shared", "unknown", notes="0/20 filled in this sample"),
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
        "unknown",
        notes="0/20 filled in this sample",
    ),
    FieldSpec(
        "House No. of Families O/C. (Liv.A)",
        "unknown",
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
    # unknown: genuinely uncertain -- say so rather than imply a scheme that isn't confirmed
    return f"{spec.name}: code or numeric value, exact coding scheme not confirmed"


def build_extraction_prompt_schema(
    schema: list[FieldSpec] | None = None,
) -> str:
    """All fields as a prompt-ready block, one per line, in card order.

    Defaults to the C1/C2 card. A VLM extractor asks for a JSON object with
    exactly these keys -- see describe_field() for what each line tells the
    model about valid values. Pass ``C3_FIELD_SCHEMA`` for the punch-card sheet.
    """
    if schema is None:
        schema = FIELD_SCHEMA
    return "\n".join(describe_field(spec) for spec in schema)

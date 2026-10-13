"""Turns a model's raw reading of one coding card into a D007 output record.

The extractor hands back ``{card label: whatever the model saw}``. D007 wants
dwelling -> household, every leaf a field object carrying value, code, label,
status and confidence. This is the piece in between, and it is the only place
that knows both vocabularies.

The three choices it makes -- cleaning on the way in, what ``status`` means,
and which group each field lands in -- are recorded in
``docs/decisions/D011-card-to-record-mapping.md``.

Three things happen here, in order:

1. **Clean.** The model's string is not the card's value: leader dots come back
   as part of the number and handwritten 0/1 come back as letters. Same rules
   as ``benchmark/scoring.py``, which measured them at 305 of 731 apparent
   mismatches on the 2026-09-01 Azure run. They belong on the way in, not only
   at scoring time -- otherwise the benchmark is clean and the dataset is not.

2. **Decode.** A code book code becomes a code plus its meaning (FR-07).
   Sentinels stay ordinary values with a label -- 999 is "over £10", never
   missing (FR-08).

3. **Place.** Each of the 62 fields goes to one of four groups. The card is one
   flat grid; the record is nested, and nothing on the card says which level a
   field belongs to.

Deliberately not done here:

- ``confidence`` is always None. No engine benchmarked so far produces a
  per-field score, and inventing one would breach NFR-01. Null is what the
  envelope asks for and what the reviewer needs to see.
- ``negated`` resolution rule is in ``build_field``, decided in
  ``docs/decisions/D023-resolving-struck-options.md``.
- ``persons`` stay empty. They come off the survey front, and the coding card
  carries none; ``association/records.py`` adds them. The dwelling's
  ``notes`` come off the survey back, in ``association/notes.py``.
"""

from __future__ import annotations

from typing import Any

from survey.extraction.card_fields import FIELD_SCHEMA_BY_NAME, FieldSpec
from survey.extraction.code_book import CLOSED_CATEGORIES, SENTINEL_CODES, decode

SCHEMA_VERSION = "0.3.0"

# --- 1. where each field lives ----------------------------------------------
# card label -> (key in the record, which group)
#
# Groups match the envelope: "dwelling" and "household" are its fixed named
# properties; "house" describes the building, "head" the head of household,
# "counts" the demographic aggregates, "coding" everything else about this
# household. Address, families-in-dwelling and the person grid are absent
# because they live on the survey front, not this card.

FIELD_MAP: dict[str, tuple[str, str]] = {
    # identity
    "Municipality": ("municipality", "dwelling"),
    "Number of Dwelling": ("dwelling_no", "dwelling"),
    "Number of Household": ("household_no", "household"),
    # the building
    "Type of Dwelling": ("type_of_dwelling", "house"),
    "Structural Material": ("structural_material", "house"),
    "Age of House": ("age_of_house", "house"),
    "Garden": ("garden", "house"),
    "State of Repair": ("state_of_repair", "house"),
    "Total Number of Rooms": ("total_number_of_rooms", "house"),
    "Number of Bedrooms": ("number_of_bedrooms", "house"),
    "Number of Living Rooms": ("number_of_living_rooms", "house"),
    "Whether used as Bedrooms": ("whether_used_as_bedrooms", "house"),
    "Rooms not in Daily Use": ("rooms_not_in_daily_use", "house"),
    "Number of Sleepouts": ("number_of_sleepouts", "house"),
    "Bathroom": ("bathroom", "house"),
    "W.C.": ("wc", "house"),
    "Washouse": ("washouse", "house"),
    "Kitchen": ("kitchen", "house"),
    "Sink and Water Service": ("sink_and_water_service", "house"),
    "Cooking Facilities": ("cooking_facilities", "house"),
    "Food Storage": ("food_storage", "house"),
    "Rooms Shared": ("rooms_shared", "house"),
    "Persons Sharing": ("persons_sharing", "house"),
    # the head of household
    "Earnings of Head": ("earnings_of_head", "head"),
    "Head's Unearned I.": ("head_unearned_income", "head"),
    "Main Source of Head's Unearned I.": ("main_source_unearned_income", "head"),
    "Subsidiary Source of Head's I.": ("subsidiary_source_of_income", "head"),
    "Industry of H.": ("industry_of_head", "head"),
    "Occupation of H.": ("occupation_of_head", "head"),
    "Grade of Occup. of H.": ("grade_of_occupation", "head"),
    "Place of Work": ("place_of_work", "head"),
    "Age of Head": ("age_of_head", "head"),
    "Sex of Head": ("sex_of_head", "head"),
    "Regularity of Work": ("regularity_of_work", "head"),
    "Pre-War Occupation": ("pre_war_occupation", "head"),
    # counts of people
    "Total No. Resident Members": ("total_resident_members", "counts"),
    "Number under 5": ("number_under_5", "counts"),
    "Number 5-10": ("number_5_to_10", "counts"),
    "Number over 10 M.": ("number_over_10_m", "counts"),
    "Number over 10 F.": ("number_over_10_f", "counts"),
    "No. of Boarders": ("number_of_boarders", "counts"),
    "No. of Family Boarders": ("number_of_family_boarders", "counts"),
    "No. of Participating Members": ("number_of_participating_members", "counts"),
    "No. of Adult M. Breadwinners": ("adult_m_breadwinners", "counts"),
    "No. of Adult F. Breadwinners": ("adult_f_breadwinners", "counts"),
    "No. of Juvenile Breadwinners (under 21)": ("juvenile_breadwinners", "counts"),
    "Children under 14": ("children_under_14", "counts"),
    "Retired and Indep. Persons": ("retired_and_independent_persons", "counts"),
    "Home Duties": ("home_duties", "counts"),
    "Other": ("other_persons", "counts"),
    "Children other than those at home": ("children_other_than_at_home", "counts"),
    "Children of H. or wife: Living": ("children_living", "counts"),
    "Children of H. or wife: Dead": ("children_dead", "counts"),
    "Children of H. or wife: Total": ("children_total", "counts"),
    # everything else about this household
    "Type of Family": ("type_of_family", "coding"),
    "Military Service": ("military_service", "coding"),
    "Normal Household I.": ("normal_household_income", "coding"),
    "Weekly Rent": ("weekly_rent", "coding"),
    "Total Available I.": ("total_available_income", "coding"),
    "Removal": ("removal", "coding"),
    "Tenure": ("tenure", "coding"),
    "Length of Residence": ("length_of_residence", "coding"),
}

# The groups holding the three fields record_id is built from. They carry a
# source, and they are never negated.
IDENTITY_GROUPS = frozenset({"dwelling", "household"})


# --- 2. cleaning ------------------------------------------------------------
# Three ways of writing "this cell holds no numeric code", which all have to
# compare equal:
#   ""  the transcriber left it blank      (page 203's empty Family 4 block)
#   "-" the transcriber marked it          (page 169's empty Family 3 block)
#   "B" the 1940s coder voided the cell on the card itself, one B per code
#       column -- so "B", "BB", "BBB". The transcriber wrote those as "-", but
#       an extractor reading the card faithfully reports the B it can see.
# Scoring these against each other measures transcription punctuation, not
# extraction. 247 of 1200 ground-truth fields are "-" or "--"; no ground-truth
# value is ever a "B", so treating a returned B as no-value can't hand out
# credit for a real code -- a B where the card holds a digit still mismatches
# that digit.
VOID_MARKS = frozenset("-Bb")

# Every value on this card is a number: the code book defines no code containing
# a letter or a period. That is what makes the two substitutions below safe --
# neither can turn one valid code into a different valid code, so neither can
# hand out credit for a wrong answer. Both were measured on the first Azure run
# (2026-09-01, 20 held-out cards), where together they accounted for 305 of 731
# apparent mismatches -- 25 accuracy points of pure scoring artefact.

# The printed fields are joined to their values by a row of dots, and OCR reads
# some of them as part of the number: "1." for 1, "1.5." for 15. Colons come off
# the "Children of H. or wife:" heading the same way.
_PUNCTUATION = str.maketrans("", "", ".:;, \t\n")

# Handwritten 0 and 1 are read as letters: O 29x, Q 16x, ! 14x, L 6x, I 3x.
# Deliberately not included: "/" and "D", which are plausible lookalikes but
# were never observed -- an unobserved mapping is a guess, and a guess here
# only ever inflates the score.
_DIGIT_LOOKALIKES = str.maketrans(
    {"O": "0", "o": "0", "Q": "0", "I": "1", "l": "1", "L": "1", "!": "1", "|": "1"}
)


def normalise(value: str | None) -> str:
    """Strip print/OCR artefacts. Leading zeros are left alone.

    Zeros are deliberately kept: the ground-truth sheet is text-formatted so
    "04" and "4" are two different transcriptions, and the code book's
    fixed-width codes make them two different codes. Stripping them would hand
    an extractor credit for reading "4" off a cell that says "04" --
    test_leading_zero_is_not_the_same_code guards it. That is the difference
    between the two rules here and that one: "04" and "4" are both valid codes
    with different meanings, whereas "1." and "O" are not codes at all.

    Public because benchmark scoring and the IT-98 agreement check
    (``survey.confidence.agreement``) both use this one function. Two
    definitions of "the same value" would let a pair of readings count as
    agreeing while scoring as a mismatch.
    """
    if value is None:
        return ""
    stripped = value.strip().translate(_PUNCTUATION)
    # all-void-marks (or empty) means no code, however it was written. Checked
    # before folding so a coder's "B" stays a void mark rather than a digit.
    if set(stripped) <= VOID_MARKS:
        return ""
    return stripped.translate(_DIGIT_LOOKALIKES)


def clean_text(value: str | None) -> str:
    """Handwriting is kept as written. A cell holding only dashes, dots,
    underscores or spaces is blank."""
    text = (value or "").strip()
    return "" if set(text) <= set("-–—_ .") else text


# --- 3. one field -----------------------------------------------------------


def build_field(
    spec: FieldSpec,
    raw: str | None,
    *,
    source: str | None = None,
    struck: bool | None = False,
) -> dict[str, Any]:
    """One card value as a D007 field object.

    A value the code book cannot explain keeps its ``ok`` status and its value,
    but its label stays null. Calling it ``no_data`` would say the cell was
    empty, which is a different and false claim.

    A null label only means "unexplained" on a ``categorical`` field, where
    every valid code has a meaning -- that is the FR-09/FR-11 review signal. On
    a ``numeric_sentinel`` field most values are ordinary amounts and carry no
    label by design: Weekly Rent 04 is four shillings, not an unknown code.

    ``struck`` resolution (D023): struck always negates, regardless of whether
    the struck digit is still legible.

    ``struck=None`` means no detector ran -- the engine cannot produce the
    signal at all. The field then carries no ``negated`` key, because ``false``
    would claim the option was read and found unstruck. Same distinction
    ``ExtractionResult.struck`` draws between ``None`` and ``{}``, and the same
    one :func:`build_omitted_field` makes below.
    """
    # Struck empties the value first, so every check below reads off `value`
    # alone rather than re-deriving the rule.
    clean = clean_text if spec.kind == "text" else normalise
    value = "" if struck else clean(raw)
    field: dict[str, Any] = {
        "value": value or None,
        "code": None,
        "label": None,
        "status": "ok" if value else "no_data",
        "confidence": None,  # no benchmarked engine produces one (NFR-01)
    }
    if struck is not None:
        field["negated"] = struck
    if source:
        field["source"] = source
    if not value:
        return field

    category = spec.code_book_category
    if category and (category in CLOSED_CATEGORIES or category in SENTINEL_CODES):
        field["code"] = value
        field["label"] = decode(category, value)
    return field


def build_omitted_field(*, source: str | None = None) -> dict[str, Any]:
    """A field the extractor did not return at all.

    This is deliberately separate from :func:`build_field`: a blank or voided
    value returned by the extractor is ``no_data``; an absent key is
    ``omitted``.  Keeping the distinction here prevents record construction
    from erasing the extractor-completeness signal required by FR-09.

    No ``negated`` key, deliberately: detection never ran on a field the
    extractor did not return, so ``false`` would claim it was read and found
    unstruck. The key is optional in D007 and its absence says "not known".
    """
    field: dict[str, Any] = {
        "value": None,
        "code": None,
        "label": None,
        "status": "omitted",
        "confidence": None,
    }
    if source:
        field["source"] = source
    return field


# --- 4. the record ----------------------------------------------------------


def build_record_id(municipality: str, dwelling_no: str, household_no: str) -> str:
    """Dwelling number alone repeats across municipalities, so identity is the
    three of them together, zero padded: 27-0006-01."""
    missing = [
        name
        for name, value in (
            ("Municipality", municipality),
            ("Number of Dwelling", dwelling_no),
            ("Number of Household", household_no),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"cannot build record_id without {', '.join(missing)}")
    return f"{municipality:0>2}-{dwelling_no:0>4}-{household_no:0>2}"


def build_record(
    fields: dict[str, str],
    *,
    region: str,
    batch: str | None = None,
    image: str | None = None,
    page: int | None = None,
    struck: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """A record from one coding card's extracted fields.

    ``fields`` is keyed by card label -- ``ExtractionResult.fields`` as it comes
    off any Extractor. Keys the card does not have are ignored; fields the model
    did not return are still emitted, as ``omitted``. A card is 62 fields either
    way, so a dropped one is visible rather than absent.

    ``struck`` is ``ExtractionResult.struck`` -- only the fields detection
    flagged are present (D023).
    """
    groups: dict[str, dict[str, Any]] = {
        "dwelling": {},
        "household": {},
        "house": {},
        "head": {},
        "counts": {},
        "coding": {},
    }
    # `struck is None` and `struck == {}` are different claims and stay that
    # way: None is an engine that cannot detect strikes at all, {} is one that
    # looked and found none. Collapsing them would make every field of a
    # no-detector run assert it was read and found unstruck.
    detection_ran = struck is not None
    for label, (key, group) in FIELD_MAP.items():
        spec = FIELD_SCHEMA_BY_NAME[label]
        is_identity = group in IDENTITY_GROUPS
        # Identity is what a value is traced back by, so it carries its source.
        source = "coding-front" if is_identity else None
        if label not in fields:
            # A field the extractor never returned cannot have been struck.
            groups[group][key] = build_omitted_field(source=source)
            continue
        groups[group][key] = build_field(
            spec,
            fields[label],
            source=source,
            # Identity is never negated: record_id needs a value, and FR-06
            # negation was never meant to apply to identity fields.
            struck=(
                not is_identity and struck.get(label, False) if detection_ran else None
            ),
        )

    record_id = build_record_id(
        groups["dwelling"]["municipality"]["value"] or "",
        groups["dwelling"]["dwelling_no"]["value"] or "",
        groups["household"]["household_no"]["value"] or "",
    )

    household: dict[str, Any] = {
        "record_id": record_id,
        "household_no": groups["household"]["household_no"],
        "head": groups["head"],
        "counts": groups["counts"],
        "coding": groups["coding"],
        "cards": [
            {
                "role": "coding-front",
                "image": image or "",
                "page": page,
                "confidence": None,
            }
        ]
        if image
        else [],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "region": region,
        "batch": batch,
        "dwelling": {
            "municipality": groups["dwelling"]["municipality"],
            "dwelling_no": groups["dwelling"]["dwelling_no"],
            "house": groups["house"],
            "households": [household],
        },
    }

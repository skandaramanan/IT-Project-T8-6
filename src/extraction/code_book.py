"""Code book value mappings for the Prest survey numeric coding cards.

Transcribed from the "Encoding References" Linear doc. Two shapes, matching
the source sheet — don't collapse them into one:

- ``CLOSED_CATEGORIES`` — fully enumerable; an unlisted value is a
  data-quality flag (route to review, FR-09/FR-11), not an accepted case.
- ``SENTINEL_CODES`` — numeric fields where a few boundary codes mean
  something else. Per-field, not universal: Rent's are 00/01/02, Earnings of
  Head's are 997/998/999, Length of Residence's is just 99.

Gap: covers the ~24 categories the coding sheet defines. Several
ground-truth columns (Overcrowding, Poverty, Family Structure, Rooms
Available, the household/dwelling counts) aren't here — some are plain
counts, but Family Structure/Overcrowding values don't look like simple
counts either. Mapping field names to the categories below is left undone
rather than guessed.
"""

from __future__ import annotations

CLOSED_CATEGORIES: dict[str, dict[str, str]] = {
    "Structural Material": {
        "0": "Other",
        "1": "Wood",
        "2": "Brick",
        "3": "Brick veneer",
        "4": "Wood and fibre",
        "5": "Cement and wood",
        "6": "Stone",
        "7": "Brick and wood",
    },
    "Garden and Yard": {
        "0": "None",
        "1": "House on or near street, back yard",
        "2": "Space available, but none cultivated",
        "3": "Some cultivated space",
        "4": "Good garden, incl. fruit, vegetables and poultry (over 100x100)",
        "5": "Commercial activities",
        "6": "Space available, no indication as to use",
    },
    "Repairs": {
        "0": "No indication",
        "1": "Good or fair repair",
        "2": "In need of repair (general or unspecified, or W.C. in bad repair)",
        "3": "Very poor repair (including damp)",
        "4": "Verminous",
        "5": "Condemned but still occupied",
    },
    "Tenure": {
        "0": "Other",
        "1": "Owner",
        "2": "Purchasing owner",
        "3": "Tenant, unfurnished",
        "4": "Tenant, furnished",
        "5": "Sub-tenant, unfurnished",
        "6": "Sub-tenant, furnished",
        "7": "Free",
        "8": "Joint tenant",
        "9": "Owned by another member of family on premises",
    },
    "Whether Used as Bedrooms": {
        "5": "Kitchen",
        "6": "Passage",
        "7": "Washhouse",
        "8": "Other",
    },
    "Sleepouts": {
        "0": "None",
        "1": "Verandah",
        "2": "Balcony",
        "3": "Outhouse",
        "4": "Two or more sleepouts",
    },
    "Bathroom": {
        "0": "No facilities",
        "1": "Bath in laundry",
        "2": "Bath in kitchen",
        "3": "Bath unusable",
        "4": "Bathroom, no heater",
        "5": "Bathroom, heating appliance",
        "6": "Bathroom, external",
        "7": "Bath unusable or no water",
        "8": "More than 1 bathroom",
    },
    "W.C.": {
        "0": "External",
        "1": "Internal",
        "2": "Not sewered",
        "3": "More than one W.C.",
        "4": "None",
    },
    "Washing Facilities": {
        "0": "Inadequate",
        "1": "In separate laundry",
        "2": "In kitchen",
        "3": "In bathroom",
        "4": "External excess",
        "5": "Other",
    },
    "Kitchen": {
        "0": "No kitchen",
        "1": "Kitchenette or kitchen where meals cannot be taken",
        "2": "Kitchen where meals can be taken",
        "3": "Kitchen with distributed facilities",
        "4": "Kitchenette with distributed facilities",
        "5": "Other",
    },
    "Water Supply": {
        "0": "None on premises",
        "1": "External (incl. gully trap)",
        "2": "Internal (in kitchen or kitchenette)",
        "3": "Internal but not in kitchen",
        "4": "Internal with H.W.S. (hot water service)",
        "5": "Tap & no sink",
    },
    "Cooking Facilities": {
        "0": "None",
        "1": "Wood only",
        "2": "Gas, or gas and wood (no indication of ownership)",
        "3": "Gas, or gas and wood (L)",
        "4": "Gas (T) only",
        "5": "Gas (T), Wood (L)",
        "6": "Electric",
        "7": "Gas ring",
        "8": "Kerosene or other",
        "9": "Elect. & gas",
    },
    "Food Storage": {
        "0": "No indication",
        "1": "Icechest",
        "2": "Refrigerator",
        "3": "Cupboards",
        "4": "Pantry or Larder",
        "5": "Safe or cabinet",
        "6": "Fixtures & Tenant's Fridge",
        "7": "Other",
    },
    "Shared": {
        "0": "No facilities shared",
        "1": "Kitchen, W., B., and W.C. shared",
        "2": "Kitchen and W. shared",
        "3": "Bathroom and W.C. shared",
        "4": "Bathroom, washhouse and W.C. shared",
        "5": "Washhouse only shared",
        "6": "W.C. only shared",
        "7": "Washhouse & W.C. shared",
    },
    "Municipality": {
        "00": "Box Hill",
        "01": "Brighton",
        "02": "Brunswick",
        "03": "Camberwell",
        "04": "Caulfield",
        "05": "Chelsea",
        "06": "Coburg",
        "07": "Collingwood",
        "08": "Essendon",
        "09": "Fitzroy",
        "10": "Footscray",
        "11": "Hawthorn",
        "12": "Heidelberg",
        "13": "Kew",
        "14": "Malvern",
        "15": "Melbourne",
        "16": "Moorabbin",
        "17": "Mordialloc",
        "18": "Northcote",
        "19": "Oakleigh",
        "20": "Port Melbourne",
        "21": "Prahran",
        "22": "Preston",
        "23": "Richmond",
        "24": "Sandringham",
        "25": "South Melbourne",
        "26": "St. Kilda",
        "27": "Williamstown",
        "28": "Braybrook",
        "29": "Various",
        "30": "Outside Metrop. area",
        "31": "Working on premises",
        "32": "Not known",
        "99": "Not applicable",
    },
    "Type of Family": {
        "0": "Other",
        "1": "Complete simple family",
        "2": "Complete simple family and relatives or others",
        "3": "Complete simple family and broken family",
        "4": "Two simple complete families",
        "5": "Broken family",
        "6": "Broken family and others",
        "7": "Broken family and another incomplete family",
        "8": "Non-parent families",
    },
    "Relation to Present Head of Persons on Military Service": {
        "0": "No persons on M.S.",
        "1": "Husband",
        "2": "Son or daughter",
        "3": "Son-in-law",
        "4": "Brother-in-law",
        "5": "Brother",
        "6": "Two sons or daughters",
        "7": "Son and husband",
        "8": "One or two others",
        "9": "Three or more persons",
    },
    "Main Source of Income of Head Other Than Earnings": {
        "0": "None",
        "1": "Child endowment",
        "2": "Pensions",
        "3": "Military allotments",
        "4": "Property (rent or interest)",
        "5": "Subletting and lodgers",
        "6": "Superannuation",
        "7": "Living on capital",
        "8": "Relatives",
        "9": "Other or not known",
    },
    "Grade of Occupation of Head": {
        "0": "Employer",
        "1": "Worker on own account",
        "2": "Employee",
        "3": "Unemployed",
        "4": "Not known",
        "9": "Not applicable",
    },
    "Sex of Head": {
        "0": "Male",
        "1": "Female",
    },
    "Regularity of Work": {
        "0": "Regular",
        "1": "Previously unemployed, now regular",
        "2": "Seasonal",
        "3": "Casual",
        "4": "Irregular because of ill-health",
        "5": "Regular: various employers",
        "6": "Other",
        "7": "Temporary",
        "8": "Working on own account",
        "9": "Not applicable",
    },
    "Pre-War Occupation": {
        "0": "No indication",
        "1": "No change",
        "2": "Change from civil to defence",
        "3": "Change from country to city",
        "4": "Own business",
        "5": "Previously home duties",
        "6": "Any other change",
        "7": "Unemployed",
        "8": "Retired",
        "9": "Not applicable",
    },
    "Residential Preference": {
        "0": "No indication",
        "1": "Satisfied",
        "2": "Nearer work",
        "3": "Further from work or better suburb",
        "4": "Country",
        "5": "Dissatisfied with house itself",
        "6": "Now sharing a house or apartment - would prefer own house",
        "7": "Dissatisfied for any other reasons",
        "8": "Rent too high",
    },
    "Type of Dwelling and No. of Storeys": {
        "0": "Other",
        "1": "Detached, one storey",
        "2": "Detached, two or more storeys",
        "3": "Semi-detached, one storey",
        "4": "Semi-detached, two or more storeys",
        "5": "Terrace, one storey",
        "6": "Terrace, two or more storeys",
        "7": "Attached to B.P., one storey",
        "8": "Attached to B.P., two or more storeys",
        "9": "Self-contained flat",
    },
}
"""Fully enumerable fields; an unlisted code is a data-quality flag."""


SENTINEL_CODES: dict[str, dict[str, str]] = {
    "Probable Age": {
        "00": "No indication",
        "98": "Old with no indication of age",
        "99": "Over 99",
        # 01-99 otherwise = exact years
    },
    "Rent": {
        "00": "Free",
        "01": "Rates unknown (owner)",
        "02": "Rent vague or unknown",
        # 03-99 otherwise = exact shillings
    },
    "Length of Residence": {
        "00": "Under one year",
        "99": "Unknown or vague",
        # 01-98 otherwise = years
    },
    "Aggregate Household Income - Earnings of Head": {
        "997": "Unknown because information refused or vague",
        "998": "Unknown because information not known",
        "999": "Unknown because over £10",
        # 000-996 otherwise = exact shillings
    },
    "Amount of Unearned Income of Head": {
        "00": "None",
        "01": "Amount not known",
        # 02-99 otherwise = exact shillings
    },
    "Age of Head": {
        "00": "Not known",
        # 01-99 otherwise = exact years
    },
}
"""Numeric fields with a few per-field boundary codes; don't reuse across fields."""


def decode(category: str, code: str) -> str | None:
    """Label for ``code`` under ``category``, or None if not a listed code
    (either an invalid value, or -- for a SENTINEL_CODES category -- an
    ordinary in-range value with no special meaning).

    Accepts normalised (leading-zero-stripped) codes: if a direct lookup
    misses and the code is purely numeric, it is re-padded to the width of
    the widest key in the table before retrying. This covers fields whose
    code book keys are zero-padded (Municipality, Rent/Age sentinels etc.)
    when the caller holds a value that has passed through _normalise()."""
    table = CLOSED_CATEGORIES.get(category) or SENTINEL_CODES.get(category)
    if table is None:
        return None
    result = table.get(code)
    if result is None and code.isdigit():
        width = max(len(k) for k in table)
        result = table.get(code.zfill(width))
    return result


def is_valid_closed_category_code(category: str, code: str) -> bool:
    """False means either an unknown category, or a code this closed
    category doesn't list -- for CLOSED_CATEGORIES fields that's a genuine
    data-quality flag. Don't use this for SENTINEL_CODES fields -- an
    in-range numeric value is valid there without appearing in the table."""
    table = CLOSED_CATEGORIES.get(category)
    return table is not None and code in table

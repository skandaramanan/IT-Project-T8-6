"""Writes the blank C1/C2 ground-truth sheet for transcribers to type into.

The existing benchmark (``1262761_1973-0002-00052-sample 20.xlsx``) is the C3
multi-family punch-card sheet -- 80 numbered slots, ``Dominant Family`` /
``Family 2/3/4`` blocks -- which IT-73's structure spike found in exactly one
unit (216463). C1 and C2 are 98% of the coding cards and have no ground truth
at all, so nothing measured on the existing benchmark transfers to them.

FIELDS below is the C1 card in reading order: left column top-to-bottom, then
middle, then right. Cross-checked two ways -- read off the C1 reference scan
(``results/reference_cards/coding-front_36d15987_216415_p0148.png``) and
against the 212-card aggregate label counts in ``results/canonical.md``. The
two agree on all 62.

``No. of Family Boarders`` is the one field C2 has and C1 doesn't; it sits
mid-column after ``No. of Boarders``. Leave it empty on C1 rows. Everything
else differs only in how the card is printed, not what it records:
C2 spells out ``...Unearned Income`` where C1 truncates to ``...Unearned I.``.

Usage:
    uv run python spike/make_c1_ground_truth_sheet.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font

DEFAULT_OUT = Path("data/coding-card-c1-c2-ground-truth-blank.xlsx")

# Where the card came from. Unlike the C3 benchmark -- 20 cards from one PDF --
# a C1 set is drawn from many units, so the page number alone can't find the
# image. spike/ground_truth.py currently treats every non-"page id" column as a
# field, so it needs these four excluded before it can load this sheet.
META_COLUMNS = ["page id", "unit", "pdf page", "card type"]

# The C1 card, in reading order. C2 adds "No. of Family Boarders" (marked).
FIELDS: list[str] = [
    # --- left column ---
    "Municipality",
    "Number of Dwelling",
    "Number of Household",
    "Type of Family",
    "Total No. Resident Members",
    "Number under 5",
    "Number 5-10",
    "Number over 10 M.",
    "Number over 10 F.",
    "Military Service",
    "No. of Boarders",
    "No. of Family Boarders",  # C2 only -- blank on C1 rows
    "No. of Participating Members",
    "No. of Adult M. Breadwinners",
    "No. of Adult F. Breadwinners",
    "No. of Juvenile Breadwinners (under 21)",
    "Children under 14",
    "Retired and Indep. Persons",
    "Home Duties",
    "Other",
    # --- middle column ---
    "Normal Household I.",
    "Weekly Rent",
    "Total Available I.",
    "Earnings of Head",
    "Head's Unearned I.",
    "Main Source of Head's Unearned I.",
    "Subsidiary Source of Head's I.",
    "Industry of H.",
    "Occupation of H.",
    "Grade of Occup. of H.",
    "Place of Work",
    "Age of Head",
    "Sex of Head",
    "Regularity of Work",
    "Pre-War Occupation",
    "Removal",
    "Type of Dwelling",
    "Structural Material",
    "Age of House",
    "Garden",
    "State of Repair",
    "Tenure",
    # --- right column ---
    "Length of Residence",
    "Total Number of Rooms",
    "Number of Bedrooms",
    "Number of Living Rooms",
    "Whether used as Bedrooms",
    "Rooms not in Daily Use",
    "Number of Sleepouts",
    "Bathroom",
    "W.C.",
    "Washouse",
    "Kitchen",
    "Sink and Water Service",
    "Cooking Facilities",
    "Food Storage",
    "Rooms Shared",
    "Persons Sharing",
    "Children other than those at home",
    "Children of H. or wife: Living",
    "Children of H. or wife: Dead",
    "Children of H. or wife: Total",
]


def build(out_path: Path = DEFAULT_OUT, rows: int = 20) -> Path:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "ground truth"

    header = META_COLUMNS + FIELDS
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(text_rotation=60, vertical="bottom")

    # Codes are zero-padded ("060" is not 60) and the C3 sheet only kept its
    # leading zeros because the cells were text-formatted. Pre-format the whole
    # grid as text so a transcriber typing 060 doesn't silently get 60.
    for row in range(2, rows + 2):
        for column in range(1, len(header) + 1):
            sheet.cell(row=row, column=column).number_format = "@"

    sheet.freeze_panes = "E2"  # keep the four meta columns and header visible
    for index in range(1, len(META_COLUMNS) + 1):
        sheet.column_dimensions[
            sheet.cell(row=1, column=index).column_letter
        ].width = 11
    for index in range(len(META_COLUMNS) + 1, len(header) + 1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = 5
    sheet.row_dimensions[1].height = 150

    out_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(out_path)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--rows", type=int, default=20, help="Blank card rows to pre-format"
    )
    args = parser.parse_args()
    path = build(args.out, args.rows)
    print(f"Wrote {path} -- {len(FIELDS)} fields, {args.rows} blank rows")


if __name__ == "__main__":
    main()

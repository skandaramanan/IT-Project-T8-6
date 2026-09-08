"""Loads a benchmark ground-truth sheet straight from the transcriber's xlsx.

Two sheets exist and they are not interchangeable:

- **C1/C2** (the default) -- 30 cards, 62 fields, drawn one per unit from 30
  different units. C1 and C2 are 98% of the coding cards, so this is the sheet
  that measures FR-01. Built by ``spike/select_c1_c2_sample.py``, transcribed
  twice (once by model, once by hand) and reconciled; the images sit beside it.
- **C3** -- the original 20 cards, all from unit 216463. IT-73's structure
  spike found C3 on 4 pages of one unit, ~2% of coding cards, so numbers
  measured on it do not transfer to C1/C2. Kept because C3 is still a real
  card type that needs its own extractor.

Field names come from the header row, not a hardcoded schema, so adding a
column doesn't require a code change here. Everything that isn't a field is
listed in ``make_c1_ground_truth_sheet.META_COLUMNS`` -- keep the two in step,
because a meta column that slips through gets scored as if it were a field.

The id column is taken **by position**, not by header text: the C1/C2 sheet has
been through Excel, which coerced its ``page id`` header to the number 0. The
first column is the id column by construction, so nothing is gained by trusting
what the header says it is called.

The sheet's used-range reports more rows than actually have data (an xlsx
artifact, not real rows) -- filtered out by skipping any row with an empty id.
Cells are text-formatted in the source, so leading zeros on codes like "060"
survive as strings, not ints -- don't let a future edit read this with a
numeric type and silently drop them. ``scoring._normalise`` does not strip them
either; see that module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import openpyxl
from make_c1_ground_truth_sheet import META_COLUMNS

DEFAULT_GROUND_TRUTH_XLSX = Path(
    "data/benchmark/c1c2/coding-card-c1-c2-ground-truth.xlsx"
)
DEFAULT_IMAGES_DIR = Path("data/benchmark/c1c2")

C3_GROUND_TRUTH_XLSX = Path(
    "data/Wilfred_Prest_Survey_Data/1262761_1973-0002-00052-sample 20.xlsx"
)
C3_IMAGES_DIR = Path("data/benchmark/images")

# C3 only. page id -> the PDF page the card is actually on.
#
# A record in the batch PDF is four pages: coding front, coding back, survey
# front, survey back (tests/fixtures/README.md). 18 of the 20 page ids land on
# the coding front. These two land on a survey back -- free-text interviewer
# notes with no codes on them at all -- so any extractor scores ~0 on them no
# matter how good it is.
#
# Corrected by finding the nearest coding front and matching it against the row
# on Municipality / No. of Dwelling / T.A.I. / Income from S.Letting / Net Rent,
# by hand, 2026-08-23:
#   row 134 -> page 131 (municipality 56, dwelling 83, 997 / 98 / 02)
#   row 168 -> page 169 (municipality 56, dwelling 91, 997 / 97 / 98)
# The other 18 were confirmed in place by cross-checking No. of Dwelling.
#
# The C1/C2 sheet needs no equivalent: it carries the source page in its own
# ``pdf page`` column, written by the script that extracted the images.
SOURCE_PAGE_CORRECTIONS = {134: 131, 168: 169}


@dataclass(frozen=True)
class BenchmarkCard:
    page_id: str  # the sheet's row id -- results stay keyed by this
    source_page: int  # the PDF page the image comes from
    image_path: Path
    fields: dict[
        str, str
    ]  # field name -> hand-transcribed value, raw ("-" and "" both mean no
    # code in that cell, inconsistently -- see scoring.VOID_MARKS)


def _rows(xlsx_path: Path) -> list[tuple]:
    workbook = openpyxl.load_workbook(xlsx_path, read_only=True)
    try:
        sheet = workbook.active
        return [
            row for row in sheet.iter_rows(values_only=True) if row[0] not in (None, "")
        ]
    finally:
        workbook.close()


def _meta(header: tuple) -> set:
    """Header cells that are not extraction fields.

    The id column counts whatever it is called, because Excel has already
    renamed it once (see module docstring).
    """
    return {header[0], *(name for name in header if name in META_COLUMNS)}


def field_names(xlsx_path: Path = DEFAULT_GROUND_TRUTH_XLSX) -> list[str]:
    """The field names from the sheet's header row, in column order."""
    header = _rows(xlsx_path)[0]
    meta = _meta(header)
    return [str(name) for name in header if name and name not in meta]


def load_ground_truth(
    xlsx_path: Path = DEFAULT_GROUND_TRUTH_XLSX,
    images_dir: Path = DEFAULT_IMAGES_DIR,
) -> list[BenchmarkCard]:
    rows = _rows(xlsx_path)
    header, data_rows = rows[0], rows[1:]
    meta = _meta(header)

    cards: list[BenchmarkCard] = []
    for row in data_rows:
        row_dict = dict(zip(header, row))
        page_id = str(row[0]).strip()
        fields = {
            str(name): str(value).strip() if value is not None else ""
            for name, value in row_dict.items()
            if name and name not in meta
        }

        card_type = row_dict.get("card type")
        if card_type:  # C1/C2: the sheet records its own source page
            source_page = int(row_dict["pdf page"])
            image_path = images_dir / f"{page_id}_{card_type}.png"
        else:  # C3: page id is the source page, bar the two corrections
            source_page = SOURCE_PAGE_CORRECTIONS.get(int(page_id), int(page_id))
            # named for the page it really came from, not the row it scores
            image_path = images_dir / f"page{source_page:03d}.jpg"

        cards.append(
            BenchmarkCard(
                page_id=page_id,
                source_page=source_page,
                image_path=image_path,
                fields=fields,
            )
        )
    return cards

"""Loads the IT-37 benchmark ground truth directly from the transcriber's xlsx
(already present in the synced Drive dataset -- no intermediate CSV).

20 numeric coding cards, one row per card, keyed by ``page id`` -- the literal
page number of that card within the source region-batch PDF (confirmed by
cross-checking page 7 against its row by hand). Field names come straight from
the sheet's header row, not a hardcoded schema, so adding a column doesn't
require a code change here.

The sheet's used-range reports more rows than actually have data (an xlsx
artifact, not real rows) -- filtered out by skipping any row with an empty
``page id``. Cells are text-formatted in the source, so leading zeros on
codes like "060" survive as strings, not ints -- don't let a future edit read
this with a numeric type and silently drop them.

Two of the transcriber's page ids are wrong, so the card's image comes from
``source_page``, not ``page_id`` -- see SOURCE_PAGE_CORRECTIONS.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import openpyxl

DEFAULT_GROUND_TRUTH_XLSX = Path(
    "data/Wilfred_Prest_Survey_Data/1262761_1973-0002-00052-sample 20.xlsx"
)
DEFAULT_IMAGES_DIR = Path("data/benchmark/images")

# page id -> the PDF page the card is actually on.
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
# Cross-check: the shared Drive also holds survey_cards_by_dwelling.pdf, the
# same 20 cards pulled out and reordered. Its pages are ~1353x865 against the
# batch PDF's ~3800x2400, so it stays a cross-reference and not the source --
# a third of the linear resolution on pencil digits is not what you want to
# benchmark against. Scaled page widths there match 131 and 169; neither 134
# nor 168 appears at all.
SOURCE_PAGE_CORRECTIONS = {134: 131, 168: 169}


@dataclass(frozen=True)
class BenchmarkCard:
    page_id: int  # the transcriber's row id -- results stay keyed by this
    source_page: int  # the PDF page the image comes from (see SOURCE_PAGE_CORRECTIONS)
    image_path: Path
    fields: dict[
        str, str
    ]  # field name -> hand-transcribed value, raw ("-" and "" both mean no
    # code in that cell, inconsistently -- see scoring.VOID_MARKS)


def _rows(xlsx_path: Path) -> list[tuple]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    try:
        ws = wb.active
        return [
            row for row in ws.iter_rows(values_only=True) if row[0] not in (None, "")
        ]
    finally:
        wb.close()


def field_names(xlsx_path: Path = DEFAULT_GROUND_TRUTH_XLSX) -> list[str]:
    """The 60 field names from the sheet's header row, in column order."""
    header = _rows(xlsx_path)[0]
    return [str(name) for name in header if name and name != "page id"]


def load_ground_truth(
    xlsx_path: Path = DEFAULT_GROUND_TRUTH_XLSX,
    images_dir: Path = DEFAULT_IMAGES_DIR,
) -> list[BenchmarkCard]:
    rows = _rows(xlsx_path)
    header, data_rows = rows[0], rows[1:]

    cards: list[BenchmarkCard] = []
    for row in data_rows:
        row_dict = dict(zip(header, row))
        page_id = int(row_dict["page id"])
        fields = {
            str(name): str(value).strip() if value is not None else ""
            for name, value in row_dict.items()
            if name and name != "page id"
        }
        source_page = SOURCE_PAGE_CORRECTIONS.get(page_id, page_id)
        cards.append(
            BenchmarkCard(
                page_id=page_id,
                source_page=source_page,
                # named for the page it really came from, not the row it scores
                image_path=images_dir / f"page{source_page:03d}.jpg",
                fields=fields,
            )
        )
    return cards

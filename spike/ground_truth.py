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
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import openpyxl

DEFAULT_GROUND_TRUTH_XLSX = Path(
    "data/Wilfred_Prest_Survey_Data/1262761_1973-0002-00052-sample 20.xlsx"
)
DEFAULT_IMAGES_DIR = Path("data/benchmark/images")


@dataclass(frozen=True)
class BenchmarkCard:
    page_id: int
    image_path: Path
    fields: dict[
        str, str
    ]  # field name -> hand-transcribed value, raw ("-" means not applicable)


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
        image_path = images_dir / f"page{page_id:03d}.jpg"
        cards.append(
            BenchmarkCard(page_id=page_id, image_path=image_path, fields=fields)
        )
    return cards

"""Loads a benchmark ground-truth sheet straight from the transcriber's xlsx.

The sheet is the C1/C2 one: 30 cards, 62 fields, drawn one per unit from 30
different units. C1 and C2 are 98% of the coding cards, so this is what
measures FR-01. Built by ``spike/select_c1_c2_sample.py``, transcribed twice
(once by model, once by hand) and reconciled; the images sit beside it.

The older C3 sheet is deliberately not supported here. C3 shares 0 of its 62
printed labels with C1/C2, and every extractor is prompted from
``FIELD_SCHEMA`` -- so a C3 run asked for the wrong field names entirely and
scored ~0%, which reads as a model failure rather than the harness fault it
was. D015 gives C3 its own schema; wire that up when the C3 extractor is built
rather than inheriting this wiring.

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
numeric type and silently drop them. ``scoring.normalise`` does not strip them
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
        if not card_type:
            raise ValueError(
                f"{xlsx_path} has no 'card type' column -- this loader reads the "
                "C1/C2 sheet, which records its own source page and card type"
            )
        source_page = int(row_dict["pdf page"])
        image_path = images_dir / f"{page_id}_{card_type}.png"

        cards.append(
            BenchmarkCard(
                page_id=page_id,
                source_page=source_page,
                image_path=image_path,
                fields=fields,
            )
        )
    return cards

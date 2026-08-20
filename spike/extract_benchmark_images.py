"""Regenerates data/benchmark/images/ from the source batch PDF.

data/ is gitignored, so the extracted JPEGs themselves are never committed --
this script is what's committed instead, so anyone with the source PDF
(shared Drive) gets byte-for-byte identical output, on any machine.

Same technique as tests/fixtures/README.md's regeneration recipe: the raw
JPEG XObject stream is copied out as-is, no decode/re-encode, so this is
deterministic -- same PDF in, same bytes out, every time.

Usage:
    uv run python spike/extract_benchmark_images.py \\
        --pdf /path/to/1262761_1973-0002-00052.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ground_truth import (
    DEFAULT_GROUND_TRUTH_XLSX,
    DEFAULT_IMAGES_DIR,
    load_ground_truth,
)
from pypdf import PdfReader


def extract_benchmark_images(
    pdf_path: Path,
    ground_truth_xlsx: Path = DEFAULT_GROUND_TRUTH_XLSX,
    images_dir: Path = DEFAULT_IMAGES_DIR,
) -> list[Path]:
    page_ids = sorted(
        card.page_id
        for card in load_ground_truth(
            xlsx_path=ground_truth_xlsx, images_dir=images_dir
        )
    )
    images_dir.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(pdf_path)
    written: list[Path] = []
    for page_id in page_ids:
        page = reader.pages[page_id - 1]
        for ref in page["/Resources"]["/XObject"].get_object().values():  # type: ignore[index]
            obj = ref.get_object()
            if obj.get("/Subtype") == "/Image":
                out_path = images_dir / f"page{page_id:03d}.jpg"
                out_path.write_bytes(
                    obj._data
                )  # raw stream, no re-encode -- see module docstring
                written.append(out_path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf", type=Path, required=True, help="Path to the source region-batch PDF"
    )
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_XLSX)
    parser.add_argument("--out", type=Path, default=DEFAULT_IMAGES_DIR)
    args = parser.parse_args()

    written = extract_benchmark_images(args.pdf, args.ground_truth, args.out)
    print(f"Wrote {len(written)} images to {args.out}")


if __name__ == "__main__":
    main()

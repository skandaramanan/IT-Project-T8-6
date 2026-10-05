"""Pull a scan image back out of a source PDF page."""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader

# PNG is lossless and right for the benchmark, but a card lands at ~5 MB and
# Document Intelligence caps a *custom template* training set at 50 MB for
# everything in the folder -- ten cards alone reach 49 MB. JPEG at this quality
# is ~0.8 MB with no visible loss on pencil digits, and the scans are stored as
# JPEG inside the source PDFs anyway. Custom neural's cap is 1 GB, so this only
# matters for the template fallback.
JPEG_QUALITY = 92


def extract_image(
    pdf_path: Path, page_number: int, out_path: Path, image_format: str = "png"
) -> None:
    """Write the page's largest embedded image.

    Uses pypdf's decoded ``page.images`` rather than copying the raw XObject
    stream: 7 units store pages as JPEG 2000 and 4 wrap the scan in a Form
    XObject, and a raw top-level stream copy handles neither.
    """
    # Pages are 1-based here. A 0 or a negative from a bad upstream row would
    # index from the end instead of failing, and quietly put the wrong scan in
    # the ground-truth set.
    if page_number < 1:
        raise ValueError(f"page number {page_number} is not 1-based ({pdf_path})")

    from PIL import Image

    page = PdfReader(pdf_path).pages[page_number - 1]
    images = list(page.images)
    if not images:
        raise ValueError(f"no image on page {page_number} of {pdf_path}")
    largest = max(images, key=lambda image: len(image.data))
    image = Image.open(io.BytesIO(largest.data))
    if image_format == "jpeg":
        # JPEG has no alpha channel and some scans decode as RGBA/P
        image.convert("RGB").save(out_path, "JPEG", quality=JPEG_QUALITY)
    else:
        image.save(out_path)

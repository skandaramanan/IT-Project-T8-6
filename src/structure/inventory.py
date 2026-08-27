"""Enumerates every page in the archive and hands out its scan bytes.

The unit of work is a *page*, not a record. A record is four pages (survey
front, survey back, coding front, coding back -- tests/fixtures/README.md), but
22 of the 44 readable unit PDFs have page counts that aren't divisible by four,
so the four-page cycle demonstrably breaks somewhere. Assuming records here
would bake that assumption into every downstream result; the analysis pass
labels each page's role instead, and the cycle is reconstructed from those
labels afterwards.

Pages are never written to disk. Each page's embedded scan is copied out of
the PDF byte-for-byte where it already is a JPEG (same technique as
spike/extract_benchmark_images.py -- no decode, no re-encode, deterministic),
handed straight to the worker, and dropped. Materialising all ~21.7k as files
would put ~6.6 GB of derived data next to a dataset that already holds it.

The archive is not uniformly encoded, and both departures are invisible until
you look for them:

- 7 units (216412-216417, 216431) store pages as JPEG 2000, which the vision
  provider rejects outright. Those are transcoded to JPEG on the way out.
- 4 units (216424-216427) wrap the scan in a Form XObject rather than putting
  it on the page, so a top-level-only XObject walk finds nothing there.

One unit PDF (216436) is corrupt -- pypdf raises "Stream has ended
unexpectedly" even with strict=False. It is reported as an unreadable unit
rather than crashing the run.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import IndirectObject

DEFAULT_INPUT_DIR = Path("data/Wilfred_Prest_Survey_Data")

# PDF stream filters whose raw stream is already a complete image file. JPEG
# goes out untouched; JPEG 2000 is decoded and re-encoded below because the
# provider won't take it. Every other filter (Flate-encoded raster, CCITT fax)
# is reported as an extraction failure naming the filter, rather than guessed
# at -- none has turned up in this archive, and the log will say so if one does.
IMAGE_FILTER_MIMES = {
    "/DCTDecode": "image/jpeg",
    "/JPXDecode": "image/jp2",
}


@dataclass(frozen=True)
class Page:
    """One page of one unit PDF -- the provenance every result carries."""

    card_id: str  # "216412_p0007"
    unit: str  # archive Node ID / folder name
    pdf: Path
    page_number: int  # 1-based, as a human would cite it


@dataclass(frozen=True)
class PageImage:
    data: bytes
    mime: str
    image_count: int  # >1 means the page isn't the expected single-scan layout


class UnreadablePdf(Exception):
    pass


def find_unit_pdfs(input_dir: Path) -> list[tuple[str, Path]]:
    """(unit, pdf) for every unit folder, sorted by unit.

    Only ``<unit>/*.pdf`` is picked up: the dataset root also holds
    survey_cards_by_dwelling.pdf, which is a separate compilation, not a unit.
    """
    pairs = [
        (pdf.parent.name, pdf)
        for pdf in sorted(input_dir.glob("*/*.pdf"))
        if not pdf.name.startswith(".")
    ]
    if not pairs:
        raise SystemExit(f"No unit PDFs under {input_dir}/*/*.pdf")
    return pairs


def open_unit(pdf: Path) -> PdfReader:
    # strict=False gets past the malformed-but-recoverable files; the one
    # genuinely truncated PDF still raises, and callers turn that into a
    # recorded unreadable unit.
    try:
        return PdfReader(pdf, strict=False)
    except Exception as error:  # pypdf raises a dozen types here; all mean unreadable
        raise UnreadablePdf(f"{pdf}: {error}") from error


def unit_pages(unit: str, pdf: Path, reader: PdfReader) -> list[Page]:
    return [
        Page(card_id=f"{unit}_p{number:04d}", unit=unit, pdf=pdf, page_number=number)
        for number in range(1, len(reader.pages) + 1)
    ]


def image_xobjects(resources, depth: int = 0) -> list:
    """Every image XObject reachable from a resource dictionary.

    Recursive because units 216424-216427 wrap the scan in a Form XObject
    (``/Fg``) instead of placing it on the page directly -- ~2,100 pages that a
    top-level-only walk reports as having no image at all, silently.
    """
    if resources is None or depth > 4:  # depth cap: a malformed PDF can cycle
        return []
    xobjects = resources.get("/XObject")
    if isinstance(xobjects, IndirectObject):
        xobjects = xobjects.get_object()
    if not xobjects:
        return []

    found = []
    for ref in xobjects.values():
        obj = ref.get_object()
        if obj.get("/Subtype") == "/Image":
            found.append(obj)
        elif obj.get("/Subtype") == "/Form":
            found.extend(image_xobjects(obj.get("/Resources"), depth + 1))
    return found


def _pixels(image) -> int:
    try:
        return int(image["/Width"]) * int(image["/Height"])
    except (KeyError, TypeError, ValueError):
        return len(image._data)  # no dimensions recorded; stream size will do


def jp2_to_jpeg(data: bytes) -> bytes:
    """JPEG 2000 is a real encoding in this archive and a 400 at the provider.

    Seven units (216412-216417, 216431) plus the four Form-wrapped ones are
    JPX, ~4,900 pages in all, and OpenRouter's provider rejects image/jp2. They
    are the only pages that get re-encoded; every DCTDecode page still goes out
    as the exact bytes the archive holds. Quality 90 keeps the pencil strokes
    the coding cards are written in -- lower starts eating thin graphite.
    """
    from PIL import Image  # imported lazily: only ~23% of pages ever need it

    with Image.open(io.BytesIO(data)) as image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "JPEG", quality=90)
        return buffer.getvalue()


def page_image(reader: PdfReader, page_number: int) -> PageImage:
    """The page's embedded scan, as bytes a vision API will accept."""
    images = image_xobjects(reader.pages[page_number - 1].get("/Resources"))
    if not images:
        raise ValueError("page has no image XObject")

    # Expected layout is exactly one full-page scan. Where a page carries
    # several, the biggest is the scan and the rest are artefacts -- take it,
    # but pass the count through so the result records the oddity.
    image = max(images, key=_pixels)
    filters = image.get("/Filter")
    filters = filters if isinstance(filters, list) else [filters]
    mime = next(
        (IMAGE_FILTER_MIMES[f] for f in filters if f in IMAGE_FILTER_MIMES), None
    )
    if mime is None:
        raise ValueError(f"unsupported image filter {filters!r}")

    data = image._data
    if mime == "image/jp2":
        data, mime = jp2_to_jpeg(data), "image/jpeg"
    return PageImage(data=data, mime=mime, image_count=len(images))

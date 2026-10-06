"""Pull a scan image back out of a source PDF page."""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PageObject, PdfReader
from pypdf.generic import ContentStream, NullObject, StreamObject

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
    placed = _placements(page, page.pdf)
    if len(placed) > 1 and _axis_aligned(max(placed, key=_pixels)[1]):
        _save(_composite(placed), out_path, image_format)
        return
    images = list(page.images)
    if not images:
        raise ValueError(f"no image on page {page_number} of {pdf_path}")
    largest = max(images, key=lambda image: len(image.data))
    image = Image.open(io.BytesIO(largest.data))
    _save(image, out_path, image_format)


def _save(image, out_path: Path, image_format: str) -> None:
    if image_format == "jpeg":
        # JPEG has no alpha channel and some scans decode as RGBA/P
        image.convert("RGB").save(out_path, "JPEG", quality=JPEG_QUALITY)
    else:
        image.save(out_path)


_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _placements(
    container, pdf, ctm=_IDENTITY, resources=None
) -> list[tuple[StreamObject, tuple]]:
    """(image XObject, CTM) for every image the content draws, Forms included.

    Images are keyed by object, not name: a page and each of its Forms number
    their own images from /Im0.
    """
    resources = container.get("/Resources", resources) or {}
    xobjects = resources.get("/XObject", {})
    stack, placed = [], []
    for args, op in ContentStream(
        container.get_contents() if isinstance(container, PageObject) else container,
        pdf,
    ).operations:
        if op == b"q":
            stack.append(ctm)
        elif op == b"Q" and stack:
            ctm = stack.pop()
        elif op == b"cm":
            ctm = _multiply(tuple(float(v) for v in args), ctm)
        elif op == b"Do" and args[0] in xobjects:
            xobject = xobjects[args[0]].get_object()
            if xobject.get("/Subtype") == "/Image":
                placed.append((xobject, ctm))
            elif xobject.get("/Subtype") == "/Form":
                matrix = tuple(float(v) for v in xobject.get("/Matrix", _IDENTITY))
                placed += _placements(xobject, pdf, _multiply(matrix, ctm), resources)
    return placed


def _pixels(placement) -> int:
    return placement[0]["/Width"] * placement[0]["/Height"]


def _axis_aligned(ctm) -> bool:
    a, b, c, d, _, _ = ctm
    return a != 0 and d != 0 and b == 0 and c == 0


def _multiply(m, n):
    a, b, c, d, e, f = m
    p, q, r, s, t, u = n
    return (
        a * p + b * r,
        a * q + b * s,
        c * p + d * r,
        c * q + d * s,
        e * p + f * r + t,
        e * q + f * s + u,
    )


def _decode(xobject):
    """RGBA when the image has a stencil /Mask, so only its painted pixels land."""
    image = xobject.decode_as_image().convert("RGB")
    # .get does not resolve indirect references
    mask = xobject.get("/Mask", NullObject()).get_object()
    # a /Mask array is a colour key, not a stencil
    if not isinstance(mask, StreamObject):
        return image
    # a 1 sample masks the pixel out unless /Decode flips it
    painted = mask.decode_as_image().convert("L").resize(image.size)
    if list(mask.get("/Decode", [0, 1])) == [0, 1]:
        painted = painted.point(lambda v: 255 - v)
    image.putalpha(painted)
    return image


def _composite(placed: list[tuple[StreamObject, tuple]]):
    """Paste each image onto the largest one at its content-stream position.

    Layered scans keep the handwriting in small patch images drawn over a
    full-page background, so the background alone has blank boxes. Only
    axis-aligned placements are handled (flips included); other patches are
    skipped.
    """
    from PIL import Image

    background = max(placed, key=_pixels)
    # decoding JPEG 2000 costs seconds, so only decode what gets pasted
    canvas = background[0].decode_as_image().convert("RGB")
    ba, _, _, bd, be, bf = background[1]
    for xobject, ctm in placed:
        if xobject is background[0] or not _axis_aligned(ctm):
            continue
        a, _, _, d, e, f = ctm
        patch = _decode(xobject)
        # page space -> background pixels; the unit square's y runs up, pixels down
        x0, x1 = sorted(((e - be) / ba, (e + a - be) / ba))
        y0, y1 = sorted((1 - (f - bf) / bd, 1 - (f + d - bf) / bd))
        box = (
            round(x0 * canvas.width),
            round(y0 * canvas.height),
            round(x1 * canvas.width),
            round(y1 * canvas.height),
        )
        if (a / ba) < 0:
            patch = patch.transpose(Image.FLIP_LEFT_RIGHT)
        if (d / bd) < 0:
            patch = patch.transpose(Image.FLIP_TOP_BOTTOM)
        size = (max(box[2] - box[0], 1), max(box[3] - box[1], 1))
        patch = patch.resize(size)
        canvas.paste(patch, box[:2], patch if patch.mode == "RGBA" else None)
    return canvas

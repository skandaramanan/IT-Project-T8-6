"""Layered scans: patch images drawn over a background must land in the output."""

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    StreamObject,
)

from survey.segmentation.pdf_pages import extract_image

WHITE = (255, 255, 255)


def _stream(writer, data, **entries):
    stream = StreamObject()
    stream._data = data
    for key, value in entries.items():
        stream[NameObject(f"/{key}")] = value
    return writer._add_object(stream)


def _image(writer, size, rgb, mask=None):
    pixels = rgb if isinstance(rgb, list) else [rgb] * (size[0] * size[1])
    entries = {
        "Type": NameObject("/XObject"),
        "Subtype": NameObject("/Image"),
        "Width": NumberObject(size[0]),
        "Height": NumberObject(size[1]),
        "BitsPerComponent": NumberObject(8),
    }
    if mask is not None:
        entries["Mask"] = _stream(
            writer,
            mask,
            **{
                **entries,
                "BitsPerComponent": NumberObject(1),
                "ImageMask": BooleanObject(True),
            },
        )
    return _stream(
        writer,
        b"".join(bytes(px) for px in pixels),
        ColorSpace=NameObject("/DeviceRGB"),
        **entries,
    )


def _resources(**xobjects):
    return DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject(f"/{k}"): v for k, v in xobjects.items()}
            )
        }
    )


def _write(tmp_path, writer, page, ops, **xobjects):
    page[NameObject("/Resources")] = _resources(**xobjects)
    page[NameObject("/Contents")] = _stream(writer, ops.encode())
    path = tmp_path / "scan.pdf"
    writer.write(path)
    return path


def _pdf(tmp_path, draws):
    """One 100x100 page; ``draws`` is [(size, rgb, cm[, mask])] drawn in order."""
    writer = PdfWriter()
    page = writer.add_blank_page(100, 100)
    xobjects = {
        f"Im{i}": _image(writer, size, rgb, *mask)
        for i, (size, rgb, _, *mask) in enumerate(draws)
    }
    ops = "".join(f"q {cm} cm /Im{i} Do Q\n" for i, (_, _, cm, *_) in enumerate(draws))
    return _write(tmp_path, writer, page, ops, **xobjects)


def _extract(pdf, tmp_path):
    out = tmp_path / "out.png"
    extract_image(pdf, 1, out)
    return Image.open(out).convert("RGB")


def test_patch_is_composited_where_the_content_stream_draws_it(tmp_path):
    # background is 200x200 for a 100pt page, so 1pt = 2px; the patch spans
    # x 10..30pt and y 60..70pt up from the bottom, i.e. 60..80px from the top
    pdf = _pdf(
        tmp_path,
        [
            ((200, 200), WHITE, "100 0 0 100 0 0"),
            ((4, 2), (0, 0, 0), "20 0 0 10 10 60"),
        ],
    )
    image = _extract(pdf, tmp_path)
    assert image.size == (200, 200)
    assert image.getpixel((30, 60)) == (0, 0, 0)
    assert image.getpixel((30, 79)) == (0, 0, 0)
    assert image.getpixel((19, 60)) == WHITE
    assert image.getpixel((30, 59)) == WHITE
    assert image.getpixel((30, 81)) == WHITE


def test_flipped_patch_is_pasted_upside_down_relative_to_the_background(tmp_path):
    # negative d draws the patch's first row at the bottom of its box
    pdf = _pdf(
        tmp_path,
        [
            ((100, 100), WHITE, "100 0 0 100 0 0"),
            ((1, 2), [(255, 0, 0), (0, 0, 255)], "10 0 0 -20 10 50"),
        ],
    )
    image = _extract(pdf, tmp_path)
    # resampling blends a little, so compare the dominant channel
    assert image.getpixel((15, 55))[2] > 200
    assert image.getpixel((15, 65))[0] > 200


def test_stencil_mask_keeps_the_background_where_the_patch_is_masked_out(tmp_path):
    # a 1 sample masks the pixel out: the left half of the patch must not paint
    pdf = _pdf(
        tmp_path,
        [
            ((100, 100), WHITE, "100 0 0 100 0 0"),
            ((2, 1), (0, 0, 0), "20 0 0 10 10 10", b"\x80"),
        ],
    )
    image = _extract(pdf, tmp_path)
    assert image.getpixel((12, 85)) == WHITE
    assert image.getpixel((28, 85)) == (0, 0, 0)


def test_images_inside_form_xobjects_are_composited_by_their_full_matrix(tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(100, 100)
    # both Forms number their image /Im0, and the patch Form is offset by a cm
    background = _stream(
        writer,
        b"q 100 0 0 100 0 0 cm /Im0 Do Q",
        Subtype=NameObject("/Form"),
        BBox=ArrayObject(NumberObject(v) for v in (0, 0, 100, 100)),
        Resources=_resources(Im0=_image(writer, (100, 100), WHITE)),
    )
    patch = _stream(
        writer,
        b"q 10 0 0 10 0 0 cm /Im0 Do Q",
        Subtype=NameObject("/Form"),
        BBox=ArrayObject(NumberObject(v) for v in (0, 0, 100, 100)),
        Resources=_resources(Im0=_image(writer, (2, 2), (0, 0, 0))),
    )
    pdf = _write(
        tmp_path,
        writer,
        page,
        "q /Fg Do Q q 1 0 0 1 20 30 cm /P0 Do Q",
        Fg=background,
        P0=patch,
    )
    image = _extract(pdf, tmp_path)
    assert image.size == (100, 100)
    assert image.getpixel((25, 65)) == (0, 0, 0)
    assert image.getpixel((15, 65)) == WHITE


def test_degenerate_background_matrix_falls_back_to_the_largest_image(tmp_path):
    pdf = _pdf(
        tmp_path,
        [
            ((50, 40), (200, 200, 200), "0 0 0 0 0 100"),
            ((4, 4), (0, 0, 0), "10 0 0 10 10 10"),
        ],
    )
    image = _extract(pdf, tmp_path)
    assert image.size == (50, 40)
    assert image.getpixel((5, 5)) == (200, 200, 200)


def test_single_image_page_is_the_image_itself(tmp_path):
    pdf = _pdf(tmp_path, [((8, 6), (10, 20, 30), "100 0 0 100 0 0")])
    image = _extract(pdf, tmp_path)
    assert image.size == (8, 6)
    assert image.getpixel((3, 3)) == (10, 20, 30)

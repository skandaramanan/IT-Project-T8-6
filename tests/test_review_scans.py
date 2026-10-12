from dataclasses import replace

import pytest
from PIL import Image
from pypdf import PdfWriter
from review_support import refs, setup_review, synthetic_pdf

from survey.records import ReviewError


def test_original_page_identity_cache_and_invalidation(tmp_path):
    service, settings = setup_review(tmp_path)
    source = service.scans
    page1 = source.get_scan(refs()[0])
    page2 = source.get_scan(refs()[1])
    assert page1 != page2
    with Image.open(page1) as first, Image.open(page2) as second:
        assert first.getpixel((1, 1)) != second.getpixel((1, 1))
    assert source.get_scan(refs()[1]) == page2
    synthetic_pdf(settings.scan_root / "demo" / "synthetic.pdf")
    assert source.get_scan(refs()[1]) != page2


def test_scan_missing_and_out_of_bounds(tmp_path):
    service, settings = setup_review(tmp_path)
    with pytest.raises(ReviewError, match="bounds"):
        service.scans.get_scan(replace(refs()[1], page=999))
    with pytest.raises(ReviewError, match="missing"):
        service.scans.get_scan(replace(refs()[1], pdf="missing.pdf"))
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(settings.scan_root / "demo" / "blank.pdf")
    with pytest.raises(ReviewError, match="no scan image"):
        service.scans.get_scan(replace(refs()[1], pdf="blank.pdf", page=1))


def test_scan_symlink_cannot_escape_region(tmp_path):
    service, settings = setup_review(tmp_path)
    outside = tmp_path / "elsewhere.pdf"
    synthetic_pdf(outside)
    link = settings.scan_root / "demo" / "escape.pdf"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ReviewError, match="escapes"):
        service.scans.get_scan(replace(refs()[1], pdf="escape.pdf"))

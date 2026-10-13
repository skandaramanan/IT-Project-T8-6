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


def test_queue_and_item_probe_without_rendering_or_decoding(tmp_path, monkeypatch):
    from survey.review import scans

    service, settings = setup_review(tmp_path)
    reader, calls = scans.PdfReader, []

    def observed_reader(*args):
        calls.append(args)
        return reader(*args)

    monkeypatch.setattr(scans, "PdfReader", observed_reader)
    monkeypatch.setattr(
        Image, "open", lambda *a, **k: pytest.fail("Probe decoded pixels")
    )
    monkeypatch.setattr(
        scans, "extract_image", lambda *a: pytest.fail("Queue rendered a PNG")
    )
    assert service.queue()["total"] == 5
    assert service.item(refs()[1].item_id)["allowed_actions"]
    assert len(calls) == 1  # One metadata read covers all flags/pages in this PDF.
    assert not list(settings.cache.glob("*.png"))


def test_probe_cache_invalidation_and_blank_page(tmp_path):
    service, settings = setup_review(tmp_path)
    service.scans.probe(refs()[0])
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(settings.scan_root / "demo/synthetic.pdf")
    with pytest.raises(ReviewError, match="no scan image"):
        service.scans.probe(refs()[0])
    with pytest.raises(ReviewError, match="bounds"):
        service.scans.probe(refs()[1])
    assert not service.item(refs()[0].item_id)["allowed_actions"]
    assert not service.queue()["complete"]


def test_render_failure_blocks_decisions_and_repair_invalidates_error(
    tmp_path, monkeypatch
):
    from review_support import decide

    from survey.review import scans

    service, settings = setup_review(tmp_path)
    original = scans.extract_image

    def unreadable(*args):
        raise ValueError("Image pixels cannot decode")

    monkeypatch.setattr(scans, "extract_image", unreadable)
    with pytest.raises(ReviewError, match="unreadable"):
        decide(service)
    assert not service.item(refs()[1].item_id)["allowed_actions"]
    assert service.item(refs()[1].item_id)["review_state"] == "pending"
    assert not list(settings.cache.glob("*.png"))
    monkeypatch.setattr(scans, "extract_image", original)
    synthetic_pdf(settings.scan_root / "demo/synthetic.pdf")
    assert decide(service)["saved_locally"]

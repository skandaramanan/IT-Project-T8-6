"""FR-19: combined-scan fixtures split into their expected card inputs,
including scans missing a card type.

Reuses the tests/fixtures/ set. A "combined scan" is simulated by taking
one record's page images in scan order; a missing-card scan is simulated
by dropping pages from that list -- no separate binary fixtures needed,
since the fixture set already has one real image per role.
"""

from pathlib import Path

import numpy as np
from PIL import Image

from survey.segmentation.segmenter import classify_page, segment_pages, segment_scan

FIXTURES = Path(__file__).parent / "fixtures"
RECORDS = [f"r{n:02d}" for n in range(1, 6)]


def _page(record: str, role: str) -> Path:
    return FIXTURES / f"{record}-{role}.jpg"


def test_classifies_every_fixture_role_correctly():
    for record in RECORDS:
        assert classify_page(_page(record, "survey-front")) == "front"
        assert classify_page(_page(record, "survey-back")) == "reverse"
        assert classify_page(_page(record, "coding-front")) == "numeric_coding"


def test_blank_coding_back_is_not_classified_as_a_card():
    for record in RECORDS:
        assert classify_page(_page(record, "coding-back")) is None


def test_segment_scan_splits_a_full_combined_scan():
    source = Path("1973-0002-00049-1-25-1-20.pdf")
    pages = [
        _page("r01", "survey-front"),
        _page("r01", "survey-back"),
        _page("r01", "coding-front"),
        _page("r01", "coding-back"),
    ]

    result = segment_scan(pages, source_scan=source)

    assert set(result) == {"front", "reverse", "numeric_coding"}
    assert result["front"].image_path == pages[0]
    assert result["reverse"].image_path == pages[1]
    assert result["numeric_coding"].image_path == pages[2]
    for card_type, card in result.items():
        assert card.card_type == card_type
        assert card.source_scan == source
    assert result["front"].page_index == 0
    assert result["reverse"].page_index == 1
    assert result["numeric_coding"].page_index == 2


def test_segment_scan_handles_a_survey_missing_its_numeric_coding_card():
    source = Path("survey-without-coding-card.pdf")
    pages = [_page("r02", "survey-front"), _page("r02", "survey-back")]

    result = segment_scan(pages, source_scan=source)

    assert result["front"] is not None
    assert result["reverse"] is not None
    assert result["numeric_coding"] is None


def test_segment_scan_handles_a_survey_missing_its_front_card():
    source = Path("survey-without-front.pdf")
    pages = [_page("r03", "survey-back"), _page("r03", "coding-front")]

    result = segment_scan(pages, source_scan=source)

    assert result["front"] is None
    assert result["reverse"] is not None
    assert result["numeric_coding"] is not None


def test_segment_scan_result_always_has_all_three_card_type_keys():
    result = segment_scan([], source_scan=Path("empty.pdf"))

    assert result == {"front": None, "reverse": None, "numeric_coding": None}


def _dense_unruled_page(tmp_path: Path, ink_fraction: float = 0.06) -> Path:
    """A synthetic page with no ruled lines and ink density in the
    numeric_coding range -- stands in for a reverse page with unusually
    dense handwritten notes, without adding a new binary fixture."""
    rng = np.random.default_rng(0)
    dark = rng.random((500, 800)) < ink_fraction
    pixels = np.where(dark, 0, 255).astype("uint8")
    path = tmp_path / "dense-unruled.jpg"
    Image.fromarray(pixels, mode="L").save(path)
    return path


def test_classify_page_alone_misreads_a_dense_reverse_as_numeric_coding(tmp_path):
    """Documents the failure mode segment_scan()'s position rule fixes below."""
    dense = _dense_unruled_page(tmp_path)
    assert classify_page(dense) == "numeric_coding"


def test_segment_scan_uses_position_to_resolve_a_dense_reverse_page(tmp_path):
    """Same page as above, but in position -- segment_scan() should call it
    reverse regardless of ink density alone."""
    dense = _dense_unruled_page(tmp_path)
    pages = [_page("r01", "survey-front"), dense, _page("r01", "coding-front")]

    result = segment_scan(pages, source_scan=Path("dense-notes.pdf"))

    assert result["reverse"].image_path == dense
    assert result["numeric_coding"].image_path == pages[2]


def test_segment_scan_declines_to_force_reverse_past_the_override_ceiling(tmp_path):
    """A dense first-in-run page (ink=0.15, found in the wild as typed prose,
    not a reverse) should fall back to content instead of being forced into
    "reverse" by position."""
    very_dense = _dense_unruled_page(tmp_path, ink_fraction=0.15)
    pages = [_page("r01", "survey-front"), very_dense, _page("r01", "survey-back")]

    result = segment_scan(pages, source_scan=Path("not-actually-a-reverse.pdf"))

    assert result["reverse"].image_path == pages[2]
    assert result["numeric_coding"].image_path == very_dense


def test_segment_scan_does_not_clobber_numeric_coding_with_a_stray_third_page(tmp_path):
    """A stray third page in a run (FR-21) must not overwrite the genuine
    numeric_coding page."""

    def make(name: str, ink_fraction: float) -> Path:
        rng = np.random.default_rng(0)
        dark = rng.random((500, 800)) < ink_fraction
        pixels = np.where(dark, 0, 255).astype("uint8")
        path = tmp_path / name
        Image.fromarray(pixels, mode="L").save(path)
        return path

    reverse_like = make("reverse-like.jpg", 0.03)
    numeric_coding_like = make("numeric-coding-like.jpg", 0.06)
    stray = make("stray-report.jpg", 0.06)
    pages = [_page("r01", "survey-front"), reverse_like, numeric_coding_like, stray]

    result = segment_scan(pages, source_scan=Path("stray-third-page.pdf"))

    assert result["reverse"].image_path == reverse_like
    assert result["numeric_coding"].image_path == numeric_coding_like


def _solid_dark_page(tmp_path: Path) -> Path:
    """A page that's almost entirely ink -- a divider/cover sheet scanned
    against a dark bed, or a badly cropped scan, rather than a card."""
    pixels = np.full((500, 800), 10, dtype="uint8")
    path = tmp_path / "solid-dark.jpg"
    Image.fromarray(pixels, mode="L").save(path)
    return path


def test_a_large_dark_region_is_not_mistaken_for_a_ruled_grid(tmp_path):
    """A contiguous dark block isn't a ruled grid (thin, spaced lines)."""
    assert classify_page(_solid_dark_page(tmp_path)) != "front"


def _single_thin_line_page(tmp_path: Path) -> Path:
    """A page with exactly one short thin dark band -- a fold-shadow or
    scan artefact, not a grid of several rule lines."""
    pixels = np.full((500, 800), 255, dtype="uint8")
    pixels[100:103, :] = 0  # one 3px-thick band, well under the run-length cap
    path = tmp_path / "single-line.jpg"
    Image.fromarray(pixels, mode="L").save(path)
    return path


def test_a_single_stray_line_is_not_mistaken_for_a_ruled_grid(tmp_path):
    assert classify_page(_single_thin_line_page(tmp_path)) != "front"


def test_segment_pages_keeps_every_record_in_a_multi_record_scan_in_order():
    source = Path("unit-batch.pdf")
    roles = ["survey-front", "survey-back", "coding-front", "coding-back"]
    pages = [_page(record, role) for record in ("r01", "r02") for role in roles]

    cards = segment_pages(pages, source_scan=source)

    assert [(c.card_type, c.page_index) for c in cards] == [
        ("front", 0),
        ("reverse", 1),
        ("numeric_coding", 2),
        ("front", 4),
        ("reverse", 5),
        ("numeric_coding", 6),
    ]
    assert all(c.source_scan == source for c in cards)
    assert [c.image_path for c in cards] == [pages[i] for i in (0, 1, 2, 4, 5, 6)]


def test_segment_pages_leaves_out_a_stray_third_page(tmp_path):
    """The unrecognised page is absent, so the pipeline can log and skip it."""
    rng = np.random.default_rng(0)
    paths = []
    for name, ink in [("rev.jpg", 0.03), ("cod.jpg", 0.06), ("stray.jpg", 0.06)]:
        pixels = np.where(rng.random((500, 800)) < ink, 0, 255).astype("uint8")
        Image.fromarray(pixels, mode="L").save(tmp_path / name)
        paths.append(tmp_path / name)
    pages = [_page("r01", "survey-front"), *paths]

    cards = segment_pages(pages, source_scan=Path("stray.pdf"))

    assert [c.page_index for c in cards] == [0, 1, 2]

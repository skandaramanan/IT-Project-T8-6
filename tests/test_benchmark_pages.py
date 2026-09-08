"""The C3 benchmark's page ids resolve to the page the card is really on.

Two of the transcriber's page ids point at a survey back instead of a coding
front, which scores ~0 for any extractor (see
ground_truth.SOURCE_PAGE_CORRECTIONS). This guards the correction: without it a
future edit could quietly go back to indexing the PDF by page id and the only
symptom would be two cards scoring badly, which reads like a model problem.

C3-specific by design -- the C1/C2 sheet carries its own ``pdf page`` column
and needs no correction table, which is what test_c1c2_cards_find_their_image
checks instead.

Skipped when the survey data isn't synced -- data/ is gitignored.
"""

import pytest
from ground_truth import (
    C3_GROUND_TRUTH_XLSX,
    C3_IMAGES_DIR,
    DEFAULT_GROUND_TRUTH_XLSX,
    DEFAULT_IMAGES_DIR,
    SOURCE_PAGE_CORRECTIONS,
    load_ground_truth,
)

c3_only = pytest.mark.skipif(
    not C3_GROUND_TRUTH_XLSX.exists(),
    reason=f"{C3_GROUND_TRUTH_XLSX} not synced -- see README, 'Data and secrets'",
)
c1c2_only = pytest.mark.skipif(
    not DEFAULT_GROUND_TRUTH_XLSX.exists(),
    reason=f"{DEFAULT_GROUND_TRUTH_XLSX} not synced -- see README, 'Data and secrets'",
)


def _c3():
    return load_ground_truth(C3_GROUND_TRUTH_XLSX, C3_IMAGES_DIR)


@c3_only
def test_corrected_rows_read_their_real_page():
    cards = {card.page_id: card for card in _c3()}
    for page_id, source_page in SOURCE_PAGE_CORRECTIONS.items():
        card = cards[str(page_id)]
        assert card.source_page == source_page
        assert card.image_path.name == f"page{source_page:03d}.jpg"


@c3_only
def test_uncorrected_rows_read_their_own_page():
    for card in _c3():
        if int(card.page_id) not in SOURCE_PAGE_CORRECTIONS:
            assert card.source_page == int(card.page_id)
            assert card.image_path.name == f"page{int(card.page_id):03d}.jpg"


@c1c2_only
def test_c1c2_cards_find_their_image():
    """Each row names an image that exists, and the meta columns aren't fields.

    The four meta columns sit beside 62 real fields; if one leaks through it is
    scored as a field the extractor can never get right, which silently caps
    every accuracy figure the benchmark produces.
    """
    cards = load_ground_truth(DEFAULT_GROUND_TRUTH_XLSX, DEFAULT_IMAGES_DIR)
    assert len(cards) == 30
    for card in cards:
        assert card.image_path.exists(), f"{card.page_id}: {card.image_path} missing"
        assert card.image_path.parent == DEFAULT_IMAGES_DIR
        assert not {"unit", "pdf page", "card type"} & card.fields.keys()
        assert card.page_id not in card.fields
        assert len(card.fields) == 62

"""Each benchmark row names an image that exists, and meta columns aren't fields.

The four meta columns sit beside 62 real fields; if one leaks through it is
scored as a field no extractor can ever get right, which silently caps every
accuracy figure the benchmark produces.

Skipped when the benchmark set isn't synced -- data/ is gitignored.
"""

import pytest

from ground_truth import (
    DEFAULT_GROUND_TRUTH_XLSX,
    DEFAULT_IMAGES_DIR,
    load_ground_truth,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DEFAULT_GROUND_TRUTH_XLSX.exists(),
        reason=f"{DEFAULT_GROUND_TRUTH_XLSX} not synced -- see README, 'Data and secrets'",
    ),
]


def test_cards_find_their_image():
    cards = load_ground_truth(DEFAULT_GROUND_TRUTH_XLSX, DEFAULT_IMAGES_DIR)
    assert len(cards) == 30
    for card in cards:
        assert card.image_path.exists(), f"{card.page_id}: {card.image_path} missing"
        assert card.image_path.parent == DEFAULT_IMAGES_DIR
        assert not {"unit", "pdf page", "card type"} & card.fields.keys()
        assert card.page_id not in card.fields
        assert len(card.fields) == 62

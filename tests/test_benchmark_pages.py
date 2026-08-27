"""The benchmark's page ids resolve to the page the card is really on.

Two of the transcriber's page ids point at a survey back instead of a coding
front, which scores ~0 for any extractor (see
ground_truth.SOURCE_PAGE_CORRECTIONS). This guards the correction: without it a
future edit could quietly go back to indexing the PDF by page id and the only
symptom would be two cards scoring badly, which reads like a model problem.

Skipped when the survey data isn't synced -- data/ is gitignored.
"""

import pytest
from ground_truth import (
    DEFAULT_GROUND_TRUTH_XLSX,
    SOURCE_PAGE_CORRECTIONS,
    load_ground_truth,
)

pytestmark = pytest.mark.skipif(
    not DEFAULT_GROUND_TRUTH_XLSX.exists(),
    reason=f"{DEFAULT_GROUND_TRUTH_XLSX} not synced -- see README, 'Data and secrets'",
)


def test_corrected_rows_read_their_real_page():
    cards = {card.page_id: card for card in load_ground_truth()}
    for page_id, source_page in SOURCE_PAGE_CORRECTIONS.items():
        card = cards[page_id]
        assert card.source_page == source_page
        assert card.image_path.name == f"page{source_page:03d}.jpg"


def test_uncorrected_rows_read_their_own_page():
    for card in load_ground_truth():
        if card.page_id not in SOURCE_PAGE_CORRECTIONS:
            assert card.source_page == card.page_id
            assert card.image_path.name == f"page{card.page_id:03d}.jpg"

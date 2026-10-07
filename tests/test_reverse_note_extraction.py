"""Gemini checked against the FR-05 reverse-side fixtures (IT-90).

The fixtures and their ground truth are IT-90's, in
``tests/fixtures/reverse_notes/ground_truth.json``; its format and the
verbatim rules ``expected_note`` follows are in
``test_reverse_note_fixtures.py``, which also checks the set is complete.

The comparison ignores whitespace only, so a line break typed as a space still
matches; case and punctuation count.

Skipped until the fixture set exists, and without ``GEMINI_API_KEY``.
"""

import json
import os
import re
from pathlib import Path

import pytest

from survey.association.notes import build_note_text

FIXTURES = Path(__file__).parent / "fixtures"
GROUND_TRUTH_PATH = FIXTURES / "reverse_notes/ground_truth.json"

if not GROUND_TRUTH_PATH.exists():
    pytest.skip("IT-90 reverse-side fixtures not added yet", allow_module_level=True)

CARDS = json.loads(GROUND_TRUTH_PATH.read_text())["cards"]


def _words(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="needs GEMINI_API_KEY")
@pytest.mark.parametrize(
    "back", CARDS, ids=lambda b: f"p{b['source']['page']}-{b['case']}"
)
def test_extraction_matches_ground_truth(back):
    """AC1 verbatim and AC3 blank; a note invented on a blank back fails."""
    from survey.extraction.gemini import GeminiExtractor

    result = GeminiExtractor(reverse_notes=True).extract(FIXTURES / back["image"])
    text = build_note_text(result)
    expected = back["expected_note"]
    if expected is None:
        assert text["status"] == "no_data", f"read {text['value']!r} off a blank back"
    else:
        assert text["status"] == "ok", f"got {text['status']}"
        assert _words(text["value"]) == _words(expected)

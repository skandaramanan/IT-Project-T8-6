"""The FR-05 reverse-side fixture set (IT-90) is complete and well-formed.

``tests/fixtures/reverse_notes/ground_truth.json`` holds one entry per back:

    {
      "image": "r04-survey-back.jpg",        relative to tests/fixtures/
      "case": "dense" | "sparse" | "blank" | "hard",
      "expected_note": "..." or null,        null only for a blank back
      "dwelling_no": "14",
      "record_id": "27-0014-01",
      "front_page": 13,                      the PDF page of the back's front
      "source": {"pdf": "1260908_1973-0002-00049.pdf", "page": 14}
    }

``expected_note`` follows the verbatim rules: spelling, case and punctuation
as written, struck words left out and their replacements kept,
``[illegible]`` for a word that cannot be read, line breaks as on the card.

``dwelling_no`` and ``record_id`` are read by eye off the dwelling's coding
card. Two backs may share a ``record_id``: an overflow dwelling has a front,
and so a back, per sheet.

Every ``expected_note`` and ID has been checked by a person against the scan,
never taken from extractor output (AC2). Keep it that way when adding a back.

No model is called here; running extraction against the set belongs with the
capture path (IT-89).
"""

import json
import re
from pathlib import Path

import pytest
from support import assert_intact_jpeg

FIXTURES = Path(__file__).parent / "fixtures"
GROUND_TRUTH = json.loads((FIXTURES / "reverse_notes/ground_truth.json").read_text())
CARDS = GROUND_TRUTH["cards"]
REQUIRED_CASES = {"dense", "sparse", "blank", "hard"}

BACKS = pytest.mark.parametrize(
    "back", CARDS, ids=lambda b: f"p{b['source']['page']}-{b['case']}"
)


def test_ground_truth_declares_its_schema_version():
    assert GROUND_TRUTH["schema_version"]


@pytest.mark.parametrize("case", sorted(REQUIRED_CASES))
def test_required_case_is_covered(case):
    """IT-90 AC1."""
    assert case in {back["case"] for back in CARDS}


def test_every_survey_back_in_the_record_set_is_covered():
    """The rNN records are the main fixture set; their backs are in this one too."""
    backs = {path.name for path in FIXTURES.glob("r*-survey-back.jpg")}
    assert backs <= {back["image"] for back in CARDS}


def test_each_back_appears_once():
    pages = [(back["source"]["pdf"], back["source"]["page"]) for back in CARDS]
    assert len(pages) == len(set(pages))


@BACKS
def test_back_is_well_formed(back):
    assert_intact_jpeg(FIXTURES / back["image"])
    assert back["case"] in REQUIRED_CASES
    assert back["source"]["pdf"].endswith(".pdf")
    assert isinstance(back["source"]["page"], int)
    assert isinstance(back["front_page"], int)
    assert back["front_page"] < back["source"]["page"]


@BACKS
def test_only_a_blank_back_expects_no_note(back):
    """IT-90 AC4: the blank back must expect an explicit empty, so a note
    invented on it fails, and no other back may expect one."""
    if back["case"] == "blank":
        assert back["expected_note"] is None
    else:
        assert isinstance(back["expected_note"], str)
        assert back["expected_note"].strip()


@BACKS
def test_record_id_names_the_dwelling(back):
    assert re.fullmatch(r"\d{2}-\d{4}-\d{2}", back["record_id"])
    assert int(back["record_id"].split("-")[1]) == int(back["dwelling_no"])

"""No meaningful value is silently lost over the noise fixture set (IT-95).

Two layers. The offline tests hold the fixture set to US-07's shape and prove
the diff report names what it loses, so a regression in the report itself
cannot hide a regression in extraction. The live test is the check proper:
it runs the primary extractor over the fixtures and fails on any loss, and is
skipped -- not passed -- when no API key is set.
"""

import json
import os
from pathlib import Path

import pytest
from noise_check import FIELD_NAMES, MANIFEST, find_losses, load_noise_cards

FIXTURES = Path(__file__).parent / "fixtures"
CARDS = load_noise_cards()


def test_every_card_pairs_noise_with_recorded_meaningful_values():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["cards"], "noise fixture set is empty"
    for card in manifest["cards"]:
        image = card["image"]
        assert (FIXTURES / image).exists(), f"{image} not on disk"
        assert card["noise"], f"{image} records no noise annotation"
        for entry in card["noise"]:
            assert entry["mark"], f"{image}: noise entry with no mark"
            assert entry["rule"].startswith("D020"), (
                f"{image}: noise entry cites no D020 rule: {entry}"
            )
        assert card["expected"], f"{image} records no expected values"
        unknown = set(card["expected"]) - FIELD_NAMES
        assert not unknown, f"{image} expects fields not in FIELD_SCHEMA: {unknown}"


def test_perfect_extraction_reports_no_loss():
    by_image = {card.image_path: card.fields for card in CARDS}
    assert find_losses(by_image.__getitem__, CARDS) == []


def test_report_names_the_card_and_field_that_were_lost():
    by_image = {card.image_path: dict(card.fields) for card in CARDS}
    victim = CARDS[1]
    del by_image[victim.image_path]["Number over 10 M."]
    by_image[victim.image_path]["Number 5-10"] = "7"

    losses = find_losses(by_image.__getitem__, CARDS)

    assert losses == [
        f"{victim.page_id} / Number 5-10: expected '0', got '7'",
        f"{victim.page_id} / Number over 10 M.: expected '2', got ''",
    ]


def test_report_names_noise_that_leaked_into_the_output():
    by_image = {card.image_path: dict(card.fields) for card in CARDS}
    victim = CARDS[0]
    by_image[victim.image_path]["Reviewer initials"] = "AW"

    losses = find_losses(by_image.__getitem__, CARDS)

    assert losses == [
        f"{victim.page_id} / Reviewer initials: not a field -- noise leaked as 'AW'"
    ]


@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set -- the live no-silent-loss check needs the extractor",
)
def test_primary_extractor_loses_nothing_meaningful():
    from gemini_extractor import GeminiExtractor

    extractor = GeminiExtractor()
    losses = find_losses(lambda p: extractor.extract(p).fields, CARDS)
    assert not losses, "meaningful values lost or noise leaked:\n" + "\n".join(losses)

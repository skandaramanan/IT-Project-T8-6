"""Recovery probes share outage limits without treating real fronts as failures."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from survey import pipeline
from survey.extraction.base import ExtractionResult
from survey.pipeline import MAX_FAILURE_STREAK, RunSummary, recover_coding_cards
from survey.segmentation.segmenter import CardType, SegmentedCard


class ProbeExtractor:
    name = "recovery-test"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def extract(self, path):
        self.calls.append(path)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def cards_and_readings(types):
    cards = [
        SegmentedCard(kind, Path(f"p{i + 1:04d}.png"), Path("scan.pdf"), i)
        for i, kind in enumerate(types)
    ]
    readings = {
        card: ExtractionResult(fields={"Address": ""}, raw_text="{}")
        for card in cards
        if card.card_type is CardType.FRONT
    }
    return cards, readings


def recover(cards, readings, extractor, summary, raw_dir=None):
    return recover_coding_cards(
        cards,
        readings,
        list(range(1, len(cards) + 1)),
        Path("scan.pdf"),
        extractor,
        raw_dir,
        summary,
    )


@pytest.mark.parametrize(
    "prior_failures", [0, MAX_FAILURE_STREAK - 1, MAX_FAILURE_STREAK]
)
def test_recovery_stops_at_shared_cap_and_keeps_all_cards(prior_failures):
    cards, readings = cards_and_readings(
        [CardType.FRONT, CardType.REVERSE, CardType.NUMERIC_CODING] * 6
    )
    original_readings = readings.copy()
    extractor = ProbeExtractor([RuntimeError("429 daily cap")] * 6)
    summary = RunSummary(failure_streak=prior_failures, failed_cards=prior_failures)

    recovered = recover(cards, readings, extractor, summary)

    assert len(extractor.calls) == MAX_FAILURE_STREAK - prior_failures
    assert summary.failure_streak == summary.failed_cards == MAX_FAILURE_STREAK
    assert recovered == cards
    assert readings == original_readings


def test_successful_recovery_resets_streak_and_preserves_unrelated_cards():
    cards, readings = cards_and_readings(
        [CardType.FRONT, CardType.REVERSE, CardType.FRONT, CardType.NUMERIC_CODING]
    )
    coding = ExtractionResult(
        fields={
            "Municipality": "27",
            "Number of Dwelling": "5",
            "Number of Household": "1",
        }
    )
    extractor = ProbeExtractor([coding, RuntimeError("429 daily cap")])
    summary = RunSummary(failure_streak=MAX_FAILURE_STREAK - 1, failed_cards=2)

    recovered = recover(cards, readings, extractor, summary)

    assert len(extractor.calls) == 2
    assert recovered[0].card_type is CardType.NUMERIC_CODING
    assert recovered[1:] == cards[1:]
    assert cards[0] not in readings
    assert readings[recovered[0]] is coding
    assert readings[cards[2]].fields == {"Address": ""}
    assert summary.failure_streak == 1
    assert summary.failed_cards == 3


@pytest.mark.parametrize("cached", [False, True])
def test_empty_probe_is_a_successful_negative_and_does_not_count_as_failure(
    tmp_path, cached
):
    cards, readings = cards_and_readings([CardType.FRONT] * 4)
    empty = ExtractionResult(raw_text="{}")
    extractor = ProbeExtractor([empty] * 4)
    if cached:
        recover(cards, readings, extractor, RunSummary(), raw_dir=tmp_path)
        extractor.calls.clear()
    summary = RunSummary(failure_streak=MAX_FAILURE_STREAK - 1, failed_cards=2)

    assert recover(cards, readings, extractor, summary, raw_dir=tmp_path) == cards

    assert len(extractor.calls) == (0 if cached else 4)
    assert summary.failed_cards == 2
    assert summary.failure_streak == 0


def test_main_extraction_exhaustion_prevents_recovery_requests(monkeypatch):
    cards, _ = cards_and_readings([CardType.FRONT] + [CardType.NUMERIC_CODING] * 3)
    monkeypatch.setattr(
        pipeline, "PdfReader", lambda _: SimpleNamespace(pages=[None] * 4)
    )
    monkeypatch.setattr(pipeline, "extract_image", lambda *args: None)
    monkeypatch.setattr(pipeline, "segment_pages", lambda *args, **kwargs: cards)
    monkeypatch.setattr(
        pipeline, "build_dwelling_records", lambda *args, **kwargs: ([], [], [])
    )
    extractor = ProbeExtractor([RuntimeError("429 daily cap")] * 4)
    front = ProbeExtractor([ExtractionResult(fields={"Address": ""})])
    summary = RunSummary()

    assert (
        pipeline._run_pdf(
            Path("scan.pdf"), "north", extractor, front, None, None, None, summary
        )
        == []
    )

    assert len(extractor.calls) == MAX_FAILURE_STREAK
    assert summary.failure_streak == summary.failed_cards == MAX_FAILURE_STREAK

"""Confidence is optional, and None means something different from {}.

FR-10 requires a score on every extracted field. D008 makes it optional on the
interface because a VLM has none to give -- so the two empty cases have to stay
distinguishable: None is "this engine can't", {} is "this engine can, but this
card came back with nothing". Collapse them and nothing downstream can tell an
engine that fails FR-10 from one that had a bad card, which is what IT-99 AC4
turns on.
"""

from extraction.base import ExtractionResult


def test_confidence_defaults_to_none_not_empty():
    assert ExtractionResult().confidence is None
    assert ExtractionResult().fields == {}  # fields keeps the {}-not-None rule


def test_an_engine_that_scores_nothing_is_not_an_engine_that_cannot():
    can_but_didnt = ExtractionResult(fields={"Tenure": "3"}, confidence={})
    cannot = ExtractionResult(fields={"Tenure": "3"})
    assert can_but_didnt.confidence == {}
    assert cannot.confidence is None

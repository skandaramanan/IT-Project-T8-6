"""IT-108: the review-routing check (FR-11, D022).

One group of tests per acceptance criterion, plus a guard that the cutoff still
tracks D016's ``agree`` constant.
"""

import pytest
from confidence import CONFIDENCE_BY_CLASS
from dual_extract import AGREE

from extraction.field_schema import FIELD_SCHEMA_BY_NAME
from extraction.record import build_field
from review.routing import AGREE_CONFIDENCE, needs_review


def field(status: str, confidence: float | None) -> dict:
    return {"value": "1", "status": status, "confidence": confidence}


def test_confident_clean_field_is_left_alone():
    """AC1."""
    assert needs_review(field("ok", 0.97)) is False


@pytest.mark.parametrize("confidence", [0.91, 0.75, 0.74, 0.14, 0.0])
def test_low_score_is_flagged(confidence):
    """AC2: single-extractor, disagree, one_blank and weaker."""
    assert needs_review(field("ok", confidence)) is True


def test_missing_score_is_flagged():
    """AC2."""
    assert needs_review(field("ok", None)) is True


@pytest.mark.parametrize("status", ["no_data", "illegible", "damaged", "omitted"])
@pytest.mark.parametrize("confidence", [0.97, 1.0, 0.5, None])
def test_unclean_status_is_always_flagged(status, confidence):
    """AC3: status decides, whatever the score. Both-blank fields score 0.97."""
    assert needs_review(field(status, confidence)) is True


def test_missing_keys_are_flagged():
    """Fail closed: a field object with no status or score is not evidence of a
    good read."""
    assert needs_review({}) is True
    assert needs_review({"status": "ok"}) is True
    assert needs_review({"confidence": 0.97}) is True


def test_cutoff_tracks_d016_agree_constant():
    """D022: the cutoff is D016's ``agree``, not a free-standing 0.97."""
    assert AGREE_CONFIDENCE == CONFIDENCE_BY_CLASS[AGREE]


def test_freshly_built_fields_are_flagged_today():
    """D022 Consequences: build_field emits confidence None until D016's scores
    reach real records, so every field routes to review."""
    spec = FIELD_SCHEMA_BY_NAME["Municipality"]
    assert needs_review(build_field(spec, "27")) is True
    assert needs_review(build_field(spec, "")) is True

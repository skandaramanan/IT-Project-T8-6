"""Per-field review routing (FR-11, D022, IT-108)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from survey.confidence.agreement import AGREE
from survey.confidence.field import CONFIDENCE_BY_CLASS

# D016's `agree` score, so the cutoff moves when D016 is recalibrated (D022).
AGREE_CONFIDENCE = CONFIDENCE_BY_CLASS[AGREE]


def needs_review(field: Mapping[str, Any]) -> bool:
    """True unless the field is `ok` with confidence >= `agree`.

    Status is checked first. A missing score or key counts as needing review.
    """
    if field.get("status") != "ok":
        return True
    confidence = field.get("confidence")
    if confidence is None:
        return True
    return confidence < AGREE_CONFIDENCE

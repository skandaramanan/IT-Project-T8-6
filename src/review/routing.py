"""Per-field review routing (FR-11, D022, IT-108)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Copy of D016's `agree` score; src/ can't import spike/. A test checks they match.
AGREE_CONFIDENCE = 0.97


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

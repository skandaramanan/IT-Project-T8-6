"""Interface every candidate model (local or hosted) implements.

Every extractor returns structured ``fields``. A card the model fails on
scores as an empty dict, not a different output shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from extraction.field_schema import FieldStatus


@dataclass
class ExtractionResult:
    fields: dict[str, str] = field(default_factory=dict)  # {} on failure, not None
    raw_text: str | None = None  # diagnostic only -- what the model said; never scored
    cost_usd: float | None = None  # estimated cost for this one card, if known

    # Per-field confidence, keyed by the same names as ``fields``. FR-10 makes
    # a score on every extracted field a Must, and D007's output envelope has
    # nowhere else to get one from.
    #
    # Unlike ``fields``, None and {} mean different things and the difference
    # is the point:
    #   None  the engine cannot produce confidence at all
    #   {}    the engine can, but returned none for this card
    # A local VLM answering None is not a bug -- it is evidence that FR-10 is
    # unsatisfiable with that engine, which decides between candidates
    # independently of how accurately they read the digits.
    confidence: dict[str, float] | None = None

    # The visual outcome of reading each field.  This remains separate from
    # confidence: a low-confidence readable value is still ``ok``, while an
    # illegible cell has no value at all.  None preserves compatibility with
    # extractors that use the legacy flat-value prompt.
    statuses: dict[str, FieldStatus] | None = None


class Extractor(Protocol):
    name: str

    def is_available(self) -> bool:
        """False if a dependency/API key/model is missing — runner skips it, doesn't crash."""
        ...

    def extract(self, image_path: Path) -> ExtractionResult: ...

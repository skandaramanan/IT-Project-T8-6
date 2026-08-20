"""Interface every candidate model (local or hosted) implements.

Every extractor returns structured ``fields``. A card the model fails on
scores as an empty dict, not a different output shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ExtractionResult:
    fields: dict[str, str] = field(default_factory=dict)  # {} on failure, not None
    raw_text: str | None = None  # diagnostic only -- what the model said; never scored
    confidence: dict[str, float] | None = None  # keyed like fields; None if unsupported


class Extractor(Protocol):
    name: str

    def is_available(self) -> bool:
        """False if a dependency/API key/model is missing — runner skips it, doesn't crash."""
        ...

    def extract(self, image_path: Path) -> ExtractionResult: ...

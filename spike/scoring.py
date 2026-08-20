"""Scores one extraction result against its ground truth card: exact-match
accuracy per field.
"""

from __future__ import annotations

from dataclasses import dataclass

from ground_truth import BenchmarkCard


@dataclass
class StructuredScore:
    page_id: int
    total_fields: int
    correct_fields: int
    mismatches: list[tuple[str, str, str]]  # (field, expected, got)

    @property
    def accuracy(self) -> float:
        return self.correct_fields / self.total_fields if self.total_fields else 0.0


def score_structured(card: BenchmarkCard, predicted: dict[str, str]) -> StructuredScore:
    mismatches: list[tuple[str, str, str]] = []
    correct = 0
    for field, expected in card.fields.items():
        got = (predicted.get(field) or "").strip()
        if got == expected.strip():
            correct += 1
        else:
            mismatches.append((field, expected, got))
    return StructuredScore(
        page_id=card.page_id,
        total_fields=len(card.fields),
        correct_fields=correct,
        mismatches=mismatches,
    )

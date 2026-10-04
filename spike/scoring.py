"""Scores one extraction result against its ground truth card: exact-match
accuracy per field.
"""

from __future__ import annotations

from dataclasses import dataclass

from ground_truth import BenchmarkCard
from survey.extraction.record import normalise


@dataclass
class StructuredScore:
    page_id: str
    total_fields: int
    correct_fields: int
    # (field, expected, raw, got) -- raw is what the model literally returned,
    # got is that after normalise(). Both, because a mismatch CSV showing only
    # the cleaned value hides the difference between a model that read "B" and
    # one that read nothing, which is the first thing a reviewer needs.
    mismatches: list[tuple[str, str, str, str]]
    # Fields where the card actually carries a code. An extractor that returns
    # nothing scores well on the empty ones, so this is the number that
    # separates candidates -- report it next to the headline accuracy.
    coded_fields: int = 0
    correct_coded_fields: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct_fields / self.total_fields if self.total_fields else 0.0


def score_structured(card: BenchmarkCard, predicted: dict[str, str]) -> StructuredScore:
    mismatches: list[tuple[str, str, str, str]] = []
    correct = coded = correct_coded = 0
    for field, expected in card.fields.items():
        raw = predicted.get(field)
        want = normalise(expected)
        got = normalise(raw)
        if want:
            coded += 1
        if got == want:
            correct += 1
            correct_coded += bool(want)
        else:
            mismatches.append((field, expected, raw or "", got))
    return StructuredScore(
        page_id=card.page_id,
        total_fields=len(card.fields),
        correct_fields=correct,
        mismatches=mismatches,
        coded_fields=coded,
        correct_coded_fields=correct_coded,
    )

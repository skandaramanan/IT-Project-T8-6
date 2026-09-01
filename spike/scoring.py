"""Scores one extraction result against its ground truth card: exact-match
accuracy per field.
"""

from __future__ import annotations

from dataclasses import dataclass

from ground_truth import BenchmarkCard

# Three ways of writing "this cell holds no numeric code", which all have to
# compare equal:
#   ""  the transcriber left it blank      (page 203's empty Family 4 block)
#   "-" the transcriber marked it          (page 169's empty Family 3 block)
#   "B" the 1940s coder voided the cell on the card itself, one B per code
#       column -- so "B", "BB", "BBB". The transcriber wrote those as "-", but
#       an extractor reading the card faithfully reports the B it can see.
# Scoring these against each other measures transcription punctuation, not
# extraction. 247 of 1200 ground-truth fields are "-" or "--"; no ground-truth
# value is ever a "B", so treating a returned B as no-value can't hand out
# credit for a real code -- a B where the card holds a digit still mismatches
# that digit.
VOID_MARKS = frozenset("-Bb")


def _normalise(value: str) -> str:
    """Void marks collapse to "no code". Leading zeros are left alone.

    Deliberate: the ground-truth sheet is text-formatted so "04" and "4" are
    two different transcriptions, and the code book's fixed-width codes make
    them two different codes. Stripping zeros here would quietly hand an
    extractor credit for reading "4" off a cell that says "04" --
    test_leading_zero_is_not_the_same_code guards it.
    """
    stripped = value.strip()
    # all-void-marks (or empty) means no code, however it was written
    return "" if set(stripped) <= VOID_MARKS else stripped


@dataclass
class StructuredScore:
    page_id: str
    total_fields: int
    correct_fields: int
    mismatches: list[tuple[str, str, str]]  # (field, expected, got)
    # Fields where the card actually carries a code. An extractor that returns
    # nothing scores well on the empty ones, so this is the number that
    # separates candidates -- report it next to the headline accuracy.
    coded_fields: int = 0
    correct_coded_fields: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct_fields / self.total_fields if self.total_fields else 0.0


def score_structured(card: BenchmarkCard, predicted: dict[str, str]) -> StructuredScore:
    mismatches: list[tuple[str, str, str]] = []
    correct = coded = correct_coded = 0
    for field, expected in card.fields.items():
        want = _normalise(expected)
        got = _normalise(predicted.get(field) or "")
        if want:
            coded += 1
        if got == want:
            correct += 1
            correct_coded += bool(want)
        else:
            mismatches.append((field, expected, got))
    return StructuredScore(
        page_id=card.page_id,
        total_fields=len(card.fields),
        correct_fields=correct,
        mismatches=mismatches,
        coded_fields=coded,
        correct_coded_fields=correct_coded,
    )

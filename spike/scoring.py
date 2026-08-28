"""Scores one extraction result against its ground truth card: exact-match
accuracy per field.
"""

from __future__ import annotations

from dataclasses import dataclass

from ground_truth import BenchmarkCard

# Ways of writing "this cell holds no numeric code", which all have to
# compare equal:
#   ""     the transcriber left it blank      (page 203's empty Family 4 block)
#   "-"    the transcriber marked it          (page 169's empty Family 3 block)
#   "None" ground-truth representation for no_data fields (Facilities Shared,
#          House No. of Families O/C.) -- the GT is inconsistent between "" and
#          "None" for absent slots; treat them the same.
#   "B"    the 1940s coder voided the cell on the card itself, one B per code
#          column -- so "B", "BB", "BBB". The transcriber wrote those as "-",
#          but an extractor reading the card faithfully reports the B it sees.
# Scoring these against each other measures transcription punctuation, not
# extraction. 247 of 1200 ground-truth fields are "-" or "--"; no ground-truth
# value is ever a "B", so treating a returned B as no-value can't hand out
# credit for a real code -- a B where the card holds a digit still mismatches
# that digit.
VOID_MARKS = frozenset("-Bb")
_ABSENT_WORDS = frozenset({"None", "none", "NONE"})


def _normalise(value: str) -> str:
    stripped = value.strip()
    if stripped in _ABSENT_WORDS or set(stripped) <= VOID_MARKS:
        return ""
    # Strip leading zeros from purely numeric values so "04" == "4".
    # Safe for scoring: no two distinct valid codes within any field collapse
    # to the same string after stripping (verified against code_book.py).
    # Decode concern: fields whose code book keys are zero-padded (Municipality,
    # Rent/Age/Length-of-Residence sentinels) need the zeros re-added before
    # calling decode() -- use the expected key width per category, not this
    # normalised form, as the lookup key.
    if stripped.isdigit():
        return str(int(stripped))
    return stripped


@dataclass
class StructuredScore:
    page_id: int
    total_fields: int
    correct_fields: int
    mismatches: list[tuple[str, str, str, str]]  # (field, expected, raw, got)
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
        raw = predicted.get(field) or ""
        got = _normalise(raw)
        if want:
            coded += 1
        if got == want:
            correct += 1
            correct_coded += bool(want)
        else:
            mismatches.append((field, expected, raw, got))
    return StructuredScore(
        page_id=card.page_id,
        total_fields=len(card.fields),
        correct_fields=correct,
        mismatches=mismatches,
        coded_fields=coded,
        correct_coded_fields=correct_coded,
    )

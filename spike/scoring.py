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

# Every value on this card is a number: the code book defines no code containing
# a letter or a period. That is what makes the two substitutions below safe --
# neither can turn one valid code into a different valid code, so neither can
# hand out credit for a wrong answer. Both were measured on the first Azure run
# (2026-09-01, 20 held-out cards), where together they accounted for 305 of 731
# apparent mismatches -- 25 accuracy points of pure scoring artefact.

# The printed fields are joined to their values by a row of dots, and OCR reads
# some of them as part of the number: "1." for 1, "1.5." for 15. Colons come off
# the "Children of H. or wife:" heading the same way.
_PUNCTUATION = str.maketrans("", "", ".:;, \t\n")

# Handwritten 0 and 1 are read as letters: O 29x, Q 16x, ! 14x, L 6x, I 3x.
# Deliberately not included: "/" and "D", which are plausible lookalikes but
# were never observed -- an unobserved mapping is a guess, and a guess here
# only ever inflates the score.
_DIGIT_LOOKALIKES = str.maketrans(
    {"O": "0", "o": "0", "Q": "0", "I": "1", "l": "1", "L": "1", "!": "1", "|": "1"}
)


def _normalise(value: str) -> str:
    """Strip print/OCR artefacts. Leading zeros are left alone.

    Zeros are deliberately kept: the ground-truth sheet is text-formatted so
    "04" and "4" are two different transcriptions, and the code book's
    fixed-width codes make them two different codes. Stripping them would hand
    an extractor credit for reading "4" off a cell that says "04" --
    test_leading_zero_is_not_the_same_code guards it. That is the difference
    between the two rules here and that one: "04" and "4" are both valid codes
    with different meanings, whereas "1." and "O" are not codes at all.
    """
    stripped = value.strip().translate(_PUNCTUATION)
    # all-void-marks (or empty) means no code, however it was written. Checked
    # before folding so a coder's "B" stays a void mark rather than a digit.
    if set(stripped) <= VOID_MARKS:
        return ""
    return stripped.translate(_DIGIT_LOOKALIKES)


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

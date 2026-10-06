"""One confidence score per card, from its field scores (IT-85, FR-20).

FR-10 (IT-99) puts a number on every one of a card's 62 fields. FR-20 wants
one number for the whole card, so a reviewer can triage cards without reading
62 fields each, and a run can be summarised per card.

**The rule, stated once:** the card's confidence is the mean of its weakest
quarter of fields -- sort the field scores ascending, take the lowest
``ceil(n / 4)`` (16 of 62), average them. Same 0.0-1.0 range and meaning as
the field score: "how likely the reading is correct", for the fields a
reviewer most needs to look at.

Why not the plain mean: it hides bad fields. 56 fields at 0.97 and 6 at 0.14
average to 0.89, which reads as a clean card; the bottom quarter averages to
0.66, which does not. Why not the minimum: one faint cell and twenty faint
cells both give the card its single worst score, so the reviewer cannot rank
them. The quartile sits between the two -- pulled down by a few weak fields,
not floored by one. Working in docs/decisions/D018-card-level-confidence.md.

Deliberately not done here:

- **A threshold.** NFR-03's accept/reject line is not set (IT-63); nothing
  here depends on it, and "fraction of fields above threshold" was rejected
  for exactly that reason.
- **Writing into a D007 record.** ``backend/survey/extraction/record.py`` still emits
  ``cards[].confidence: None``; that changes when D007 is amended, not here.
- **Run-level rollups.** One card, one number.
"""

from __future__ import annotations

from collections.abc import Iterable
from math import ceil


def card_confidence(scores: Iterable[float]) -> float:
    """Mean of the lowest quarter of ``scores``, in 0.0-1.0.

    An empty card -- no fields scored at all -- is 0.0: no evidence, the same
    reading ``confidence_for`` gives a field neither arm read. A card whose
    fields are all blank is *not* empty; its fields carry the ``both_blank``
    constant and it scores that, which is what AC5 asks for.

    Raises TypeError on a non-numeric score and ValueError on one outside the
    range. A bad input silently folded into the mean would hand out a number
    that means nothing, which is worse than no number (NFR-01).
    """
    checked = []
    for score in scores:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise TypeError(f"field confidence must be numeric, got {score!r}")
        if not 0.0 <= score <= 1.0:
            raise ValueError(f"field confidence {score} is outside 0.0-1.0")
        checked.append(score)
    if not checked:
        return 0.0
    checked.sort()
    k = max(1, ceil(len(checked) / 4))
    return round(sum(checked[:k]) / k, 2)


def assert_every_card_scored(records: Iterable[dict]) -> None:
    """AC1. Raises rather than warns -- a card that reaches a reviewer with no
    score is indistinguishable from one that scored well.

    Over the finished records, not each card as it is built: that is what
    catches a record appended by some later code path that forgot the score.
    """
    for record in records:
        score = record.get("card_confidence")
        page_id = record.get("page_id")
        assert isinstance(score, (int, float)) and not isinstance(score, bool), (
            f"{page_id}: card confidence must be numeric, got {score!r}"
        )
        assert 0.0 <= score <= 1.0, (
            f"{page_id}: card confidence {score} is outside 0.0-1.0"
        )

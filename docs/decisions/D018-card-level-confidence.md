# D018 — Card-level confidence: the aggregation rule

**Status:** Accepted, provisional — pending the NFR-03 threshold (IT-63)
**Date:** 2026-09-13
**Decided by:** Qitao Shi (IT-85 assignee)
**Linear issue:** IT-85

## Context

FR-10 (IT-99, D016) attaches a confidence score to every one of a coding
card's 62 fields. FR-20 asks for one more score per card, so that a reviewer
can triage whole cards without reading 62 fields each, and so a run can be
summarised at the card level. D007 already reserves the slot —
`cards[].confidence`, 0.0–1.0, nullable — but nothing fills it.

The issue's requirements for the rule: deterministic, documented in-repo,
same range and meaning as the field score, and — the one that does the work —
"a few bad fields on an otherwise clean card are not hidden".

## Decision

**The card's confidence is the mean of its weakest quarter of fields.** Sort
the field scores ascending, take the lowest `ceil(n / 4)` — 16 of 62 — and
average them. Rounded to two decimals, matching the field constants.

Implemented as `card_confidence()` in `spike/card_confidence.py`.

Worked on D016's constants (agree 0.97, disagree 0.75, one_blank/low 0.14):

| Card | Plain mean | Min | **Bottom-quartile mean** |
| -- | -- | -- | -- |
| 62 × 0.97 | 0.97 | 0.97 | **0.97** |
| 61 × 0.97, 1 × 0.14 | 0.96 | 0.14 | **0.92** |
| 56 × 0.97, 6 × 0.14 | 0.89 | 0.14 | **0.66** |
| 50 × 0.97, 8 × 0.75, 4 × 0.14 | 0.89 | 0.14 | **0.65** |
| 62 × 1.0 | 1.0 | 1.0 | **1.0** |
| 62 × 0.0 | 0.0 | 0.0 | **0.0** |

Rows two and three are the decision. Six fields a reviewer would not trust
sit on a card the plain mean calls 0.89; the quartile calls it 0.66. One such
field on an otherwise clean card is 0.92, not 0.14 — a reviewer can rank the
two, which the minimum cannot do.

### What the number means

The same thing the field score means (D016): the measured probability that a
reading is correct — here, for the fields a reviewer most needs to look at.
A card at 0.66 says "the sixteen fields you should check first are, on
average, two-thirds likely to be right". It is not the probability the whole
card is correct, and it is not the fraction of fields that are.

### Edge cases

- **All-blank card (AC5).** Every field falls in `both_blank`, which D016
  scores 0.97, so the card scores 0.97. Blank is a scored class, not missing
  data, and the card score does not second-guess that.
- **No fields at all.** 0.0 — the same value D016's `confidence_for` gives a
  field neither arm read. No evidence, no confidence. Distinct from all-blank:
  the former has no readings, the latter has 62 corroborated ones.
- **Fewer than four fields.** `max(1, ceil(n / 4))`, so the quartile is never
  empty; a single field's card is that field's score.
- **A non-numeric or out-of-range score raises** rather than being skipped.
  Skipping would hand out a number that means nothing, which NFR-01 forbids.

## Alternatives considered

**Plain mean.** Rejected by the issue and by the table above: 0.89 for a card
with six untrustworthy fields is the false confidence NFR-01 exists to
prevent.

**Minimum field score.** Honest but blunt. Every card with one faint cell
scores the same as a card with twenty, so it cannot rank cards for triage,
which is the whole point of a card score. It is also hostage to D016's
weakest constant: on the flash-lite pairing 22 of 1,860 fields are
`one_blank`/low (0.14), spread across cards, so most cards would floor at
0.14 and the number would stop discriminating.

**Geometric mean.** Penalises low scores more than the arithmetic mean, but a
single 0.0 field — a card neither arm read — collapses it to 0.0 regardless
of the other 61, and the penalty otherwise stays mild: 56 × 0.97 and 6 × 0.14
gives 0.80, still a card that reads as fine.

**Fraction of fields at or above threshold.** The issue's other suggestion,
and a good one once a threshold exists. NFR-03's threshold is not set — it
waits on IT-63 — and a rule that cannot be evaluated today is not a rule.
Revisit below.

**A quarter versus another cut.** Sixteen fields is roughly the number a
reviewer can check on one card in one sitting, and on a dense card (D016:
1,834 of 1,860 fields carry a code) it is deep enough that a handful of
`disagree` or `one_blank` fields all land in it. A smaller cut approaches the
minimum; a larger one approaches the mean. No cut was measured against
reviewer behaviour; this is a judgement, marked provisional.

## Consequences

- Every card record from a paired run can carry `card_confidence` in
  0.0–1.0, alongside the per-field scores. Wiring into `pair_cards()`
  (`spike/dual_extract.py`) follows IT-99's merge, not this record.
- `src/extraction/record.py` still writes `cards[].confidence: None`. D007's
  field object has no `source_agreement` key, so the per-field triple cannot
  land in a real record yet; the card score waits for the same amendment
  rather than arriving ahead of the fields it is derived from.
- A card's score can only be as good as D016's constants. Every "revisit if"
  in D016 applies here by inheritance.

## Revisit if

- **NFR-03's threshold is set (IT-63).** "Fraction of fields at or above
  threshold" becomes computable and speaks the reviewer's language directly
  ("58 of 62 fields accepted"). The quartile mean may stay as the number and
  the fraction be reported beside it, or replace it; decide then.
- **D007 is amended** to carry `source_agreement`. The card score goes into
  `cards[].confidence` in the same change.
- **Reviewers say the ranking is wrong.** The cut is a judgement; if the
  cards reviewers send back do not match the cards this ranks lowest, the
  quarter is the first thing to move.

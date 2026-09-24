# D022 — Review-routing rule (FR-11)

**Status:** Proposal, on hold pending client confirmation (see Open question)
**Date:** 2026-09-23
**Proposed by:** Elliot Guo (IT-107 assignee)
**Linear issue:** IT-107

## Open question

The client has not confirmed that FR-11 routes by score at all (IT-107 hold
comment, see IT-64). Two alternatives are open:

- **No threshold:** every field goes to the review queue, and this rule is
  not needed.
- **Disagreement-based:** a card is queued if the extractors disagree on any
  field.

This note is the rule **if** a per-field score cutoff is chosen. Do not build
IT-108 against it until the client answers.

## The rule

A field goes to review unless **all** of these hold:

1. `status == "ok"`
2. `confidence` is not `null`
3. `confidence >=` D016's `agree` constant (currently **0.97**)

Status is checked first. A high score never overrides a non-`ok` status.

## Why

**Only a clean double-agreement clears.** `agree` (both extractors read the
same non-blank value) is D016's highest score. Everything below it, a person
checks. This is research data, so the bar is "maximally sure."

**The cutoff tracks the `agree` constant, not the literal 0.97.** When D016
is recalibrated, the cutoff moves with it. A hardcoded 0.97 would send every
field to review the moment `agree` dropped to 0.96. The principle is fixed;
the number is not.

**A missing score is the worst case, not a neutral one.** Raw-OCR engines
give no per-field score (D007), and that is not evidence the read is good.

**Blank fields always go to review.** Both-blank fields score 0.97 in D016
but carry `status: no_data`, so they route on status. The score is left
alone: it is D016's to set, D018 depends on it, and lowering it would change
no outcome.

**A cutoff of 0.5 was rejected.** It would clear `disagree` (0.75),
`one_blank` (0.74) and single-extractor fields (0.91), about a quarter of
which are wrong.

## Examples

| `status` | `confidence` | Review? | Why |
| -- | -- | -- | -- |
| `ok` | `0.97` | No | Both extractors agreed. |
| `ok` | `0.91` | Yes | Only one extractor read the card. |
| `ok` | `0.75` | Yes | The extractors disagreed. |
| `ok` | `null` | Yes | No score. |
| `no_data` | `0.97` | Yes | Both blank. Status decides. |
| `illegible` / `damaged` / `omitted` | any | Yes | Status decides. |

## Assumes banding is off

This note assumes `GEMINI_CONFIDENCE_BAND` stays off (the default). The band
was meant for when only one model reads a card. With two models, agreement
supplies that signal, and the band costs a separate prompt and 2.5 points of
flash-lite accuracy (D016 §5). Single-model fields score 0.91 and route to
review regardless, so the band would not change their outcome here.

The trade-off: with the band off, every field the models agree on clears,
including the few Gemini would have rated hard to read (D016 §6 measured
`agree`/medium at 91% correct, against 97% overall).

If banding is adopted, revisit this note first. D016 falls back to the flat
`agree` score (0.97) for fields Gemini rates `low`, because it has too few
samples for that case, so they would clear. The fix belongs in D016, not
here: this rule never sees the band.

## Out of scope

- How confidence is computed (D016) or who wins a disagreement (D021).
- **Unexplained codes.** D011 calls a null `label` on a `categorical` field
  the FR-11 signal to review. Such fields stay `ok` and clear here. Adding it
  is one condition, deferred until the Open question is answered.
- **NFR-03's threshold (IT-63).** If it lands per field, it and this cutoff
  should be one number.
- Building the check: IT-108.

## Consequences

- Every field currently has `confidence: None`, so **every field routes to
  review today**. That is correct, and it stops once D016's scores reach real
  records.
- Every `no_data` field routes to review, which adds volume on sparse cards.

## Revisit if

- The client answers the Open question. A card-level answer supersedes this
  note.
- D007 gains real `confidence` values (the `source_agreement` amendment).
- Banding is adopted. See "Assumes banding is off".
- NFR-03's threshold is set. Reconcile the two numbers.
- Unexplained codes need routing (D011).

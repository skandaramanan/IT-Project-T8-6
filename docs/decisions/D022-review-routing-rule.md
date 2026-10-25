# D022 — Review-routing rule (FR-11)

**Status:** Accepted, client confirmed agreement-based routing (2026-10-02 meeting)
**Date:** 2026-09-23
**Proposed by:** Elliot Guo (IT-107 assignee)
**Linear issue:** IT-107

## Client confirmation

In Client Meeting #4 on 2026-10-02 the client confirmed that when both extractors
agree on a field, it does not need to be added to the review queue. Everything
else is still queued. This settles the earlier open question in favour of
routing by agreement, so the per-field cutoff below is the rule. The "no
threshold" (queue every field) and card-level disagreement alternatives are
not adopted.

IT-108 can build against this rule.

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
  is one condition, deferred.
- **NFR-03's threshold (IT-63).** If it lands per field, it and this cutoff
  should be one number.
- Building the check: IT-108.
- **Dwelling flags.** D007 0.5.0 writes `dwelling.flags` and can leave
  `record_id` null. This rule is per field and doesn't read them, so a
  flagged household whose fields both extractors agree on would clear. The
  queue (IT-109) should route a flagged dwelling's identity fields whatever
  they score.

## Consequences

- Every field currently has `confidence: None`, so **every field routes to
  review today**. That is correct, and it stops once D016's scores reach real
  records.
- Every `no_data` field routes to review, which adds volume on sparse cards.

## Revisit if

- The client changes their answer on agreement-based routing.
- D007 gains real `confidence` values (the `source_agreement` amendment).
- Banding is adopted. See "Assumes banding is off".
- NFR-03's threshold is set. Reconcile the two numbers.
- Unexplained codes need routing (D011).

## IT-125 recalibration (17 October 2026)

D016 Addendum D replaces the flat `agree` constant with **0.98** (1,486/1,523
correct, 97.57%, rounded) for unbanded Flash-Lite × normalized Q6_K / 2MP.
The existing check imports that constant, so its cutoff follows the measured
configuration. All current disagreement and standalone constants are strictly
below it; regression tests assert this and the exact boundary. Both-blank is a
reasoned fallback with no Q6 benchmark observations and stays in review through
`status: no_data`. No score on an omitted field is treated as agreement.

This is the existing interim clean-agreement policy, evaluated on the available
30-card development benchmark. It is **not** a proven 99% corpus accuracy promise:
37/1,523 agreeing benchmark fields were wrong, the sheet is single-keyed, and
there is no held-out evaluation. Field skip-share reports distinguish this
policy eligibility from the review queue's additional identity flags and human
decisions. Unsupported C3 fields and Gemini-only identity recovery receive zero
in the merge, so neither can clear from apparent double agreement. Front fields
remain uncalibrated and null. Banded low-sample fallbacks are retained for scoring
but are not validated for a new banded review-bypass policy.

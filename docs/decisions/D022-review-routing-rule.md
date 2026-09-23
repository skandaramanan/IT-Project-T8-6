# D022 — Review-routing rule (FR-11)

**Status:** Pending.
**Date:** 2026-09-23
**Decided by:** Elliot Guo (IT-107 assignee)
**Linear issue:** IT-107

## Context

FR-11 says fields below a confidence/status threshold should be routed to a
human review queue, but doesn't say what "too low" means. This note defines
that rule. It does not compute confidence (D016/IT-99) or resolve
disagreements between the two extractors (IT-86/D021) — both are decided
elsewhere.

## The rule

A field is routed to review unless **all** of these hold:

- `status == "ok"`
- `confidence` is not `null`
- `confidence >= 0.97`

Anything else — a non-`ok` status, a missing score, or a score below
0.97 — goes to review.

## Why 0.97

0.97 is D016's measured accuracy for a genuine double-agreement (both
extractors read the same value, `agree` or `both_blank`). Setting the
cutoff there means **only a clean double-agreement clears automatically;
everything else, a person decides.** This is research data, so the bar is
"maximally sure," not "probably fine."

**The rule works the same whether or not Gemini's optional confidence band
is turned on, with no extra logic needed:**

- **Band off (today's default).** `agree`/`both_blank` always score exactly
  0.97, so the rule clears real double-agreements and nothing else.
- **Band on.** Gemini additionally self-rates each field's legibility
  (`high`/`medium`/`low`). A field where the extractors agreed but Gemini
  itself flagged the handwriting as only medium-legible now scores 0.91 —
  below the cutoff — so it drops out of "clears automatically" and goes to
  review, correctly.

Either way, the cutoff never has to change: 0.97 already sits above every
banded or unbanded score except a fully-confident agreement, so turning
banding on only ever makes the rule stricter, never looser.

An earlier draft used 0.5 ("more likely right than wrong"). Rejected: it
let every plain disagreement between the two extractors (0.75) clear
automatically, which is too permissive for a research dataset — a quarter
of those fields are wrong.

**This is still a placeholder**, tied to D016's benchmark constant rather
than a corpus-scale measurement. If that constant moves, this cutoff should
move with it — see Revisit if.

## Examples

| `status` | `confidence` | Review? | Why |
| -- | -- | -- | -- |
| `ok` | `0.97` | No | Clean double-agreement. |
| `ok` | `0.91` | Yes | Agreed, but Gemini flagged its own read as uncertain. |
| `ok` | `0.75` | Yes | The two extractors disagreed. |
| `ok` | `null` | Yes | No score at all is treated as the worst case, not a neutral one. |
| `no_data` / `illegible` / `damaged` / `omitted` | any | Yes | Status alone is enough — a high score can't override a bad read. |

## Out of scope

- How confidence is computed (D016/IT-99) or which arm wins a disagreement
  (D021/IT-86) — this rule just consumes their output.
- An unexplained code on an otherwise-`ok` categorical field (`code_book.py`,
  D011) can still score 0.97 and clear, even though it's a real
  data-quality flag. Not covered here — see Revisit if.
- Building the actual check that applies this rule — a follow-up ticket.

## Consequences

Every field today has `confidence: None` (D016's scoring isn't wired into a
real record yet), so under this rule **every field currently routes to
review**. That's the correct behavior, not a bug — it stops once D016's
scores reach a real record.

## Revisit if

- A full benchmark run gives a real cutoff to tune against — retune 0.97
  to it.
- D007 gains a real `confidence`/`source_agreement` — then this rule starts
  actually discriminating instead of flagging everything.
- The unexplained-code signal needs its own rule (see Out of scope).

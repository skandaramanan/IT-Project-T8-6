# D023 — Resolving struck options: negation vs. correction

**Status:** Accepted
**Date:** 2026-09-17
**Decided by:** Jacob Ng (IT-92 assignee)
**Linear issue:** IT-92

## Context

IT-80, meant to get a client ruling on crossed-out-as-negation versus
crossed-out-as-correction, was canceled without a resolution. FR-06 still
requires resolution to run.

The hand-classified fixtures resolve every recorded struck field to a null
value, regardless of whether the struck digit is still legible underneath the
mark. Detection (IT-91) reports one boolean per field; there is no signal that
could tell resolution "two values are present here, one struck," only "this
field's value is struck."

## Decision

Resolution reads two signals per field: its cleaned value, and the per-field
`struck` flag detection produces.

- Not struck: unchanged, `negated: false`.
- Struck: `negated: true`, `value`/`code`/`label` null, `status: "no_data"` —
  regardless of whether the struck digit is still legible.
- No detector ran: no `negated` key at all. `false` would claim the option was
  read and found unstruck, which is the claim `omitted` already exists to avoid
  on a field the extractor never returned. This is the `None` versus `{}`
  distinction `ExtractionResult.struck` carries, preserved through to the
  record.

Identity fields — Municipality, Number of Dwelling, Number of Household — are
exempt and never negate, whatever detection reports. `record_id` is built from
all three, so negating one yields a record that cannot be identified or traced
back to its card.

No new schema key or status value. `negated` is exactly the flag D007 already
reserved for this.

## Alternatives considered

**Branch on whether the struck value is still legible.** Rejected — the
fixtures resolve legible and illegible strikes identically; legibility isn't
the axis that distinguishes anything here.

**A `conflict`/review status for a struck field with a coexisting unstruck
value.** Considered, since AC3 describes exactly this case. Rejected:
detection's signal shape (one value, one bool) cannot represent "two values
were present" in the first place, so resolution never has the information to
tell that case apart from a clean strike — there is nothing to branch on.

## Consequences

- A struck option coexisting with an affirmatively marked one is not
  distinguishable from a clean strike, and resolves the same way (negated).
  That is a property of the detection signal we chose — one boolean per field —
  not of the problem itself. A richer signal would make the case
  representable; this decision does not close it.
- "Every option in a question struck" is likewise unrepresentable: the signal
  is per field, not per option, so a fully struck question looks like a struck
  field. Not resolved here.
- A strike detected on an identity field is discarded without trace. On a
  genuinely voided card that is lost information, which is the failure US-06
  exists to prevent — accepted for now because the alternative is an
  unidentifiable record.

## Revisit if

Detection gains a signal richer than one boolean per field (e.g. flagging that
more than one value is present in a cell) — then a real conflict/review case
becomes representable and this decision should be revisited.

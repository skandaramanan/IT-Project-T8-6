# D029 — Review fields persist in JSONL and share through review-data

**Status:** Implementation of the supplied review handoff; pending team rollout
**Date:** 2026-10-11
**Linear issue:** IT-113
**Amends:** D007, D025, D026 for the bounded review backend

The supplied handoff chooses no database: region JSONL remains authoritative,
with an in-memory queue index for direct field lookup. Teammate flags select
fields; the backend does not generate/rank a queue. IT-113's older database
wording must be reconciled with this choice before integration sign-off.

Schema `0.3.0` adds optional field `review` metadata with a separate
pending/accepted/corrected state and append-only decision/undo history. Snapshots
exclude history. Accepted payloads remain extraction payloads; mutations retain
original machine value and confidence. Existing `0.1.0` example and `0.2.0`
records remain readable. Untouched files are not migrated at startup.

D026 protection now includes active acceptance and correction, and preserves
history when undo leaves a field pending. Pending values can be extracted again,
while legacy corrected payloads remain protected. Audit snapshots are never
traversed as live fields. Household regrouping/order changes still refuse unsafe
attachment; partial-rebuild and failed-front protections remain.

D025's open branch question is resolved by the handoff: same repository,
`review-data` branch, separate checkout, normal direct pushes, no PR per batch.
Code changes still follow D002's reviewed PR convention. Provisioning/rules and
credentials are user/admin responsibilities. CI validates after push; local
validation precedes commit. No bypass, force push, auto-merge or data discard.

V1 supports one active dataset writer. Physical identity is region/PDF/page;
shared fields belong to the first coding household. Identity and existing negated
fields are accept-only. Front/person/handwritten/negation editing and shared-field
reconciliation are deferred. See [the runbook](../review-backend.md) for API,
launch, synthetic demo, deployment gates and recovery.

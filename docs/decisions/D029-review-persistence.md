# D029 — Review fields persist in JSONL and share through review-data

**Status:** Implementation of the supplied review handoff; pending team rollout
**Date:** 2026-10-11
**Linear issue:** IT-113
**Amends:** D007, D025, D026 for the bounded review backend

The supplied handoff chooses no database: region JSONL remains authoritative,
with an in-memory queue index for direct field lookup. Teammate flags select
fields; the backend does not generate/rank a queue. IT-113's older database
wording must be reconciled with this choice before integration sign-off.

Schema `0.4.0` adds optional field `review` metadata with a separate
pending/accepted/corrected state and append-only decision/undo history. Snapshots
exclude history. Accepted payloads remain extraction payloads; mutations retain
original machine value and confidence. IT-89 retains `0.3.0` for dwelling notes
and is now included from main after merging #50. Existing `0.1.0`,
`0.2.0`, and IT-89 `0.3.0` records remain readable, including verbatim dwelling
notes. Earlier versions cannot contain review metadata; this constraint is checked
by the shared Python validator rather than a recursive JSON Schema legacy tree.
Untouched files are not migrated at startup.

D026 protection now includes active acceptance and correction, and preserves
history when undo leaves a field pending. Pending values can be extracted again,
while legacy corrected payloads remain protected. Audit snapshots are never
traversed as live fields. Household regrouping/order changes still refuse unsafe
attachment; partial-rebuild and failed-front protections remain.

D025's open branch question is resolved by the handoff: same repository,
`review-data` branch, separate checkout, normal direct pushes, no PR per batch.
Code changes still follow D002's reviewed PR convention. Provisioning/rules and
credentials are user/admin responsibilities. CI validates after push; local
validation precedes commit. No bypass, force push, automatic same-region merge
or data discard.
When upstream and local changes touch disjoint region files, the backend commits
local work and rebases only unpushed commits onto the fetched remote. Overlapping
regions stop for manual reconciliation. A non-fast-forward push retries once with
a fresh fetch and the same overlap checks; authentication failures do not retry.

V1 supports one backend writer per data checkout. Reviewers on separate machines
or checkouts can share different regions concurrently; assign one owner per region
to avoid manual reconciliation. An OS lock protects each checkout, and a short
in-process lock serializes its saves and Git checkout updates. Network operations
and validation of changed incoming region blobs run outside the save lock.

Full validation and card/audit indexes are built once after acquiring the startup
writer lock. Each review decision validates only its changed dwelling and checks
audit IDs against cached indexes before atomically replacing the region JSONL.
Incoming updates replace only affected region/index entries. Card lookup uses a
physical-card dictionary; batch completion uses cached counters, invalidated when
source scans change. JSONL serialization/replacement still covers the region.

Physical identity is region/PDF/page; shared fields belong to the first coding
household. Identity and existing negated
fields are accept-only. Front/person/handwritten/negation editing and shared-field
reconciliation are deferred. See [the runbook](../review-backend.md) for API,
launch, synthetic demo, deployment gates and recovery.


## Rebase onto IT-89 (13 October 2026)

IT-113 was rebased onto `origin/main` at `c43a97f`, which includes IT-89 PR #50.
The original branch tip is preserved locally at
`refs/backup/it-113-before-main-rebase-928ee1b`. No remote history was rewritten.

Conflict resolutions and integration decisions:

- Keep both `survey extract --notes` and the `review`/`validate-results` commands.
- Keep IT-89's extraction, back-card provenance, omitted-back fallback and note
  ownership updates. Corrected notes follow their `front_page` when a front is
  gained or note order changes; review protection is applied after that mapping.
- Keep accepted/corrected coding payloads and their append-only histories across
  reruns. Undo-to-pending preserves history while allowing a new extraction value.
- Keep `0.3.0` as IT-89's notes version. Review metadata requires `0.4.0` or
  later; the builder and example are at `0.6.0` since IT-123 (D007).
- Per the user's explicit decision, `0.3.0` onward rejects household-level
  notes. Only `0.1.0`/`0.2.0` retain read compatibility for that legacy shape.
  Reviewing such a record is blocked with a migration diagnostic before any write.
  Move the notes explicitly using verified front/back provenance; do not discard
  their text or invent page associations merely to upgrade a schema version.
- Update the synthetic review fixture to canonical dwelling notes with matching
  synthetic front/back pages. This keeps unflagged-note preservation exercised
  against the same structure the extractor now writes.

Validation covers both upstream notes tests and review regressions, including one
rerun preserving a corrected note after a front is added and retaining either an
active coding review or its pending undo history. Legacy-note migration refusal
also verifies the original file and note text remain unchanged.

Post-rebase verification: Ruff lint/format and whitespace checks pass. The full
combined suite reports **589 passed, 14 skipped, 2 failed**. The failures remain
the two pre-existing local confidence-benchmark data checks documented in the
runbook; no notes or review regression failed. CLI smoke checks expose both
`extract --notes` and `review`. Native Windows/remote CI remains pending.

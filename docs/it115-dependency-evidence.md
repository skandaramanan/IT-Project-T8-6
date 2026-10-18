# IT-115 dependency evidence

Rechecked 19 October 2026. This maps the actual backend contract to evidence;
it does not introduce a separate approval ceremony or change Linear statuses.
IT-115 depends on functioning IT-109 queue output, IT-112 saves and IT-113 state.
An In Progress dependency ticket alone does not establish a broken integration.

## Storage contract: IT-111

The implemented model is [D029](decisions/D029-review-persistence.md):
authoritative regional JSONL stores current fields and review history; an
in-memory index supplies direct retrieval. A decision validates and atomically
replaces JSONL, then publishes the new index state. Restart rebuilds the index.
There is no SQLite database, second durable working copy or dual-write process.

| Criterion | Evidence | Assessment |
| --- | --- | --- |
| AC1: full field/state/actor/time directly retrievable | D029, item/history API; `test_direct_lookup_never_reads_source_batch` fails if lookup reads JSONL; `test_current_uses_card_index_without_scanning_region` fails on a linear scan | Implemented and regression-covered under D029 |
| AC2: authoritative-record boundary and synchronization explicit | D029; atomic-failure and stale-version regressions; index publication occurs only after successful durable replacement | Implemented boundary documented; old ticket database wording needs the proposed correction |

The old IT-111 and IT-113 descriptions still say database/SQLite. That wording
does not describe this implementation. The exact replacement is prepared in
[proposed updates](it115-proposed-updates.md#proposed-it-111-and-it-113-storage-wording).
Do not build a new database to satisfy superseded wording or silently mark that
wording reconciled while the remote ticket remains unchanged.

## Correction contract: IT-112

| Criterion | Concrete proof |
| --- | --- |
| AC1: new value appears in export | `test_generated_queue_decisions_restart_export_regeneration_and_undo`; production-copy browser correction and JSONL readback |
| AC2: `origin: corrected` and `original_value` retained | `test_repeated_correction_original_value_and_latest_undo`; actual walkthrough export has `value: "009"`, `origin: "corrected"`, `original_value: "10"` |
| AC3: every other record unchanged | Generated-queue contract deep comparison; production-copy comparison restores the one selected field and required schema version then asserts equality of the entire region |

Confidence and original payload remain available. Supplying real digits for a
previously illegible/no-data field changes status to readable/`ok`; code/label
are recomputed where appropriate. The actual machine original and snapshots
remain in history. See D029 and `tests/test_review_service.py`.

## State contract: IT-113

| Criterion | Concrete proof |
| --- | --- |
| AC1: full current field/state directly retrievable | No-JSONL-read and indexed-lookup regressions above |
| AC2: amendment updates current lookup and authoritative record | Generated-queue HTTP contract asserts immediate decision response and persisted JSONL; failed-save regression asserts neither index nor file advances |
| AC3: value/state/actor/time survive reopening | Actual backend process restart in the walkthrough; generated-queue restart contract; `test_actions_persist_and_only_change_second_household` |
| AC4: regenerated queue retains progress | `test_queue_refresh_preserves_progress_and_stale_collisions`, `test_regenerated_flags_keep_last_reviewer_from_removed_decisions`; production regeneration/Undo evidence |

The generated assignment removes resolved entries; it does not delete their
history from records. Keep the original assignment when reopening or undoing a
resolved item. An empty new assignment is valid but is not proof that the entire
corpus is reviewed.

## Current evidence and actual remaining actions

Current command results are in [verification](it115-verification.md). The
[computer-use walkthrough](it115-walkthrough.md) records execution as automated
technical evidence, with screenshots and export. Human fields remain blank.

- Backend functionality has technical evidence; assess it against the criteria
  above rather than repeating implementation work or inventing owner sign-off.
- Apply the proposed IT-111/113 wording through the normal owner review when
  remote edits are authorized. This session keeps those edits local.
- TC-M07 human evidence, PR delivery and the separately requested Jacob Windows
  check remain as described in [acceptance](it115-acceptance.md). IT-116's unaided
  Archives usability session is downstream, not an added IT-115 dependency.

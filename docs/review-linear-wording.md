# Prepared IT-111/112/113 wording corrections

Prepared 14 October 2026 against the descriptions read from Linear. These are
reviewable replacements; no issue description, status or teammate message was
changed. Keep dependencies, existing acceptance goals and issue ownership.

## IT-111 — storage decision

Replace the database/SQLite mandate and dual-store synchronization wording with:

> D029 chooses authoritative region JSONL with a cached in-memory physical-card,
> field and audit index. There is no database or independently durable queue store.
> Startup validates/indexes the dataset once; field reads use those indexes. Review
> saves atomically persist the changed record's payload and append-only history in
> its region JSONL, then install validated indexes. Review state, actor and time
> survive restart through embedded field review metadata. Queue input selects scope;
> refreshing supplied flags does not reset saved decisions. Region versions and
> exact request replay protect stale or uncertain editors. Same-region Git overlap
> stops for manual reconciliation; different regions may share through review-data.

AC1 remains direct retrieval of current payload/state without rereading batch
files. AC2 should say JSONL is the sole durable authority and the validated memory
index reflects atomic save results; remove the requirement for two stores to sync.
Link D029 and `docs/review-backend.md` as the implementation decision/runbook.

## IT-112 — save-a-correction

Correct the schema path to `schema/record-envelope.schema.json`. Replace the
paragraph saying the screen calls the save logic directly with:

> The reviewer calls the versioned ReviewService API. RecordStore validates and
> atomically replaces the region JSONL; the memory index updates only after a
> successful save. Correction preserves original machine value, confidence,
> provenance and negation, sets status to ok and origin to corrected, and resolves
> code/label only for fields with established codebook mappings. Numeric input
> retains exact digits/zeros; supported text retains Unicode and line breaks.
> Accept keeps the stored payload. No-data/illegible, attribution, append-only
> history, exact retries and latest-applicable undo are provided by IT-113's service.

Retain AC1–AC3. Clarify that repeated corrections preserve the original machine
value rather than overwriting original_value with a previous human correction.
Workflow policy stays in ReviewService; RecordStore owns validated atomic writes.

## IT-113 — review index/service

Replace "a database holding every flagged field's full value" with:

> Implements D029's in-memory review index over authoritative region JSONL. A
> supplied physical-card flag resolves only to a supported field and verified
> source owner. Current payload/state reads use validated indexes; decisions and
> undo persist immediately with append-only attribution/history. Restart rebuilds
> indexes from JSONL. Fresh queue scope retains stored decisions and keeps stale,
> unsupported and ambiguous references visible. Region versions and stable exact
> retries prevent overwriting stale edits. Sharing uses a separate review-data Git
> checkout with normal pushes and explicit same-region conflict reporting.

Update AC2's "updates both store and record" to "atomically persists the record
and installs its validated memory index after save success". Retain AC1/3/4.
State supported coding fields, uniquely owned front dwelling fields and verified
IT-89 notes; person columns and ambiguous multi-front ownership remain unsupported.
No damaged action or coding-back field contract is added. Keep delivery gates:
verified IT-109 production queue merge, live frontend/corpus reconciliation,
provisioned data branch/rules/credentials, user-operated Windows acceptance and
IT-116 unaided usability evidence. Passing developer tests does not close these.

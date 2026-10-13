# IT-113: local review backend

The review store indexes region JSONL in memory for direct lookup. Region JSONL
is the only durable record: each field's current payload and append-only audit
history are replaced together in one atomic file save. There is no database or
separate progress file. This follows the supplied implementation handoff;
IT-113's older database wording needs to be reconciled with this storage choice.

Backend implementation and synthetic acceptance are separate from live rollout.
Real-data acceptance requires extracted records and teammate flags. Deployment
also requires a provisioned data branch, direct-push rules, Git credentials, and
a Windows desktop smoke test. This implementation does not provision those.

## Setup and launch

Install Git and uv once. In the **code checkout**, run:

```sh
uv sync --locked
uv run survey validate-results "../survey-review-data/results"
uv run survey review --scan-root "/path/to/downloaded/scans" \
  --data-checkout "../survey-review-data" --flags "/path/to/flagged-fields.jsonl"
```

Open `http://127.0.0.1:8765`; add `--open-browser` to wait for readiness and open
the default browser. No Gemini key or extraction is required. Missing paths,
records, flags, wrong branches, and another application writer produce explicit
diagnostics. `/api/health` reports readiness and startup errors. A supplied file
with invalid flags remains visible as unresolved diagnostics.

The code checkout and data checkout must be separate. Run the code from an
editable installation (`uv sync --locked`); launching from another working
directory still finds the schema and packaged static assets. Wheel distribution
is not the v1 installation method (D024).

Configuration comes from CLI arguments or the code checkout's `.env`:

| CLI | Environment | Default |
| --- | --- | --- |
| `--scan-root` | `SURVEY_REVIEW_SCAN_ROOT` | required; contains region/PDF |
| `--data-checkout` | `SURVEY_REVIEW_DATA_CHECKOUT` | required; Git root, `results/` below |
| `--flags` | `SURVEY_REVIEW_FLAGS` | required; supplied flagged JSONL |
| `--cache` | `SURVEY_REVIEW_CACHE` | OS temp directory / `survey-review-scans` |
| `--data-branch` | `SURVEY_REVIEW_DATA_BRANCH` | `review-data`; main/master refused |
| `--sync-interval` | `SURVEY_REVIEW_SYNC_INTERVAL` | 180 seconds |
| `--port` | `SURVEY_REVIEW_PORT` | 8765; bound to 127.0.0.1 |

Cache must be outside both Git checkouts. Scans are retrieved on demand from
`scan_root/region/pdf`, using the original one-based PDF page and existing image
extraction. No bulk scan preprocessing is required. Source metadata invalidates
cached images when a PDF changes; clear the external cache if moving/replacing
scans while preserving file metadata. Original PDFs remain untouched.

Queue/item metadata requests probe PDF presence, page bounds and image metadata
without rendering PNGs. Metadata is cached per PDF fingerprint; PNGs are generated
when the reviewer requests a scan and reused from disk on later views. A loading
indicator disables decisions until the image loads. Saving also verifies that
the selected original can decode; rendering failures keep the item unresolved.
If first-card loading proves too slow in acceptance, revisit rendering latency
and consider preloading the next card in the queue. Preloading is not enabled.

On Windows, set the three required path variables once (or fill `.env`). Create
a shortcut to `scripts\review.cmd`. The launcher uses the already installed
`.venv\Scripts\survey.exe`, waits for readiness, and opens the browser. It does
not update dependencies at ordinary launch. Paths with spaces are quoted. Errors
stay in the console. Stop with Ctrl+C; close the console after the application
stops. If the port is occupied, stop the existing backend or choose another port.
Use one backend process per data checkout. Reviewers in different regions may
run separate checkouts concurrently; avoid assigning the same region to two
reviewers.

## Synthetic demonstration

From the code checkout, choose a **new empty directory outside this repository**:

```sh
uv run python scripts/review_demo.py "/tmp/survey-review-demo"
```

On Windows, use e.g. `"C:\Temp\survey-review-demo"`. The script prints a launch
command. It creates an explicitly synthetic two-household dwelling, a two-page
synthetic PDF, three flags, a separate data checkout, and a local bare Git remote.
It never contacts GitHub or runs an extractor. Use the printed command, enter a
name, and review the second household's rent. Try `009`, accept, no data, and
illegible; inspect history and undo. Stop and restart with the same command to
verify resume. `Share now` and `Save & Exit` upload only to that local remote.
Batch completion also requests synchronization.

To exercise a retained-upload failure, rename the demo's `remote.git` directory
while the app is stopped, reopen, make a decision and request sharing. The page
reports that local data is retained. Restore the remote path and share again.
Do this only with the disposable synthetic demo.

## Real scans with a manually selected test queue

The repo already has an illustrative r01 record and real fixture JPEGs. For a
test without extraction, adapt that example to its original downloaded PDF:

```sh
uv run python scripts/review_fixture.py "/tmp/survey-r01-review-test" \
  --scan-root "/Users/ericzhang/Downloads/Wilfred_Prest_Survey_Data"
```

Choose a new empty directory. The helper verifies that original PDF pages 1-4
match the committed r01 JPEG streams byte-for-byte, adapts a copy to schema 0.4.0
and original region/PDF provenance, and marks illustrative confidence scores as
unknown. It retains the example's values/annotations and legacy correction; it
does not certify them as a new extraction or ground truth. Weekly Rent, Age of
Head and Sex of Head are manually flagged on original page 3. Follow the printed
launch command (port 8876). Sharing goes to the local test remote. The sample has
one dwelling/one household and does not verify multiple-household ownership.

Queue generation need not be ready. Once an extracted regional JSONL exists,
prepare a separate local test using explicitly selected field names:

```sh
uv run python scripts/review_sample.py "/actual/path/216412.jsonl" \
  "/tmp/survey-real-review-test" \
  --scan-root "/Users/ericzhang/Downloads/Wilfred_Prest_Survey_Data" \
  --field "Weekly Rent" --field "Garden" --households 2
```

Replace the first path with an existing extracted file. Choose a new empty test
directory outside the code checkout and scan root. The helper copies complete
dwellings containing up to two matching households, retaining household indexes,
all fields and any existing history. It writes `manual-flags.jsonl` with a manual
test reason, seeds a separate `review-data` checkout and a **local** `remote.git`,
and prints the review launch command (default port 8875). It does not extract
records, rank confidence, modify source records/scans or contact GitHub.

Use `--pdf BASENAME.pdf` and repeated `--page N` to select specific original cards.
Only each household's first coding card owns its stored fields; shared fields
are selected only on household zero. Page bounds/readability are checked by the
review backend when opened. If extraction has not produced regional JSONL yet,
that remains the prerequisite; PDFs alone are insufficient. Windows paths differ.

## Teammate flag contract

Each nonblank line is an object with exactly these keys, plus optional `reason`:

```json
{"region":"demo","pdf":"synthetic.pdf","page":2,"field_path":"/dwelling/households/1/coding/weekly_rent","reason":"Synthetic test"}
```

This is a synthetic example, not a real transcription. Region and PDF are plain
names; page is a positive integer. Household indexes must match the physically
identified card's current owner. Shared `/dwelling/house/...` and identity fields
belong to the first coding household and its first coding card. Other household
cards cannot review independently stored copies of a shared field. The mapping
allowlist is the existing C1/C2 `FIELD_MAP`; front, handwritten, person and reverse
fields are not editable.

Card identity is `(region, PDF basename, original PDF page)`. Item ID combines
that physical identity with the logical field path (excluding household index).
`record_id` is for display. A stale pointer is reported, never redirected. Exact
duplicate references are deduplicated; stale, malformed, missing, unsupported or
ambiguous entries stay unresolved. Missing or unreadable scans prevent decisions.

Default batches are `(region, PDF)`. Progress derives from the supplied flags;
it does not certify an entire card or unflagged fields. Unknown-region diagnostics
are shown even under a region filter so malformed input cannot disappear.
The queue is loaded at startup. Replace the flagged file and restart to change
scope; the domain `replace_queue` method also accepts a fresh list without
resetting stored decisions. Existing region versions still protect mid-edit saves.

## Frontend HTTP contract

When `frontend/dist/index.html` exists, `/` serves the IT-115 React reviewer and
its built assets. Otherwise it serves the original integration test page.
See [reviewer-ui.md](reviewer-ui.md) for build and disposable-test instructions.
Use the same loopback origin. No wildcard CORS is enabled. For React development,
proxy `/api` through this origin, or serve a built frontend on this origin. Another
origin requires an explicit backend change and security review. Typed names are
attribution, not authenticated identities. Session cookies are HttpOnly and
SameSite=Strict, and expire with the backend process; re-enter a name after restart.
Mutation requests must be JSON and use an allowed loopback host/origin.

| Method and path | Response / behavior |
| --- | --- |
| `GET /api/health` | readiness, startup diagnostics, supported scope |
| `POST /api/session` | `{ "name": "Jane Smith" }`; sets session cookie |
| `GET /api/regions` | regions with record/scan-folder availability and batches |
| `GET /api/queue?region=demo&batch=synthetic.pdf` | items, diagnostics, totals, completion, explicit scope |
| `GET /api/review-items/{id}` | current field, label, allowed actions, warnings, version, scan URL |
| `GET /api/scans/{card_id}` | exact original scan image; opaque identifier only |
| `POST /api/review-items/{id}/decisions` | versioned/idempotent decision; response below |
| `GET /api/review-items/{id}/history` | embedded audit events |
| `POST /api/decisions/{id}/undo` | latest applicable item decision only |
| `GET /api/sync/status` | pending, known remote SHA, pushed SHA/time, error |
| `POST /api/sync` | immediate sharing attempt; requires reviewer session |

Open `/docs` for generated OpenAPI documentation, or `/openapi.json` for tooling.
Example from a same-origin frontend:

```js
await fetch('/api/session', {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({name: 'Jane Smith'})
});
const queue = await (await fetch('/api/queue?region=demo')).json();
const item = queue.items[1];
const request = {
  action: 'correct', value: '009', expected_version: item.version,
  request_id: crypto.randomUUID()
};
const response = await fetch(`/api/review-items/${item.id}/decisions`, {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(request)
});
const result = await response.json();
if (!response.ok) throw new Error(result.error.message); // retain entered value
// Advance only now: result.saved_locally === true.
```

A successful decision returns:

```json
{
  "saved_locally": true,
  "replayed": false,
  "item": {"id":"opaque-id","version":"region-digest","review_state":"corrected","field":{"value":"009","status":"ok","confidence":null}},
  "decision": {"id":"uuid","request_id":"client-id","action":"correct","reviewer":"Jane Smith","timestamp":"2026-10-11T08:00:00+00:00"},
  "sync": {"state":"waiting_to_upload","pending":true}
}
```

The example abbreviates the full field and audit event. Mutations reject extra
properties such as a payload reviewer name; attribution comes from the session.
Accept/no_data/illegible omit `value`. Undo sends only `expected_version` and
`request_id` to `/api/decisions/{decision-id}/undo`. The browser retains the original
undo target, version and request ID across network failures or uncertain server
errors. A confirmed conflict clears that retry and reloads the current item.

Each request ID is unique across the dataset. Retry **the same complete request**
(including original version) after an uncertain response. The prior saved decision
is returned with `replayed: true` and the current authoritative item. No duplicate
audit event is added; reusing an ID with different input/name/item is a conflict.
If later decisions occurred, the returned item may be newer than the replayed
decision's snapshot. A new intentional decision needs a new ID/current version.
A fresh equivalent decision on an already identical review state returns `no_op`
and appends nothing. Any region change invalidates an editor's saved version.

Errors always have `{ "error": { "code": "stable_code", "message": "readable" } }`:
401 missing session; 403 unexpected host/origin; 404 missing item/scan; 409 stale
version/external change/request reuse/undo conflict; 422 invalid/unsupported input;
500 failed local save; 503 unready backend. Sync returns structured failure status
with local data retained, so a saved decision never becomes an apparent failed
save merely because its upload failed.

The test page keeps typed input after failed saves and supports a reload that
retains it. It displays audit history and undo, basic image zoom, supplied-scope
progress, and local vs remote status. Save & Exit waits for a sharing attempt;
pending work requires explicit acknowledgement before the page says it may close.
Closing a tab does not reliably run sharing. Local decisions were already saved.

To amend a saved no-data or illegible decision, select the field, enter digits and
choose **Save correction**. **Accept stored value** preserves the stored value
and extraction status, including an empty or illegible value. It is disabled while
the correction input differs from the stored value, preventing accidental
acceptance of the old payload instead of saving the entered amendment. Repeating
an identical decision displays an informational message and adds no audit event.

## Durable data and reruns

New builders use schema `0.4.0`. IT-89 has landed on main and owns `0.3.0` for
`dwelling.notes`. Existing `0.1.0`, `0.2.0`, and IT-89 `0.3.0` records remain
readable. Review upgrades only the changed record; startup does not rewrite files.
Old versions cannot carry review metadata: the shared Python validator checks this
during its field traversal, without the expensive recursive JSON Schema legacy
check. Use `survey validate-results` for the complete validation contract.
Downstream consumers must accept optional `review` metadata before live rollout.

Earlier disposable demos from this PR used `0.3.0` for review metadata. Preserve
those directories and create a fresh test with the updated helper, or explicitly
upgrade a backed-up copy of reviewed records to `0.4.0` and run `validate-results`.
Any legacy household notes also require explicit migration to dwelling-level
notes before the record can be valid at `0.4.0`. Do not relabel IT-89 records or
overwrite an existing test checkout.

`review.state` is pending/accepted/corrected and independent of extraction status.
History records decision/request IDs, reviewer, backend UTC time, action,
before/after payload and state, request input, and undo target when applicable.
Snapshots exclude review/history. Acceptance keeps extraction payload unchanged.
Validation checks request/value consistency, empty or illegible decision payloads,
preserved provenance, continuous active snapshots, undo targets, and duplicate
audit IDs across the dataset. CLI validation, startup and synchronization share
the same audit index, with both conflicting locations reported. Incoming Git
snapshots are validated before advancing Git or replacing the affected indexes.
Full validation runs on initial load and external imports. Normal review saves
validate only the changed dwelling and check new audit IDs against cached indexes;
they still serialize and atomically replace the regional file.
A pending field may change after re-extraction;
its next decision snapshots the new payload rather than altering old history.
Corrections preserve original machine value across repeated edits, confidence,
source and negation metadata. Human digits bypass OCR normalization; zeros and
unknown codes are retained. Only closed categories warn about unlisted codes;
ordinary numeric-sentinel values need no label. Sentinel meanings come from the
existing field-specific codebook, never a generic `999 => missing` rule.

Identity and existing negated fields are accept-only: if wrong, leave pending.
Missing `negated` means unknown; no false value is manufactured. Handwritten,
person and front values remain intact during review. Negation editing and
multi-card shared-field reconciliation are deferred scope decisions.

Undo restores the latest active decision's exact prior payload/state and appends
an event. Successive undos can walk backwards through active decisions; audit
events are never deleted. Reruns preserve accepted/corrected payloads and all
history, plus legacy `origin: corrected` fields. Pending history after undo may
receive a fresh extraction payload; legacy corrections remain protected. Field
traversal skips audit snapshots. Unsafe household order/grouping changes refuse
the merge. Existing partial-rebuild protection and failed-front fallback remain.

## Git deployment and recovery

Code runs in its code checkout; data writes use `results/<region>.jsonl` in a
separate checkout on `review-data`. An OS file lock in that checkout's Git
directory refuses a second app writer and releases on process exit/crash.
Extraction and external tools must not write concurrently. Separate reviewer
checkouts may share different regions on the same branch. The lock is local to
the checkout; it does not reserve regions across machines. Assign region owners
to reduce accidental overlapping work.

Synchronization compares incoming region paths with all local dirty and unpushed
region paths, using their common Git ancestor. Disjoint changes are safe to share:
the backend commits local edits, rebases only unpushed commits onto the fetched
remote, installs the changed regions, and pushes normally. Same-region overlap
stops even when reviewers changed different fields. Both local and remote work
are retained for manual reconciliation; there is no force push or automatic
same-region merge. A non-fast-forward push retries once after a fresh fetch and
repeating all checks. Authentication/network errors retain pending work.

Only incoming changed JSONL blobs and newly added external region files need
full validation during sync. Validation uses immutable Git blobs outside the save
lock. Under a short lock, sharing rechecks local changes and audit collisions,
commits/rebases the checkout, and installs only affected region/card/audit indexes.
Existing validated local files receive digest checks instead of full schema
validation. Saves during incoming validation are included when safe; saves during
push remain pending for the next attempt unless included in a rejection retry.
Unexpected, deleted, renamed, conflicted paths or unrelated unpushed commits are
refused. Empty commits are avoided.
Git errors do not return raw stderr or credential-bearing remote URLs to browsers.

Admin/client rollout checklist:

1. After the code/schema workflow is reviewed, create `review-data` from that
   compatible revision in `git@github.com:skandaramanan/IT-Project-T8-6.git`.
2. Seed validated extracted JSONL; exclude scans, raw extraction outputs and secrets.
3. Scope branch rules so authorized reviewers can push directly to `review-data`
   while main stays protected. Broad organization rules may require admin action.
   PR-only rules must not block this chosen data-branch workflow.
4. Configure Git credentials and `user.name`/`user.email` on each reviewer machine.
   Reviewer names stay separate from Git commit identity. Verify a disposable,
   authorized direct push before live use.
5. Clone/check out the data branch separately; verify its origin is the intended
   same repository. Point the app at that root. Enable Actions permissions.
6. Confirm post-push `Validate review data` runs. A pushed SHA is **not** a claim
   that CI passed; failures require team follow-up, never automatic rollback.
7. Verify one Windows shortcut with paths containing spaces, scan rendering,
   browser opening, port collision, saves/undo/restart, credentials and failed-push
   retention. Windows CI covers synthetic filesystem/Git/API behavior, not desktop
   acceptance. CI has been added; its remote outcome is not locally verified.
8. Agree that the data branch is the canonical reviewed dataset. Incorporation
   into main is a separate deliberate workflow, with no PR per review batch.

On sync conflict, stop the app, preserve both local and remote work, and reconcile
with a teammate. On external file change, restart only after investigating the
other writer; stale edits must not overwrite it. On missing scan, fix the precise
source PDF/page; never substitute a neighboring page. Disk/permission failures
leave the previous region file intact and never return local-save success.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, and
`uv run pytest --cov=survey --cov-branch --cov-report=term-missing` follow existing
CI practice. New review tests use synthetic builders/PDFs and local bare remotes:
record validation/ownership, all actions and restrictions, versions/idempotency,
atomic failures, undo, reruns, scans, API sessions/security, two-clone disjoint
sharing, same-region conflicts, bounded push retries, and saves during incoming
validation or push. No automated test added here calls a live model.

The baseline on 11 October 2026 was 399 passed, 7 skipped, 2 failed. Both failures
are local benchmark-data checks in `tests/test_confidence.py`:
`test_constants_still_match_the_benchmark` divides by zero with no paired
observations; `test_both_blank_is_still_too_thin_to_measure` finds 1,860
NO_SECOND_OPINION observations. They predate this branch and are not suppressed.

Local implementation evidence (11 October 2026): the full coverage run completed
with **473 passed, 7 skipped, 2 failed**, matching the two baseline benchmark
failures above; overall reported coverage was 90%. All 74 new review tests passed.
Lint and formatting passed. Browser QA verified the second household's exact
original PDF page, leading zeros, sharing to the synthetic bare remote,
restart/resume, durable undo, and a stale-version rejection that retained typed
input until an explicit reload and successful retry. A separate read-only smoke
check extracted page 1 of an available original 227-page regional PDF without
changing its size or modification time. That proves local scan extraction, not
matching-record or live-dataset review acceptance.

Still required: actual extracted regional records and matching teammate flags;
production contract/consumer agreement; user/admin branch/rules/credentials and
authorized deployment checks; Windows CI outcome and manual desktop acceptance.
Negation editing and shared-card reconciliation retain their deferred defaults.

PR-readiness verification (13 October 2026): the full suite reports **509 passed,
7 skipped, 2 failed**, with the same two local benchmark-data failures documented
above. Lint, formatting and whitespace checks pass. Follow-up regressions cover
uncertain undo retries, lazy scan rendering, dataset-wide audit-ID validation,
rejection of invalid incoming Git snapshots, immediate POSIX server restart, and
amending accepted no-data/illegible fields. Browser checks confirm correction,
undo, local Git sharing, and no-data-to-numeric amendment. This supports a draft
implementation PR; it does not replace remote CI, team schema/queue contract
sign-off, production-data acceptance, or Windows desktop verification.

## Concurrent-region and performance follow-up

The review schema is `0.4.0`, incorporating IT-89 (#50) from main at `c43a97f`.
IT-89 retains `0.3.0` for dwelling notes with required `front_page` provenance.
Both extraction and review behavior are now combined. Household-level notes are
readable only in `0.1.0`/`0.2.0`; newer versions reject that legacy shape. An old
record with household notes must be explicitly migrated before review can upgrade
it. Migration diagnostics disable decisions, and failed attempts leave the file
and note text intact. Verify each front/back association rather than inventing
provenance or silently deleting legacy notes.

A local before/after benchmark used unchanged copies of #51's results at
`c1a7ffe`, with 44 populated regions, 3,590 dwellings and 222,780 manually supplied
coding-field flags. The empty `216461.jsonl` was excluded only from the disposable
benchmark; normal dataset validation still rejects empty region files. Region
216418 contains 79 dwellings. Baseline code was this branch at `f1de190`; both
runs used stubbed scans and a local bare Git remote, with fresh copies and caches.

| Operation | Before | After |
| --- | ---: | ---: |
| Application startup, including full validation and queue indexing | 217.860 s | 33.862 s |
| First Accept in 216418 | 3.032 s | 0.175 s |
| Two subsequent corrections | 2.987–3.006 s | 0.126–0.130 s |
| Local sharing after those decisions | 101.632 s | 0.586 s |
| Longest continuous save-lock hold during sharing | 101.365 s | 0.177 s |
| Resolve all 222,780 field references | 7.336 s | 0.733 s |

These are local API measurements, excluding Python imports, browser rendering,
scan decoding and GitHub network latency. Regional JSONL serialization/replacement
still happens per save. Sharing can briefly block saves during commit/rebase/index
installation, but full incoming schema validation happens outside that lock.

To repeat the updated implementation benchmark on existing compatible results:

```sh
uv run python scripts/review_benchmark.py /path/to/results --region 216418
```

The helper reads the originals, copies nonempty JSONL to a temporary checkout,
generates a load-test flag for each supported coding field, stubs scan access,
and accepts three pending Weekly Rent fields. It reports startup, Accept, sharing,
lock-hold and lookup timings, then removes the disposable checkout and local Git
remote. It does not contact GitHub, change source data, or choose production review
flags. `--iterations` changes the number of pending rent fields needed.

Regression coverage includes two clones with dirty or committed disjoint-region
changes, same-region different-field conflicts, a real rejected push followed by
one retry, stopping after a second rejection, saves during validation/push,
audit-ID collisions introduced during validation, single-dwelling validation,
indexed lookup, startup loading once after writer-lock acquisition, batch counters
through undo/queue replacement, and scan-change invalidation.

Final follow-up verification: **533 passed, 7 skipped, 2 failed** in the full
suite. The failures are the same two pre-existing local benchmark-data checks in
`tests/test_confidence.py`, documented above. Ruff lint/format and whitespace
checks pass. A disposable r01 test also verified original-PDF PNG serving, all
three durable decisions, completion counters, schema `0.4.0`, and sharing to a
local bare remote. Original scans and the existing user test checkout were not
modified. Remote CI and Windows desktop acceptance remain pending.

Post-IT-89 rebase verification (13 October 2026): the branch includes main at
`c43a97f` and both extraction/review implementations. Full tests report **589
passed, 14 skipped, 2 failed**, with the same two existing confidence-benchmark
failures. Lint, formatting and whitespace pass. Combined rerun tests preserve
corrected note text by `front_page`, active coding review history, and pending
undo history. Strict modern-schema tests reject household notes; legacy-record
migration refusal retains source bytes. Decisions are recorded in D029.

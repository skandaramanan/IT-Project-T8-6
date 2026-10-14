# IT-115 reviewer UI: PRs 1–3

React + TypeScript in `frontend/`, built with Vite and served by the local
FastAPI backend at `http://127.0.0.1:8765`. The browser and API share an origin.
Source Sans 3 (400/600/700) is bundled, so opening the review screen needs no
Google Fonts connection. The v1.5 palette and type scale live in CSS tokens.

## Reading and PR split

Reviewed the README, all D0xx decisions, record-envelope schema, review runbook,
record/review implementation, integration page, review scripts and review tests.
Read the bodies of PRs #50–#54, #52's reviews and inline comments, and #53/#54's
queue implementation and labelled tests on their open branches. Inspected all
23 pages of the supplied hi-fi PDF, the mockup README, board content and layered
v13/v14/v15 CSS, including the Cover styling reference.

Read Linear IT-115, IT-113, IT-112, IT-111, IT-109, IT-110, IT-116, IT-65,
IT-64, IT-61, IT-106 and IT-131 with their comments; both Sprint 3 documents;
requirements, US-13/US-14 and their ACs; client meeting 4; Standups 14–17;
Test Cases, Coding Standards, Definition of Done, Encoding References and
Glossary. The hi-fi Linear document returns null content; the supplied local
PDF/HTML/CSS are the usable design source. The low-fi document is a PDF attachment.

Keep the proposed three-PR split:

1. **PR 1 (this change):** the working C1/C2 slice over #52's existing API:
   sign-in, region selection, a paged queue grouped by dwelling, original scan,
   field/value/code/label/status/confidence, exact-digit correction, accept,
   blank/illegible, undo, local-save confirmation and sharing status. Tests
   protect AC2 and the frontend part of AC3. Backend persistence/reopen tests
   prove the existing save path. No full-ticket completion claim.
2. **PR 2:** `GET /api/dwellings?region=`, card score and region averages,
   address/catalogue title, last reviewer, field kind/code list, and other card
   fields in printed order. Replace the temporary client grouping with a
   durable dwelling identifier and implement the complete queue (AC1).
3. **PR 3:** magnifier, detailed history/help/finish flows, two-household context,
   full laptop-layout polish and IT-116 findings. Keep basic coding-card tabs
   and manual zoom in PR 1 so all supplied household flags are reachable.

## Conflicts and limits found while reading

- IT-111/113 still describe a database. Merged #52 and D029 use authoritative
  JSONL with an in-memory index and schema **0.4.0**. #52's PR body still says
  0.3.0. IT-112's core save logic is already in that backend.
- The requirements document and old IT-64/110 comments still call routing
  provisional. D022 and IT-109's newer client-confirmation comment settle it.
  The UI takes the supplied order; it does not implement routing or move
  in-progress dwellings ahead of lower-scoring ones as the mockup suggests.
- #53's current `build_flags` traverses front/person fields too, although its
  IT-109 comment says coding-only. #52 rejects those as unsupported diagnostics.
  They stay visible and unresolved here; supplying only supported C1/C2 flags
  is an upstream queue responsibility, not a silent frontend filter.
- Standup 17 predates #52's fixes to performance, disjoint-region sharing and
  the schema clash. One backend owns each checkout; separate checkouts can
  share different regions. Same-region changes stop for manual reconciliation,
  even for different fields. The mockup's automatic same-region merging and
  per-field choice dialog do not describe this API.
- The mockup's separate accept/progress file, per-region PR sharing, accepted
  values changing on a rerun, record-ID editing, damaged/negated mutations,
  strict code-list rejection and two-reader answers are superseded or unsupported.
  Follow `allowed_actions`. Unknown numeric codes are retained with warnings.
  Damaged is displayed if already stored, but cannot be selected as an action.
- `216461.jsonl` is empty in #51; backend dataset validation rejects empty
  region files. Exclude that file from a **disposable copy**, never delete it
  from the source dataset. A region with no supported items is shown honestly.
- PR 1 had no dwelling ID, card score, address, region title, field kind or printed order
  from the API. PR 2 now supplies these. PR 1 groups by `(region, PDF, municipality-dwelling)` for
  display only, preserving first occurrence and every field's original order.
  Duplicate displayed IDs can be grouped together; every save still uses the
  opaque physical-card item ID. PR 2 must provide actual dwelling identity.
- No made-up corpus counts or sample confidences are rendered. Counts cover
  supplied flags only. The current unbanded coding-field values are
  0.97/0.91/0.75/0.74/0.0 (or null); card aggregates can have other values.
- Uvicorn finishes the existing lifespan startup before serving HTTP; the
  launcher waits before opening the browser. The UI shows loading during its
  health/region/item/scan requests and connection retries, but cannot display
  the initial backend validation wait before HTTP is available. The launcher
  console remains visible during that wait. Background startup is separate
  backend work, not silently introduced in this slice.
- Backend reviewer sessions are in memory. Retype your name after restarting
  the backend. A failed request does not submit a forged reviewer field.
- TC-M07 requires a different executor; TC-M08/IT-116 requires a non-technical
  participant. Developer checks do not claim either independent acceptance.

## Build and run

Developers need Node **22.12+ (22.x) or 24+** and npm. Reviewers need only the
built assets alongside the code checkout, Git, uv and the Python environment.
From the **IT-115 code worktree**:

```sh
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

FastAPI checks for `frontend/dist/index.html` when creating the app. Restart it
after adding/removing a build. `frontend/dist` and `node_modules` are ignored;
source and `package-lock.json` are tracked. API/docs routes remain ahead of the
static mount. Files outside the dist directory cannot be served by that mount.

For development, `npm --prefix frontend run dev` proxies `/api` to the existing
backend on 8765. Use its printed loopback address. The proxy rewrites Host/Origin
for that local backend; production continues to use one origin and no CORS change.

### Real r01 scan with copied illustrative records

Choose a **new directory outside both checkouts**. The helper verifies the
original pages against the fixture JPEG bytes and copies the schema example;
it is illustrative data with unknown scores, not a fresh model extraction.

macOS/Linux:

```sh
uv run python scripts/review_fixture.py /tmp/it-115-review-test \
  --scan-root /path/to/Wilfred_Prest_Survey_Data
```

Windows PowerShell:

```powershell
uv run python scripts/review_fixture.py "C:\Temp\it-115-review-test" --scan-root "C:\Users\YourName\Documents\Wilfred_Prest_Survey_Data"
```

Run the **exact launch command printed by the helper** (port 8876). Its
`--data-checkout`, flags and cache point to disposable copies, and sharing goes
to a local `remote.git`, never GitHub. Original scans are read-only. Never set
`--data-checkout` to the code worktree or the original results checkout.

For extracted #51 data instead, use `scripts/review_sample.py` against one
populated regional file. It copies the selected complete dwellings and creates
its own local data checkout/remote, keeping source files unchanged:

```sh
uv run python scripts/review_sample.py /path/to/copied-results/216418.jsonl \
  /tmp/it-115-region-test --scan-root /path/to/Wilfred_Prest_Survey_Data \
  --field "Weekly Rent" --field "Garden" --households 2
```

This is a manually selected test queue, not production flags from #53. Run its
printed launch command. For an entirely synthetic check with no archive download,
use `uv run python scripts/review_demo.py /tmp/it-115-synthetic-test`.

### Reviewer steps

1. Enter your name and choose **Start reviewing**.
2. Select a region; choose **Review**, **Continue** or **Reopen** on a dwelling.
3. Wait for the original scan. Find the field by its printed name and compare
   its value, meaning, status and confidence. Use manual zoom if needed.
4. Choose **Accept**, or **Correct**, type the exact digits and choose **Save**.
   Leading zeros are preserved. For an empty/unreadable cell, use the link under
   the buttons and select the appropriate plain-language choice.
5. The Saved line confirms local persistence; sharing status is separate.
   **Undo** restores the latest applicable decision and retains its history.
6. If saving is uncertain, **Try again** reuses the original request and keeps
   input. Navigation pauses. On a stale version, reload explicitly; typed digits
   stay. Same-region conflicts require the team to reconcile before restarting.
7. **Save and Exit** attempts sharing, then explains whether sharing was
   confirmed. It never claims an unfinished correction was saved. Close the
   tab and stop the backend with Ctrl+C when finished.

## Tests and distribution recommendation

Vitest + Testing Library exercise the rendered decision flow and API requests:
scan loading/failure, restrictions, exact digits, local failures and retries,
stale versions, undo retries, save-before-advance, sync conflicts, region scope
and bounded queue rendering. Pytest verifies built/fallback serving and preserves
IT-113's real persistence, restart, audit, security and sync tests. Both frontend
build and tests run in CI; Windows review CI includes the asset-serving tests.

Prefer CI-built assets over committing `dist`. This PR uploads a
`reviewer-frontend` artifact. For Standup 17's **single deployable**, package that
build with the matching code, schema, uv lockfile and Windows launcher in one
release ZIP; reviewers unpack once and run `uv sync --locked`, then the shortcut,
without Node. A ZIP of frontend assets alone is not the complete deployable.
Do not distribute a wheel yet: the current backend expects an editable checkout
for schema and frontend paths (D024/runbook). Full release packaging and physical
Windows acceptance remain follow-up work.

### Session verification

- `uv run ruff check .` and `uv run ruff format --check .` passed.
- `uv run pytest`: 590 passed, 17 skipped; one Starlette deprecation warning.
- `npm --prefix frontend test`: 18 passed; TypeScript and the Vite build passed.
- Built and fallback asset/API tests passed with the production build present.
- Browser checks used disposable synthetic and r01 copies. A correction to `009`
  survived reload with original `04` retained, reviewer attribution and undo;
  the copied results passed `survey validate-results`.
- Original results and scans were unchanged. Test servers were stopped.

## PR 2: dwelling queue and review context

This local change is stacked on PR 1 (`cdd9c08`, GitHub #56), on
`skandar/it-115-reviewer-queue-pr-2`. The PR 1 branch remains unchanged.
No project commits, remote pushes or external posts are made during implementation.

The queue requests `/api/dwellings?region=...`, one small summary per JSONL
dwelling. Opening one row loads only that dwelling's flagged items via
`/api/dwellings/{id}/items?region=...`; opening a field loads its detailed context.
The browser no longer downloads the region's full field/history queue to group it.
Rows preserve the first occurrence in the supplied flags, including after a save.
Continue opens the first unfinished row in that order. The mockup's promotion of
in-progress rows is deliberately omitted because the supplied queue owns ranking.

IDs hash the region and sorted physical coding-card locations, independent of
read record numbers, JSONL row order and household order. Separate dwellings with
the same read number remain separate. Changing a dwelling's actual card membership
changes its ID; stale pointers remain visible diagnostics rather than disappearing.
Nullable record numbers display “Number not identified”. This is display support,
not acceptance of an upstream schema version before it has been integrated.

The row score is its weakest stored household coding-card score; if any card is
unscored, the dwelling is shown as not scored. Region/all-region averages use each
available coding-card score once, including cards outside the supplied queue.
Unknown scores are excluded from the mean and counted separately. Neither human
acceptance nor correction invents a new machine score. Counts come from loaded data;
no fixed corpus counts from the old boards are used.

Progress is decided supplied flags, grouped into queued dwellings. Loaded dwelling
counts and queued dwelling counts are separate API values. A dwelling absent from
regenerated flags is not claimed as reviewed or automatically completed. Unsupported,
stale and missing-source diagnostics remain unresolved and prevent completion. Last
reviewer/date comes from the dwelling's latest stored decision, including undo and
fields no longer present in regenerated flags. Refresh queue or return from review
to retrieve current progress. An explicit stale-field reload refreshes the dwelling's
other decisions while preserving the correction draft.

Address is read-only survey-front context. Catalogue titles come from `metadata.csv`
at the configured scan root (`Node ID`/`Node Title`, including UTF-8 BOM); missing
metadata falls back to the region ID. Region IDs are never replaced by guessed suburbs.
Coding fields follow `FIELD_SCHEMA` printed order, not `FIELD_MAP` domain grouping.
Other stored fields are visible but only supplied flags can be opened for decisions.
Shared building fields appear on household 0 only. The active field scrolls into view.
Card tabs show scan page and remaining flags. Code meanings use the existing closed
and sentinel maps; ordinary amounts remain valid and unknown digit codes can still
be saved with the backend's warning. No new validation policy is introduced.

Review summary (.csv) downloads the current region's full dwelling summary, including
rows beyond the visible page. It is progress information, not a corrected-dataset
export; authoritative records remain JSONL. CSV cells are quoted and formula-like
text is kept literal when opened in spreadsheet software.

### Upstream integration boundaries

- #52 is merged and provides the store/save/sync implementation. Linear's IT-111/112/113
  database wording/status remains older than D029 and the implementation.
- #53 (IT-109) still needs its review fixes/rebase and coding-only flags. #54 (IT-110)
  is stacked on it. Unsupported supplied flags are surfaced; the frontend does not
  silently discard them or rebuild routing.
- #51 (IT-123) is open. Its published data count changed from 3,590 to 3,717; read
  counts from data. The other agent's local schema 0.5 follow-up allows null/lettered
  IDs and dwelling flags. Its schema predates review metadata: it must be integrated
  with 0.4 review validation/history before loading that rebuilt dataset. #53's sorting
  also needs a deterministic nullable-ID tie-break and dwelling-flag handling.
  PR 2 does not copy, edit, commit or rebase that agent's work.
- IT-124/#55 and IT-125 are not prerequisites for this UI. Single-reader scores route
  to review now; merged scores can clear fields later without frontend routing changes.
- IT-116 and independent Windows/manual acceptance remain rollout work. PR 3 retains
  detailed magnifier/history/help/finish, column folding/locator polish and laptop polish.
  Front/person/damaged/negation edits remain outside the backend's v1 action contract.

### PR 2 verification and safe local run

Use the same build commands and disposable fixture/sample workflow above. A fresh
real-scan fixture example (never the project's results checkout):

```sh
uv run python scripts/review_fixture.py /tmp/it-115-pr2-test \
  --scan-root /path/to/Wilfred_Prest_Survey_Data
```

Run the launch command printed by the helper from this code worktree. Every review
write targets the copied `/tmp/.../data checkout`; sharing targets a local bare
`remote.git`. Tests likewise use temporary synthetic datasets/local remotes, never
GitHub. Keep the real source scans read-only. Choose a fresh directory each time.

Independent reviews covered data/client contracts, backend correctness and frontend
state recovery in separate passes. Regression tests cover physical identity, region
averages, printed order, readonly fields, code meanings, progress/reviewer/undo,
source loss, synced stale pointers and recovery, scan gating, and stale editor reloads.

Final local checks: Ruff lint and format pass; full pytest **604 passed, 17 skipped**
(one existing Starlette/httpx deprecation warning); frontend **25 tests passed**;
TypeScript/Vite production build passed. Independent follow-up checks confirmed
stale-pointer recovery, global scan completion and editor-context refresh fixes.
Browser verification at 1366 × 768 used a fresh `/tmp/it-115-pr2-r01` illustrative
r01 copy with verified original PDF pages: exact `009` correction, original `04`,
next-field navigation, persisted reload, attribution/progress and a real CSV download.
The temporary toolbar wrap keeps all queue actions reachable at this width.

A read-only load comparison used a temporary copy of published #51 commit
`1f772b7`: 44 populated regions, 3,717 dwellings, 230,494 manually supplied supported
flags. Scan metadata/rendering was stubbed; this is not production flag generation.
For 216418 (81 dwellings, 5,022 flags): summary **40,146 bytes / 0.103 s**, legacy
field queue **6,495,484 bytes / 0.274 s**, selected dwelling **80,139 bytes / 0.006 s**.
The initial region response is **99.4% smaller**. Combined dataset load/indexing took
58.663 s. These are local observations, not Windows or network performance claims.

A subsequent whole-PR review found and fixed two additional edge cases: incomplete
optional catalogue titles now fall back without preventing startup, and save/undo
responses build card navigation after updating progress. Regression tests exercise
accepting every field on a card and undoing the second decision, verifying that the
returned next-field link matches a fresh GET. The independent reviewer confirmed
both fixes; the focused backend suite passed 62 tests and the frontend suite 25.


## PR 3: magnifier, help, history, finish and laptop review

PR 3 is a local branch `skandar/it-115-reviewer-polish-pr-3`, stacked on
PR 2 (`0eaea42`, GitHub #57). PR 1 and PR 2 branches remain unchanged.

The scan viewer fits the entire original card into its viewport using the image's
real dimensions. Use +/− to zoom, or drag with the mouse to move an enlarged scan.
Magnifier toggles a mouse-following 2.5× lens; +/− changes the lens diameter while
it is on. Keyboard users can switch it off and use zoom and arrow-key scrolling.
Zoom, lens toggle and lens size stay while moving between fields on one physical
card and reset when switching cards. Each field/retry loads fresh image evidence;
late events from a previous image cannot enable the current decisions.

Help opens after the first sign-in and remains available from the header.
More help explains the real v1 contract and has a switch for single-letter
shortcuts, remembered in browser storage when available. A/E/U work with focus in
the field panel; M works with focus in the scan or its controls. Decision shortcuts do not act
while typing, during another request, or behind a modal. A accepts, E corrects,
U undoes the saved decision after advancement (or the selected field's latest
applicable decision). Left/right navigate queued fields on the current card.
Enter saves a correction; Escape cancels from the input or its buttons, except
while saving is uncertain. Turning shortcuts off disables A/E/U/M, retaining
ordinary Tab/Enter and the correction form's Enter/Escape controls.

History displays the recorded original answer/status/confidence and the audit
before/after values, status, reviewer and local date/time. Clicking a decided
field opens its history. Imported legacy corrections use `original_value`, and
say when the original status/actor/date was not recorded; none is invented.
Only the backend-provided latest applicable decision can be undone. Undo adds an
audit entry and never deletes previous decisions.

The field locator names its printed column and label, without claiming a pixel
location or universal line number (C2 prints an extra field). Completed columns
can fold, expand and reopen their decided fields. The active column stays open.
Card context adds `column`, `household_count`, `dwelling_flags`, per-field column,
and each coding card's score. Unqueued coding cards are visible in the tabs as
“Not queued” without an action ID. The actual shared building fields remain on
household 0. Front/person/back editing, record-ID changes, Damaged and crossed-out
mutations remain deferred. Grouping/identity warnings are translated to plain
language; unknown flags still ask the team to check the grouping/identity.

Save and Exit opens a modal over the current review context. It confirms local
persistence separately from a confirmed uploaded sharing state and timestamp.
Failed/uncertain sharing never displays “Shared”. Keep reviewing returns to the
same field, scan and settings. The continuation hint names the region, household
card, page and printed field; it describes how to find it in the queue and does
not pretend that browser selection survives a backend restart. A completed
supported dwelling directs the reviewer back to the queue to check diagnostics.
Unsaved drafts and uncertain saves block exit until saved, cancelled or retried.

At 1366 × 768 the header, scan toolbar and exit action remain reachable; the field
panel and scan scroll independently, and modal contents scroll within the screen.
Long reviewer names are visually shortened with the full name available on hover;
the complete name remains in every saved audit decision.

### Acceptance and integration boundaries

- AC1: every supported supplied flag is reachable through the dwelling/card/field
  navigation, including completed columns. Unsupported diagnostics remain visible.
- AC2: image evidence, current/original values, status and score precede an action;
  scan failure/reload/card switching cannot bypass the gate.
- AC3: the existing versioned backend persists exact digits and provenance, keeps
  retry IDs stable after uncertainty, and supports restart/undo/rerun protection.
- IT-116 has no findings yet. The unaided non-technical participant test and
  independent manual UI acceptance remain required; developer/subagent checks
  cannot claim NFR-09 or physical Windows desktop acceptance.
- #53 still needs production queue fixes/integration. #51 now retains 5,356
  records/5,411 households and schema 0.5.0; this stack's 0.4 schema must integrate
  with it before validating that latest corpus. Counts are always data-derived.
  The old PR 2 load comparison remains a historical measurement of its cited commit.
- Full Windows release packaging, provisioned data-branch credentials/rules and
  client repository handover remain deployment work. The existing CI-built frontend
  artifact is not by itself the single complete deployable recommended above.

Use the existing Build and run instructions with a fresh disposable directory,
e.g. `scripts/review_fixture.py /tmp/it-115-pr3-test --scan-root ...`, and run its
printed command. Original results and scans remain unchanged. All verification
mutations/sharing use copied data and a local bare remote, never GitHub.


### PR 3 verification

Separate subagents independently reviewed each implementation stage and the final
whole change: one final pass for AC/requirements and another for usability,
quality, bugs and security. The final quality pass exposed an optional-page/source
regression in unqueued card context; it was fixed and independently rechecked for
absent/null page and a non-PDF image identifier. Such context cannot prevent a
healthy queued field from opening. Final reviewers found no remaining actionable
findings; human acceptance gates above still apply.

Frontend: **43 tests pass**, including scan-gate reload/late events, per-card view
settings, actual lens source/geometry, pan/keyboard controls, shortcut off, modal
help/finish/draft guards, audit history, original legacy values, latest-saved undo,
completed-column reopening and household switching. TypeScript/Vite build passes.
The focused dwelling suite passes **17 tests**, including the optional-source fix.
Ruff lint/format and whitespace checks pass. Full `uv run pytest` with stable built assets: **607 passed, 17 skipped**,
with one existing Starlette/httpx deprecation warning.

Browser checks at **1366 × 768** used the illustrative `/tmp/it-115-pr3-r01`
copy and its verified original scan: exact `009` correction with machine `04`
kept, history actor/date, next-field navigation, native help focus restoration,
persisted shortcut setting, sharing/finish/Keep reviewing, and a 95-character
reviewer name without horizontal overflow. The correction and audit survived a
backend restart; the copied JSONL validates. Sharing went only to the fixture's
local bare remote. Test servers/tabs were stopped and the viewport reset.

One intermediate full run overlapped a frontend rebuild and returned a temporary
404 for the static root while Vite replaced dist. The isolated API suite passed
15 tests; final full verification holds built assets stable. No application change
was made to hide that test-run interference.


A further fresh bug and visual review found a reviewer-switch scan-gate bug:
changing reviewer unmounted the scan but retained the prior readiness marker.
Successful sign-in now clears readiness/failure and advances the image evidence
revision while retaining the selected field, draft, history and queue. A regression
proves Accept/Correct remain disabled until the new image loads; the independent
reviewer rechecked **43 frontend tests** and the production build. Focus returns
to the open field, preserving correction-input focus during reauthentication.

The separate visual reviewer found no actionable issue at 1366 × 768,
1024 × 768 or 390 × 844, including real-scan save/history/help/finish and synthetic
two-household switching. Magnifier toggle and lens-size controls were exercised;
native mouse-hover lens rendering was not exercised by the available browser
controls (source/geometry are covered by component tests). All review tests used
disposable data/local remotes; that reviewer's server/tab and viewport were cleaned up.


## IT-113 text continuation (14 October 2026)

On `eric/it-113-build-the-review-queue-data-store-follow-up`, the existing stack is
extended to supported front dwelling fields and IT-89 interview notes. The APIs
are reused. `field_kind: text` selects a multiline correction with exact Unicode/
whitespace retention; code lists remain specific to numeric coding fields. Card
metadata adds role and nullable household_index for dwelling front/back sources.
`source` includes role and the verified note front_page. Front/note tabs appear
only for supported supplied flags; all coding cards remain available as context.

The backend rejects stale note pointers and ambiguous ownership. Fresh supplied
pointers after a reorder recover the same physical note ID. Person and merged
multiple-front fields remain unresolved. The synthetic helper now supplies five
manual flags and four synthetic PDF pages, including front/address and notes.
The Windows package ships matching built frontend assets with editable Python
source; reviewers do not need Node. See [operator steps](review-windows-acceptance.md).
Live PR stack freshness and IT-109's merge remain unverified; no teammate branch
was rewritten. Developer verification is recorded separately from human acceptance
in [the continuation record](review-continuation-verification.md).

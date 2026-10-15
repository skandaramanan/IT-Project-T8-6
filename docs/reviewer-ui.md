# IT-115 reviewer UI: PR 1

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
- No dwelling ID, card score, address, region title, field kind or printed order
  comes from this API. PR 1 groups by `(region, PDF, municipality-dwelling)` for
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

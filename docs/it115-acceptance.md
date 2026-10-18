# IT-115 PR 4: production integration and acceptance handoff

Audit date: 19 October 2026 (Australia/Melbourne). The PR 4 branch was committed
and pushed at `d28624f`; no PR has been published. The documentation and test
follow-ups were prepared after that revision and are included in this PR branch.
Verify CI against the final pushed SHA; the initial revision alone does not
identify those follow-ups or establish their CI outcome.

## Current status and acceptance scope

[IT-115](https://linear.app/um-it-project/issue/IT-115/reviewer-screen-a-queue-to-browse-and-a-screen-to-review-each-field-fr)
is **In Progress**, rechecked on 19 October. It was briefly Done on 18 October;
that earlier observation is historical. This documentation review changes no
remote ticket, document or status.

IT-115 requires the produced flags to be visible/selectable (AC1), the matching
scan, answer, status and confidence before deciding (AC2), and GUI corrections
saved into exported records with updated review state (AC3). The working queue,
save logic and state store are implementation dependencies. Their ticket statuses
and separate administrative approvals do not add acceptance criteria to IT-115.
D029 storage wording is reconciled below and in the proposed updates.

The [dependency evidence map](it115-dependency-evidence.md) links each IT-111,
IT-112 and IT-113 criterion to the implemented D029 model and specific regression
or production-copy proof. No new backend approval ceremony is required.

[TC-M07](https://linear.app/um-it-project/document/test-cases-648649f503b7)
remains Pending. It requires a human executor other than Skanda and screenshots
at steps 3, 4 and 5. Automated checks and AI-assisted computer-use evidence are
useful technical evidence; neither is a human TC-M07 pass. Human executor and
observed result remain blank until that person performs the test.

[Definition of Done](https://linear.app/um-it-project/document/definition-of-done-0fce56ee35d6)
also requires independent PR approval, merge, passing checks, updated docs,
recorded follow-ups and owner closure. No PR exists yet, so those delivery items
remain outstanding.

IT-116's unaided Archives usability test is downstream, with its own participant
and observation requirements. IT-125 is needed only for a claim about the final
dual-scored corpus; compatible production Gemini records and their matching
scans suffice for bounded reviewer integration. IT-134's negation editing remains
deferred. Physical Windows acceptance is a user-requested rollout check, kept
separate from IT-115's written ACs and TC-M07 below.

## Scope and resolved contradictions

- D029 is authoritative: region JSONL stores values and append-only review
  history, with an in-memory lookup index. IT-111/113's database language is
  stale. No second durable database, progress file or dual-write operation exists.
- D029 chooses a separate `review-data` checkout and ordinary pushes, with one
  assigned owner per region. Same-region changes stop for reconciliation. The
  hi-fi per-region PR and automatic same-region merge frames are superseded.
- The interface edits supported C1/C2 numeric coding fields. Identity and already
  negated fields are accept-only. Front/person/reverse/handwritten editing,
  identity amendments, negation editing and household regrouping remain deferred.
  Open #66 proposes broader text review and packaging; it is not included here.
- Whole-card scans, manual zoom/magnifier, printed field names and textual
  Left/Middle/Right locators are supported. Coordinates, automatic highlighting
  and automatic field zoom remain outside IT-115. Hi-fi example scans explicitly
  stand in for different records and cannot establish matching-source acceptance.
- Merged #60 already supplies later-household Municipality, printed order and
  flagged-dwelling identities. Merged #62 already handles the welcome dialog.
  These fixes are not replayed. The current first-household Municipality fallback
  remains actionable; #68 owns canonical alias presentation cleanup.
- This change's empty-assignment startup fix overlaps the small corresponding
  change in open #68. Resolve that overlap before publishing/merging either PR.
  No other #66–69 commits, text editing, scan downloads or live-GitHub acceptance
  machinery were imported. Their release packaging and broader rollout remain
  independently reviewable. An empty queue is an assignment result, not proof
  that every record in a corpus was reviewed.
- D022's old 04 October meeting date conflicts with the linked 02 October Client
  Meeting #4 and IT-109 confirmation. The repository date is corrected; proposed
  Product-document updates are prepared separately. Routing still uses D016's
  agree constant; null scores and non-ok statuses route, and the producer adds
  identities for flagged dwellings. Unscored is not zero or invented confidence.

## Reproducible production-record setup

Requirements: Git, uv/Python 3.12 and Node 22.12+ in 22.x or Node 24+ with npm for
the asset build. Run in the code checkout:

```sh
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
uv run python scripts/review_acceptance.py results/216412.jsonl /tmp/it115-human-acceptance --scan-root data/Wilfred_Prest_Survey_Data
```

Windows PowerShell (replace paths with actual locations):

```powershell
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend run build
uv run python scripts/review_acceptance.py results/216412.jsonl 'C:\Temp\IT115 acceptance' --scan-root 'C:\Archive\Wilfred_Prest_Survey_Data'
```

Use a new destination outside code, original records and scans. The helper copies
the entire region and matching PDFs, validates every produced source page,
preserves record bytes/household indexes/scores, calls the actual `build_flags`
producer, and creates only a disposable local `remote.git`. It refuses skipped
producer sources instead of silently dropping them. `manifest.json` records
source hashes, code base, counts and exact quoted launch arguments. Retain the
working diff alongside it: HEAD alone does not identify uncommitted code.

Run the exact launch command printed by the helper. All writable data, scan
cache, copied PDFs and sharing destination then point outside original data.
The launcher now waits up to five minutes for validation before reporting a
timeout; startup errors still stop immediately. Close the browser and Ctrl+C
the backend when finished. No extraction/model calls are needed.

For a portable source handoff, assemble a folder retaining the repository layout:
`backend/`, `schema/`, `scripts/`, `frontend/dist/`, `pyproject.toml`, `uv.lock`,
`.python-version`, README and docs. Include only the built `frontend/dist`, not
node_modules. Unpack, run `uv sync --locked`, then the same review command.
This is a source-plus-assets distribution, not an installed wheel containing UI
assets. Verify `/` serves the built React screen after moving the folder. Open
#66 owns the automated release packager; no duplicate packager is added here.

Browser integration (fresh disposable destination for each run):

```sh
npx --prefix frontend playwright install chromium
SURVEY_ACCEPTANCE_SAMPLE=/absolute/resolved/path/to/disposable/sample npm --prefix frontend run e2e
```

Use the resolved destination printed in manifest paths (on macOS `/tmp` resolves
to `/private/tmp`). The optional production journey refuses an origin different
from that sample's local `remote.git`. Default CI runs the generated synthetic
queue journey and existing failure/retry journeys; production execution requires
the archive and is explicitly skipped when the variable is absent.

## Human TC-M07 execution sheet

Execution status: **NOT RUN**. Human executor: ______ (not Skanda).
Date/time: ______. Build/commit and working diff identity: ______.
Sample manifest/source hashes: ______. Evidence directory: ______.
Observed result: ______. Failure and follow-up, if any: ______.

Use a fresh disposable sample prepared above. Enter a reviewer name and dismiss
first-use Help. These are the documented TC-M07 steps:

1. Open the reviewer screen on a region.
2. Open the first flagged field.
3. Check that the matching source scan, machine value, status and confidence are
   visible before deciding. **Capture screenshot 3.**
4. Correct the value and save. **Capture screenshot 4.**
5. Reopen it, then inspect the JSONL export. Confirm the new value,
   `origin: corrected` and original machine value. **Capture screenshot 5** and
   retain the exported field excerpt.

The JSONL in the disposable data checkout is the export. TC-M07 requires a
non-author human; it does not require an unaided Archives participant or Windows.
Those belong to the separate checks below. Record an actual pass or failure only
after execution; leave executor/result fields blank beforehand.

The first generated flag can be an accept-only identity. Inspect it, then select
an editable numeric field such as **Weekly Rent** for steps 3–5; record that
selection. Do not attempt to change an identity or claim its disabled Correct
button is a defect. On the prepared fresh sample, open `09-0077-01`, select
**Weekly Rent** (original PDF page 197), and compare its machine value `10`,
Readable status and confidence `0.91` with the scan. A deliberate `009` test edit
is permitted only on the disposable copy to check exact-digit persistence; label
it as a test edit rather than a source-verified transcription correction.

## Optional technical integration evidence

The dated [verification record](it115-verification.md) records automated and
independent technical checks. Any separately recorded AI-assisted walkthrough
must identify itself as AI-assisted. Neither fills the human sheet above.

The completed [computer-use walkthrough](it115-walkthrough.md) includes local
screenshots, exported field evidence and the exact result template/location for
a subsequent human execution. A fresh unmodified human sample is prepared at
`/tmp/it115-human-ready-20261019`; use its manifest's launch command. The earlier
walkthrough sample contains a deliberate test edit and is evidence only.

Additional coverage requested for PR 4 includes exact `009`, Accept, restart,
regeneration, Undo, multiple households, nullable identities, unchanged records,
missing scans, stale versions, uncertain retries, sharing failures and same-region
reconciliation stops. Use the existing backend/browser regressions and disposable
production samples. These are technical checks, not extra mandatory steps for
the TC-M07 human executor. Never mutate original scans/results or test sharing
against a live remote.

## Downstream IT-116 usability

IT-116 / TC-M08 requires a non-technical Archives participant to complete the
review/correct cycle using only written instructions without development-team
help, with failures recorded, fixed and retested. Its observation sheet, participant
selection and timing are separate from TC-M07. Prepare current instructions now;
keep IT-116 pending and downstream rather than making it an IT-115 closure gate.

## Review-data administrative rollout

Read-only inspection found an existing remote `review-data` branch and review-save
history. That proves branch use, not credentials/protections on every intended
desktop. D029 and `.github/workflows/review-data.yml` govern rollout: local
validated JSONL save → commit/share → post-push validation. “Shared” means upload
success, not a CI pass. Same-region overlap requires preserved-data manual
reconciliation; disjoint regions can rebase. Never force-push to reconcile.

The rollout owner/admin should confirm canonical data ownership, appropriate
branch rules, operator credentials and post-push validation before intended live
use. Disposable local sharing tests do not attest to live permissions. These
administrative tasks are deployment readiness items, not additional IT-115 ACs.

## IT-115 delivery and closure checklist

- [ ] Record final functional evidence for AC1–3 against the current code and
      matching copied production records/scans; rerun affected checks after fixes.
- [ ] Complete the actual human TC-M07 sheet and its three required screenshots.
- [ ] Update behavior/setup docs and locally prepare accurate ticket wording;
      track deferred scope and distinguish dependency implementation from rollout.
- [ ] Publish PR 4, coordinate the documented #68 overlap, verify CI on the final
      pushed SHA, obtain independent approval and merge under the Definition of Done.
- [ ] Owner closes IT-115 when its actual ACs and DoD are satisfied. Its current
      status is In Progress. IT-116 remains downstream; final dual-corpus claims
      require IT-125.

## User-requested physical Windows handoff — Jacob

Requested operator: Jacob. Actual executor: ______. Date/time: ______.
Device/Windows/browser: ______. Build and working diff identity: ______.
Evidence paths: ______. Observed result: ______. Failures/follow-ups: ______.

Run this on a physical Windows desktop at the end of the handoff. Use a new
sample destination and shortcut paths containing spaces; launch
`scripts\review.cmd` with correctly quoted paths. Verify actual browser opening,
matching scan rendering, a saved decision, Undo, restart/reopen and port-collision
handling. If delivering the portable source-plus-assets folder, repeat its launch
from the unpacked location. Use only the disposable local remote to verify failed
sharing retains local decisions and recovery succeeds.

Jacob may also execute TC-M07 during this same session, provided he actually
performs its steps as a non-author and records his own screenshots/result.
TC-M07 does not require an Archives participant; that belongs to IT-116. Record
the functional TC-M07 result and Windows rollout result separately even if
executed together. Existing automated screenshots are reference material, not
proof of his execution.

Windows CI covers synthetic filesystem/Git/API behavior; it does not fill this
sheet. Jacob's requested Windows check is rollout evidence, separate from the
written IT-115 ACs, human TC-M07 and downstream IT-116 usability. No physical
Windows pass is claimed here.

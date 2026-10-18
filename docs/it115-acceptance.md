# IT-115 PR 4: production integration and acceptance handoff

Audit date: 19 October 2026 (Australia/Melbourne). Local changes based on main
`9cf8a35c3883f8ff75113d7d4d23760c4a73de05`; no publication or remote mutation.

## Current status and authority

Live Linear already marks IT-115 Done. That status is not evidence of completed
acceptance: [TC-M07](https://linear.app/um-it-project/document/test-cases-648649f503b7)
remains Pending, explicitly requires an executor other than Skanda, and the
[Test Report](https://linear.app/um-it-project/document/test-report-08102026-81352fbbbe45)
and [How We Tested](https://linear.app/um-it-project/document/how-we-tested-6a8358e84eee)
record no manual execution. No status was changed in this work.

[Definition of Done](https://linear.app/um-it-project/document/definition-of-done-0fce56ee35d6)
also requires independent PR approval, merge and checks. This local handoff does
not establish those gates. Automated and agent reviews cannot replace human
TC-M07 or physical Windows desktop evidence.

IT-109/110/114 are Done; IT-111/112/113 remain In Progress. IT-116 is downstream
usability work; IT-125 is In Review and is only a hard dependency for a claim
about the final dual-scored corpus. Compatible production Gemini records and
their actual scans suffice for bounded reviewer integration, with scores shown
honestly. IT-134 is archived Todo: negation editing remains deferred.

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

## Human TC-M07 and Windows execution sheet

Result: **NOT RUN**. Executor: ______ (not Skanda). Date/time: ______.
Windows operator/device/OS/browser: ______. Code base and diff hash: ______.
Sample manifest and source hashes: ______. Evidence directory: ______.

1. Start with a fresh copied region and matching scans. Record manifest counts,
   code/diff and launch output. Enter reviewer name and dismiss welcome Help.
2. Select a region, then a dwelling. Compare generated flags with the queue;
   visit both households where available. Nullable display IDs must not combine
   physical cards or prevent selection. Identity decisions remain accept-only.
3. Before deciding, capture the matching original PDF/page, printed label,
   extracted answer, status and actual confidence. Capture screenshots required
   by TC-M07; verify manual zoom and textual location rather than a highlight.
4. Correct a numeric field to `009`, accept another and capture local-save
   confirmation. Inspect `results/<region>.jsonl` in the disposable checkout:
   exact string, original machine value, reviewer, time and history must remain.
5. Stop/restart, sign in, reopen and capture retained values. JSONL is the export;
   no lossy numeric conversion step is needed. Compare every other field/record.
6. Regenerate from the copied results with `uv run survey flags <copied-results>`
   into a new flags file; restart using it. Decided fields must leave pending
   assignment; retain the old flags file to reopen/Undo. An empty regenerated
   assignment must start successfully, without claiming whole-corpus acceptance.
7. Undo using the retained assignment; inspect append-only history and regenerate
   again. The restored pending field must reappear. Record any failure honestly.
8. On a separate fresh sample, remove/rename a copied scan and verify decisions
   are disabled. Restore it. Never manipulate original archive files.
9. Run two reviewer sessions; verify stale save rejection and retained typed
   input. Reproduce uncertain response retry through the automated browser test;
   verify one decision event, not two.
10. Rename only the disposable `remote.git`, save and Share now. Verify local
    persistence plus failed-share feedback. Restore it and retry. For same-region
    reconciliation use the existing two-clone sync regressions; capture the stop
    message and preserve both sides. Do not test live data writes.
11. On physical Windows, launch `scripts\review.cmd` from a shortcut with quoted
    paths containing spaces; verify actual browser/scan, save/undo/restart and
    port-collision handling. For portable assets repeat from the unpacked folder.
    CI on Windows does not fill this sheet.

Observed results and screenshot/export paths: ______. Failures: ______.
Independent executor sign-off: ______. Physical Windows sign-off: ______.

## Review-data rollout and closure checklist

Read-only inspection found an existing remote `review-data` branch and review-save
history. That proves branch use, not correct credentials/protections for every
intended desktop. D029 and `.github/workflows/review-data.yml` govern rollout:
local validated JSONL save → commit/share → post-push validation. “Shared” means
upload success, not a CI pass. Same-region overlap requires preserved-data manual
reconciliation; disjoint regions can rebase. Never force-push to reconcile.

- [ ] Named non-author TC-M07 execution with matching scan/record screenshots.
- [ ] Physical Windows launch/shortcut/paths/save/undo/restart evidence.
- [ ] IT-111/112/113 storage wording and actual acceptance sign-off reconciled.
- [ ] Admin confirms canonical review-data ownership, branch rules, intended
      operator credentials and post-push validation. Live writes are outside this
      session; disposable sharing does not attest to live permissions.
- [ ] User commits/publishes PR 4, resolves #68 overlap, obtains independent review,
      verifies all CI at the final pushed SHA and merges per DoD.
- [ ] Owner reconciles IT-115's existing Done status with the evidence above.
      IT-116 remains downstream; no final dual-corpus claim without IT-125.

Until these gates have genuine evidence, this audit does not support closure.

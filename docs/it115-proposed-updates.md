# Proposed IT-115 ticket and Product updates — 19 October 2026

These are reviewable local drafts, not posted comments or applied document/status
updates. Live IT-115 was rechecked as **In Progress** on 19 October. It was briefly
Done on 18 October, then reopened; the earlier audit's Done observation is
historical. Read-only retrievals are retained under `/tmp/it115-audit/`, including
`revised-live-scope-evidence.json` and `revised-scope-checklist.md`.

The PR 4 branch was committed and pushed at `d28624f`, with no PR published.
Follow-up edits were prepared above that revision and are included in the PR
branch. Use its final pushed SHA for CI and delivery evidence; do not substitute
an earlier CI result for the final diff.

## Proposed IT-115 evidence comment

Production integration uses the real queue producer, compatible production
records and their matching copied scan. The dated verification record covers
visible/actionable queue entries; scan, answer, status and confidence before a
decision; exact `009` correction, Accept, original machine values,
attribution/history, restart/reopen/JSONL export, unchanged other records,
regeneration/Undo, stale versions, retries and disposable-local-remote sharing.
See `docs/it115-verification.md` for actual current results and limitations.
Automated tests and any explicitly AI-assisted walkthrough are technical evidence;
they do not establish a human TC-M07 pass.

IT-115 remains In Progress. TC-M07 requires a human executor other than Skanda,
with screenshots at steps 3 (evidence visible), 4 (correction/save) and 5
(reopen/export). Human executor/result remain blank pending actual execution.
The prepared instructions are in `docs/it115-acceptance.md`. Its queue, save and
store dependencies must function; their ticket statuses do not impose additional
acceptance requirements. D029 wording corrections are proposed separately.

IT-116's unaided Archives usability check remains downstream. IT-125 is needed
only for a final dual-scored corpus claim. Jacob's requested physical Windows
acceptance and administrator live-data checks remain separately labeled rollout
items. PR 4 is not published; final changes still need publication, final-SHA CI,
independent approval and merge before owner closure under the Definition of Done.

## Proposed dated Test Report addendum

Date: 19 October 2026. Scope: IT-115 production integration using disposable
compatible records, matching scans and a local Git remote. Attach the current
`docs/it115-verification.md`, relevant logs and the final code/diff identity.
Record automated and AI-assisted checks separately from human execution.

Human TC-M07 execution status: **NOT RUN**. Executor: ______ (not Skanda).
Date/build: ______. Screenshot 3: ______. Screenshot 4: ______.
Screenshot 5 and exported field excerpt: ______. Observed result: ______.
Failure/follow-up: ______.

Downstream TC-M08 / IT-116: pending; no unaided usability pass claimed.
Physical Windows rollout requested of Jacob: actual executor/date/build/evidence
and observed result remain blank until execution. Preserve the 08 October Test
Report as historical rather than replacing its dated totals with these runs.

## Proposed IT-111 and IT-113 storage wording

Authoritative regional JSONL contains each current field and optional review
state/history. An in-memory index rebuilt at startup supplies direct lookup. A
decision validates the changed record, atomically replaces its JSONL file and
updates the index under the writer lock. Restart reconstructs the index; no
second durable database or dual-write operation exists. D029 governs review-data
sharing, one writer per checkout and manual same-region reconciliation.

For IT-111, replace database/SQLite and dual-write language with this model while
retaining direct retrieval, review state/actor/time and the explicit authoritative
record boundary. For IT-113, describe the implemented index, atomic writes and
restart/queue-regeneration behavior; link the corresponding persistence,
regeneration and sync tests from the dated verification record. #52's merged
implementation and the actual checks are evidence to assess against its ACs.
Do not invent a new owner sign-off table or equate ticket status with a missing
implementation. Apply no status change from this draft.

## Proposed IT-112 evidence note

The merged save logic was exercised through the built reviewer and real queue
producer on disposable production records. Its AC1 evidence is the corrected
value in JSONL export; AC2 is `origin: corrected` with the original machine value
retained; AC3 is comparison showing every other record unchanged. Restart,
history, repeated correction, regeneration and Undo regressions provide supporting
integration coverage. Link current test names/results and copied-record evidence
from `docs/it115-verification.md`. Evaluate its own ACs without adding unrelated
usability, administrator or physical desktop requirements to this backend ticket.

## Proposed TC-M07 ownership clarification

TC-M01–05 remain IT-131's scope. Assign TC-M07 to an actual non-author human under
IT-115 and retain the three screenshots and export excerpt with build identity.
A separate AI-assisted report cannot fill the executor/result fields. TC-M08's
unaided participant/observer requirements remain downstream IT-116; the physical
Windows rollout request to Jacob is separate from both cases.

Clarify TC-M07's correction step: if the first generated flag is an accept-only
identity, inspect it and select an editable numeric flag for steps 3–5. Record
the chosen field. A test edit on disposable records is not a claim of archival
transcription accuracy. This reflects existing allowed actions without expanding
the implementation to identity editing.

## Proposed Product-document corrections

- **D022 / Decisions:** identify Client Meeting #4 on 02 October as the accepted
  routing confirmation; the old 04 October reference was stale. Keep the rule
  tied to D016's agree constant, with null scores/non-ok statuses queued. The
  producer additionally routes flagged dwelling identities; bounded-v1 identities
  remain accept-only. Preserve historical calibration claims with their dates.
- **Hi-fi design:** retain the PDF as design history. D029 supersedes separate
  progress-file storage and per-region PR sharing: review metadata lives in JSONL
  and sharing uses `review-data`. The design's disclosed stand-in scans do not
  establish matching-source acceptance. Front/person/handwritten/reverse editing,
  identity changes, strike editing and regrouping are deferred in bounded v1.
- **Locator scope:** printed field names, textual Left/Middle/Right location,
  whole-card scan and manual zoom/magnifier are supported. Automatic field
  coordinates, highlighting and zoom-to-field remain outside IT-115.
- **Test Cases:** describe merged PR1–3 and current IT-115 In Progress status;
  leave TC-M07 Pending until genuine evidence arrives. Preserve the actual
  five-step case and three screenshots without adding the entire technical
  failure/retry regression suite to the human task.
- **How We Tested / Test Plan:** update outdated PR draft/merge statements and
  counts from verified current evidence. Describe real browser coverage alongside
  component/backend tests, distinguish D022 routing from optional banding, and
  keep benchmark precision separate from confidence cutoff or corpus accuracy.
- **IT-116 instructions:** check button names and first-use Help against the
  current screen, retain exact digits/leading zeros, and identify supported coding
  fields. Keep its participant observation sheet empty until actual execution.
- **Architecture:** JSON Lines is the implemented export; CLI/XML alternatives
  are historical. IT-115's deliverable is the GUI. Existing no-database wording
  should match D029 and the actual implementation.
- **Deferred work:** preserve IT-134's FR-06/client decision gap and IT-125's final
  dual-corpus scope explicitly. Do not silently add their features to PR 4.

## Proposed owner checklist

1. Verify current functional AC1–3 evidence and complete human TC-M07.
2. Commit/publish the final PR 4 changes, coordinate the documented #68 overlap,
   verify CI on the final pushed SHA, obtain independent approval and merge.
3. Close IT-115 as its owner only when its actual ACs and DoD are satisfied.
4. Keep IT-116 downstream and administrative review-data readiness separate.
5. At the end of the handoff, Jacob performs the requested physical Windows
   shortcut/quoted paths/browser/scan/save/Undo/restart/port-collision checks on a
   disposable sample and records actual results. Do not substitute Windows CI.

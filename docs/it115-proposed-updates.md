# IT-115 acceptance and dependency audit — 19 October 2026
Read-only live Linear audit. No ticket, document, status, comment or GitHub state changed. Raw local retrieval evidence is in /tmp/it115-audit/live-linear-evidence.json and /tmp/it115-audit/document-comments.json. This file contains proposed updates only; apply none automatically. All retrieved issue and document comments were read (no pagination remained).

## Current state and branch
IT-115 is already Done (completed 18 October 2026 13:04 UTC), despite TC-M07 remaining explicitly Pending and backend rollout sign-off remaining outstanding. This audit cannot validate that closure from genuine human evidence. Do not claim this session closed or reopened the ticket.
Exact Linear gitBranchName: skandar/it-115-reviewer-screen-a-queue-to-browse-and-a-screen-to-review.
IT109 Done; IT110 Done; IT111 In Progress; IT112 In Progress; IT113 In Progress (briefly Done then reopened 13 October); IT114 Done; IT116 In Progress; IT125 In Review; IT131 Todo; IT134 archived Todo.

## Acceptance mapping
IT115 AC1: every eligible flag from US13 queue visible/selectable. Prove producer→loader→API→browser; all statuses, nullable record_id, shared identities, multiple households, Municipality per household and printed field order matter. Unresolved diagnostics must remain visible and blocked.
AC2: source scan, current/machine answer, status and score before acting. Matching real scan + real record required; actions disabled until scan loaded, missing/error scan blocks writes. Code/label where present; genuine unscored values shown honestly.
AC3: actual review save and export through IT112, persisted IT113 state. Prove accept/correction, exact 009 string, machine original, attribution/time/history, restart/reopen/export/queue regeneration and untouched-record preservation.
User Stories AC14.1 adds rerun retention; AC14.2 gives same pre-decision evidence; AC11.3 status/confidence visibly flagged.
DoD: acceptance met; independently approved PR merged main; local/CI lint+format+pytest (plus frontend); docs changed; owner closes; known gaps tracked. Local-only work necessarily leaves publication/independent approval/merge/final pushed-SHA CI outstanding.

## Dependencies and scope
IT109 (queue), IT112 (save), IT113 (store) explicitly block IT115. Merged implementation is distinct from their acceptance sign-off. IT111 is IT113 decision prerequisite; ticket text contradicts D029. Do not pretend outstanding sign-off complete.
IT116 depends on IT115; TC-M08 NFR09 non-engineer Archives staff test is downstream, not automatically a prerequisite to this ticket.
IT125 dual-scored final corpus is not an explicit IT115 dependency. Gemini-only compatible production records can prove integration: single-extractor 0.91 correctly queues. Final dual dataset required only for a separately stated final-corpus acceptance claim.
IT131 currently covers TC-M01–05, yet refers TC-M06–08 to IT110/116; TC-M07 needs explicit ownership in proposed update.
IT134 FR06 is archived Todo with no decision/client notification evidence. Track strike editing/FR06 as deferred; do not expand PR4 to invent human strike handling.

## Genuine human and Windows evidence
Test Cases: TC-M07 Pending, executor explicitly Not Skanda. Steps: open region, selected flag, verify scan+machine value+status+confidence, correct/save, reopen/re-export, screenshot steps 3/4/5.
Test Report 08 October: no manual test executed; AC11.3/14.2 Not run. How We Tested also explicitly says none run and AI-drafted tests cannot be evidence from a model saying passed.
NFR09 instructions are Draft, written against PR1/2; empty observation sheet proves no actual usability result.
Runbook rollout checklist requires physical Windows shortcut, spaces in paths, scan rendering, browser launch, port collision, saves/undo/restart, credentials and failed-push retention. Windows CI synthetic Git/filesystem/API tests are not that acceptance.
No fetched comment provides completed TC-M07 or physical desktop acceptance. Prepare runnable materials with empty executor/result fields; user must nominate non-author and Windows operator, run and record real evidence.

## Explicit contradictions and proposed corrections
1. IT111 description/scope/AC: replace database/SQLite/dual-write model with: 'Authoritative region JSONL contains full field and optional review state/history. An in-memory index built at startup supplies direct retrieval. Decisions validate the changed record, atomically replace JSONL and update the index under the writer lock. Restart rebuilds the index. There is no second durable store.' Retain direct lookup, original values, state/actor/time and queue-rerun AC; link D029.
2. IT113 description: same model correction; implementation #52 is merged but acceptance/rollout sign-off remains. Proposed sign-off table must separately list persistence/restart/queue regeneration/local Git sharing/Windows/human result.
3. IT112: proposed evidence links actual save regression/integration tests for AC1–3, byte/deep equality for other records, original machine snapshot after repeated corrections. Do not mark Done from merge alone.
4. D022 dates: repo and Decisions row say confirmation 04 October; 02 October Client Meeting #4, IT109 and user stories say 02 October. Proposed wording: 'Accepted following Client Meeting #4 on 02 October 2026; the earlier 04 October reference was stale.' Rule itself remains status ok + confidence >= D016 agree (0.97), null always routes. Replace obsolete 'every confidence None today' with Gemini-only score 0.91; preserve historical date claims as history, not current state.
5. Decisions D022 row says identity routing deferred, but repo D022 assigns flagged dwelling identities to queue producer. Update to 'Per-field rule does not read dwelling.flags; queue producer additionally routes flagged dwelling identities. Identity fields are accept-only in bounded review v1.' Only claim actual landed behavior once verified.
6. Hi-fi v1.5 p1 proposes separate progress file, PR per region, storage/schema unresolved. D029 supersedes: per-field JSONL review history and review-data direct pushes, no per-batch PR. Preserve PDF as design history, attach a scope/supersession note rather than claiming all frames implemented.
7. Hi-fi p1 discloses fixture scans r01 stand in for different 03-0005 values. Those pages are not matching scan evidence. Use matching copied originals for production acceptance.
8. Hi-fi front/person/free-text, identity changes, human crossed-out editing are broader than v1. Document v1 as C1/C2 supported mapped fields; shared ownership first coding household/card; identity and existing-negated accept-only; front/person/handwritten/reverse, identity amendments, negation edits and regrouping deferred. Card tabs/read-only context do not imply edit support.
9. Textual locator scope: printed field labels, Left/Middle/Right column and where line; whole-card scan with manual zoom/magnifier. No field coordinates, automatic highlight or automatic zoom-to-field. Low-fi p32 and IT115 explicitly defer automatic highlighting.
10. Test Cases TC-M07 status: replace stale 'first slice merged, issue still in progress' with 'PR1–3 merged; Linear currently Done, manual independent acceptance remains unrecorded. PR4 integration evidence [local artifact], TC-M07 human execution pending.' Keep genuine result Not run until executor supplies screenshots.
11. Test Report 08 October should remain historical at c88e86f; prepare a dated addendum/new report, not overwrite old test totals or imply new runs occurred then. Record PR4 local SHA/base/diff fingerprint, exact command counts, fixtures/scans, automated vs human distinctions.
12. How We Tested has outdated #59 last PR, #62 draft, Windows #61 pending and 25/43 frontend counts. Update from verified live merge/CI + current command output; remove draft/pending claims only when independently verified.
13. Test Plan still makes banding the decided mechanism and asserts frontend tests in fake browser only / Playwright future. D022+banding-off adopted, real E2E #62 exists. Update current layers/rule; benchmark precision 97.0 is distinct from confidence cutoff and not universal corpus accuracy.
14. Usability draft: check actual button names ('Correct', save label, welcome dismissal, Save and Exit outcome), preserve leading-zero instruction, clarify only supported coding fields. Copy exact sample launch output after actual production sample generation. Do not fill observation sheet from automation.
15. Architectural Requirements says output JSON or XML and CLI enough; D007 output is JSON Lines, IT115 explicitly requires GUI for this deliverable. Note XML/CLI as historical alternatives; resulting reviewer proof is GUI. 4+1 already correctly says no database but obsolete 'in progress' remains.

## Required remaining actions before closure claim
- User publishes PR4 with independently reviewed final diff; CI passes exact final pushed SHA; user merges under D002.
- Team records IT111/112/113 acceptance reconciliation and sign-off without confusing merged code with acceptance.
- Non-author runs TC-M07 on matching real scan/record disposable sample, records date/build/executor/screenshots/export/restart result.
- Physical Windows operator runs runbook acceptance and records environment/build/results; synthetic Windows CI insufficient.
- Admin verifies review-data branch/protection/credentials/validation workflow and canonical reviewed-data ownership. Read-only existing review-save commits prove branch use but not every intended desktop credential or branch-rule behavior.
- Keep IT116 and FR06 deferred ownership visible; no fabricated TC-M08 or final dual-corpus claim.


## Exact proposed IT-115 evidence comment (not posted)

Production integration was audited against merged main 9cf8a35 on 19 October 2026. PRs 56/57/59/60/62/65 are merged. The coding-only producer's later-household Municipality, printed order and flagged-identity routing were verified. Read-only inspection resolved all 335,487 flags across 44 populated production regions. Disposable production acceptance used 75 dwellings, 4,650 generated flags and their matching original PDF copied into a new local sample. Automated checks verified exact 009 persistence, Accept, restart/reopen/export, original machine values, attribution/history, stale versions, retries, Undo, regeneration and sharing to a local bare remote. See docs/it115-verification.md for exact final results and limitations, and docs/it115-acceptance.md for the executable human checklist.

IT-115 currently shows Done, but this audit found TC-M07 Pending and no physical Windows desktop evidence. Do not treat agent or synthetic CI results as human acceptance. Proposed disposition: owner reconciles status with the outstanding gates; no automatic closure or reopening. IT-111/112/113 acceptance and D029 wording reconciliation remain outstanding. IT-116 is downstream; IT-125 blocks only a final dual-corpus acceptance claim. PR4 remains local/uncommitted until user publication, independent approval, final pushed-SHA CI and merge. The empty-assignment fix overlaps open #68 and needs coordination before publication.

## Exact proposed acceptance-result addendum (not applied)

Date: 19 October 2026. Scope: IT-115 production integration on disposable compatible production records and matching scans. Automated results: attach docs/it115-verification.md and final diff fingerprint. Human TC-M07: NOT RUN; executor and required screenshots outstanding. Physical Windows desktop: NOT RUN; operator/build/shortcut/paths/scan/save/undo/restart evidence outstanding. Overall human acceptance: NOT ESTABLISHED. Preserve the 08 October Test Report as historical; do not replace its dated results with these runs.

## Exact proposed IT-111/113 replacement storage wording (not applied)

Authoritative regional JSONL contains each current field and optional review state/history. An in-memory index rebuilt at startup supplies direct lookup. A decision validates the changed record, atomically replaces its JSONL file and updates the index under the writer lock. Restart reconstructs the index; no second durable database or dual-write operation exists. D029 governs review-data sharing, one writer per checkout and manual same-region reconciliation. Implementation is merged; production/human/Windows acceptance remains separately evidenced.

## Exact proposed IT-112 acceptance note (not applied)

Merged save logic was exercised through the built reviewer and the real flags producer on disposable production records. Exact digit strings, unchanged other fields/records, original machine snapshots, reviewer/time/history, restart, JSONL export, queue regeneration, Undo and local sharing were verified by the dated PR4 evidence. This supports implementation integration; rollout and required human/Windows acceptance are not signed off by this note.

## Exact proposed IT-131 ownership clarification (not applied)

TC-M01–05 remain this ticket's scope. Nominate a non-author executor for TC-M07 under IT-115 and a physical Windows operator; retain screenshots and exported copied records with build/diff identity. TC-M08 remains downstream IT-116 usability work. Do not infer a TC-M07 pass from merged browser tests.

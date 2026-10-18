# Proposed PR 4 (not published)

Title: **IT-115: verify production reviewer integration and prepare acceptance**

Base: `main`. Proposed head:
`skandar/it-115-reviewer-screen-a-queue-to-browse-and-a-screen-to-review-pr-4`.
No PR URL exists. All changes remain uncommitted for owner review.

## Proposed body

The reviewer has merged queue, save and UI implementations, but its earlier
demonstrations used hand-selected flags and did not establish the complete
production-record flow or required human acceptance. Production startup could
outlast the browser launcher's 30-second wait, and a fully reviewed regenerated
queue was incorrectly rejected as invalid startup input.

Extend the launch wait to a bounded five minutes and allow valid empty
assignments. Add a production acceptance helper that copies compatible regional
records and matching scans, uses the real flag producer, hashes source/copy bytes
and directs all sharing to a newly created disposable local remote. Add generated
queue and optional matching-production browser journeys, plus regressions for
source changes during preparation and alternate push destinations. Include the
acceptance contract tests in Windows CI. Reconcile dated documentation, textual
locator/editing scope and D029 storage/workflow decisions; provide source-plus-
assets launch instructions, a runnable human/Windows sheet and proposed ticket
updates without claiming sign-off.

Validation: 51 frontend tests, TypeScript/Vite build and 9 real-browser checks
passed, including the optional matching production sample. Final focused backend
acceptance/API suite: 20 passed, independently repeated. Full backend coverage run:
779 passed, 13 skipped, 2 xfailed, **1 pre-existing local-input branch-guard
failure**, 93% coverage. Final source-race regression was added after that full
collection and passed in final focused/independent checks. Ruff, whitespace,
both committed result trees and moved source-plus-assets package checks passed.
See `docs/it115-verification.md` for exact commands, chronology and limitations.

Production proof uses 75 copied dwellings, 4,650 generated flags and the matching
PDF, with exact `009`, Accept, original machine values, attribution/history,
restart/reopen/JSONL export, unchanged other fields, regeneration/Undo and local
sharing verified. Read-only whole-root compatibility resolves 335,487 flags in
44 regions. No original results, scans or live reviewed data were mutated.

Dependencies and overlap: merged #60/#62 fixes are retained without replay.
The small empty-assignment change overlaps open #68; coordinate ownership before
publication/merge. Do not stack or merge #66–69 implicitly: broader text editing,
scan downloads, automated release packaging and live-GitHub acceptance remain
their separate work. IT-116 is downstream. IT-125 is required only for a claim
about the final dual-scored corpus. IT-111/112/113 acceptance/storage reconciliation
remains outstanding.

IT-115 is currently Done in Linear, but TC-M07 remains Pending and no physical
Windows desktop acceptance was found. This PR does not establish closure. A named
non-author must execute TC-M07, a physical Windows operator must record the launch
workflow, and the owner/admin must complete rollout sign-off. Before merge,
verify CI on the actual final pushed SHA and obtain independent review per
DoD. Current base CI is green; no PR4 pushed SHA or CI result exists yet.

Owner handoff: commit and publish only after reviewing this diff, resolve overlap,
run final-SHA CI, obtain required acceptance and merge, then reconcile IT-115's
existing status. See `docs/it115-acceptance.md` and
`docs/it115-proposed-updates.md` for the exact unapplied checklist and updates.

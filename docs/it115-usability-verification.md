# IT-115 usability follow-up — 20 October 2026

## Branch decision

Use `skandar/it-115-reviewer-screen-usability-fixes` from main `06aaaec`, independently of PR 4 (#71).
PR 4 supplies acceptance tooling/documentation, while main already contains the
newer survey-front and notes editing, scan management, generated queue and
assignment-progress integration. No PR 4 code is required for this change.
The work is in a separate local worktree to preserve uncommitted acceptance
handoff files in the original checkout. Nothing is pushed.

## Requested behavior

1. Unqueued coding cards no longer appear in the card selector.
2. Survey fronts have a direct **Open survey front** button and their own selector
   entry, separate from coding cards. Interview notes remain accessible.
3. Printed field columns stay expanded; decided fields remain selectable.
4. **Previous field** and **Next field** browse without saving. Evidence and draft
   guards remain active.
5. A confirmed final decision shows **Card reviewed**, with **Next card** or
   **Back to queue**, and **Stay here**. Automatic advancement stays within the
   current card. Region completion excludes unresolved diagnostic-only work.
6. Reviewed cards appear in a final **Reviewed cards** group. Completed dwellings
   move below pending dwellings, retaining pending priority. Undo restores priority.
7. Reviewed cards/dwellings display **High · reviewed**. This means all supplied
   review fields are resolved without diagnostic blockers; it does not rewrite
   original machine confidence, field scores or originals.
8. The correction action and help now say **Fix**, retaining shortcut E and the
   existing decision API action.

Reliability details start closed to reduce clutter and remain available. Existing
read-only context, scan tools, history, undo, downloads, sharing, CSV export and
numeric/text correction behavior remain available.

## Verification

- Frontend: 70 unit/component tests passed; production build/typecheck passed.
- Browser: all 8 Playwright end-to-end tests passed against disposable real backend
  instances, including lost save responses, concurrent reviewers, missing scans,
  failed sharing, session recovery, completion/stay/undo/next and durable Unicode
  survey text editing.
- Full Python suite with branch coverage: **955 passed, 19 skipped**, 92% total
  coverage (314.61 seconds). Targeted backend: 153 passed, 1 skipped across six
  review test files.
- After the audit fixes, the targeted card-completion browser scenario passed again.
- Ruff lint/format and `git diff --check` passed.
- Computer use: inspected the actual 1280×720 UI with synthetic scans; exercised
  Previous/Next, same-card automatic advance, completion choices, reviewed High,
  direct survey-front access, text Fix, next-card navigation and progress reload.
- Independent audit found two completion/order edge cases; both were fixed and
  independent regressions added. Final independent frontend run: 70 passed;
  independent backend dwelling suite: 29 passed. No remaining actionable findings.

The browser and backend demonstrations use synthetic disposable data and local
Git remotes, without editing or sharing production records.

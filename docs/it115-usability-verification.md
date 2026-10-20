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

## Identity correction follow-up — 21 October 2026

Municipality, dwelling and household identity fields now support Fix, with
format validation, duplicate-ID checks, dependent record-ID/note-link updates,
and guarded Undo. Survey-front text remains independent of coding identities;
corrections preserve the original physical card and person associations.
Historical extraction flags appear as neutral, collapsed Source notes. Current
identity and structural problems have a separate Needs attention message.

- Frontend: 88 tests passed; production build and browser-test typecheck passed.
- Browser: all 13 real-backend scenarios passed, including correction and Undo
  for each coding identity, preserving leading zeros and a dwelling letter suffix.
- Full Python run: 974 passed, 19 skipped, with one stale accept-only assertion.
  After updating that assertion, the queue integration suite passed (4 passed,
  1 skipped). A final service/text/dwelling/schema run passed all 152 tests,
  including two added legacy municipality-inheritance regressions.
- Ruff lint/format, JSONL corpus validation and diff checks passed.
- Computer use: saved and undid a municipality correction, saved `0006b`,
  verified canonical ID `27-0006B-01`, and inspected Fix, advancement, history
  and neutral source notes at 1280 × 720 on disposable synthetic records.
- Independent final audit passed after fixing legacy shared municipality
  propagation; inherited household IDs and note links now restore on Undo.
- All 44 original result files match the full-corpus preview's baseline hashes.
  The preview uses copied data; the synthetic visual fixture was removed.

This verification used local data copies and disposable synthetic fixtures.

## Independent edge-case audit — 21 October 2026

Three independent reviewers tested input behavior, identity side effects, and
extraction/persistence compatibility. Seven gaps were reproduced and fixed:

| Gap | Verified behavior after the fix |
| --- | --- |
| Identity input silently truncated a longer reading into a valid prefix | Full invalid input remains visible; Save and Enter cannot submit it. |
| Municipality mirroring bypassed a crossed-out counterpart's restriction | The correction is rejected atomically when it would change the protected copy. |
| Undo could not restore a duplicate that existed before correction | Original physical conflict owners may be restored; new or replacement owners still block Undo. |
| Legacy IDs lost their municipality during unrelated corrections | Each card's stored ID retains its municipality evidence; missing conflicting evidence is never guessed. |
| Extraction reruns overwrote alias metadata and blocked Undo | Each alias keeps its own machine evidence and review payload. |
| Note insertion, removal or reordering could restore a link onto the wrong note | Undo checks physical note topology and refuses changed ownership/order before indexing links. |
| Repairing the sole household's identity left null note links unresolved | Unambiguous links update with the identity; Undo restores their original null values. |

Six user-event regressions exercise typing, pasting and Enter across all three
coding identities; 16 backend regressions cover the independent edge and
persistence findings. The final cross-review independently ran those 16 tests
and found no remaining blockers. Computer use confirmed that `1234AB` remains
intact, shows format guidance, and leaves Save disabled after Enter. The disposable
visual fixture was removed without saving that invalid input.

Final verification on the complete patched code:

- Python: **993 passed, 19 skipped**, 93% branch-aware total coverage.
- Frontend: **94 passed**; production build and browser TypeScript passed.
- Real browser: **13 passed**, including overlength input, blocked Enter,
  normal identity corrections and Undo.
- Ruff lint/format and `git diff --check` passed.
- All 44 original corpus files still match their baseline hashes. The full-corpus
  preview was restarted with the final backend.

Ambiguous legacy identity evidence and changed note ownership remain explicit
conflicts requiring data repair; the review tool does not guess their association.
The verification did not alter the original corpus or publish review results.

# Proposed PR 4 (not published)

Title: **IT-115: verify production reviewer integration and prepare acceptance**

## What changed

Verify the reviewer against the real queue producer, compatible production records and matching scans using disposable copies and local Git remotes, including exact-digit saves, restart/export, history, Undo and queue regeneration. Fix slow-start browser launch and empty assignments, isolate the offline rebuild test from original data, and document dependency evidence, scope and the remaining human acceptance steps.

The empty-assignment fix overlaps open #68 and needs coordination before merge. Broader work in #66–69 is excluded; IT-116 usability is downstream, and IT-125 is needed only for final dual-scored corpus claims.

## Linear issue

[IT-115 — Reviewer screen](https://linear.app/um-it-project/issue/IT-115/reviewer-screen-a-queue-to-browse-and-a-screen-to-review-each-field-fr)

IT-115 remains In Progress. Human TC-M07 is pending; Jacob's physical Windows check is a separate requested rollout item. Automated walkthrough evidence does not establish either result. Proposed ticket/document updates are prepared locally and have not been applied.

## How it was tested

- `uv run pytest --cov=survey --cov-branch --cov-report=term-missing`: **782 passed, 13 skipped, 2 xfailed**, no failures; **93% coverage**.
- `npm --prefix frontend test`: **51 passed**; TypeScript/Vite build passed.
- `SURVEY_ACCEPTANCE_SAMPLE=<fresh-disposable-sample> npm --prefix frontend run e2e`: **9 passed**, including matching production records/scans, uncertain retries, stale reviewers, missing scans and sharing failure recovery.
- Ruff lint/format, `git diff --check`, root and Qwen result validation, and relocated source-plus-assets launch passed.
- Production-copy verification used **75 dwellings and 4,650 generated flags**. Exact `009`, machine originals, attribution/history, restart/reopen/export, unchanged other records, regeneration/Undo and local sharing passed; source hashes remained unchanged.
- Independent review and fix verification passed. The repaired offline rebuild/branch-guard suite passed **10 tests**, independently repeated.

See `docs/it115-verification.md` for command results and limitations, `docs/it115-dependency-evidence.md` for the backend AC mapping, and `docs/it115-acceptance.md` for the human/Windows handoff. Final pushed-SHA CI, human TC-M07 and physical Windows execution remain outstanding. Frontend/browser results remain applicable because the follow-up changes affect tests and documentation only.

## Definition of Done

- [ ] Acceptance criteria on the issue are met — functional automation passed; required human TC-M07 evidence remains pending.
- [ ] Checks pass (`uv run ruff check .`, `uv run pytest`; CI also runs a secret scan) — local checks passed; PR CI on the final pushed SHA is pending.
- [x] Docs updated if behaviour or setup changed.
- [ ] Reviewed by someone else — independent agent reviews passed; required PR approval remains pending.
- [ ] Linear issue is linked, and closes when this merges — linked above; enable closure only after acceptance and DoD are satisfied.

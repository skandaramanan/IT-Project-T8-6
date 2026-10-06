# D025 — The extracted dataset is committed (amends D004)

**Status:** Accepted
**Date:** 2026-10-04
**Decided by:** Qitao Shi (IT-126 assignee)
**Linear issue:** IT-126

## Context

D004 keeps `data/` gitignored, "including anything derived from the scans".
The 02/10 client meeting agreed to share corrected JSON through GitHub, and the
review tool (US-13 / US-14) needs the dataset somewhere it can read and write.

## Decision

One exception to D004: `results/<region>.jsonl`, the scored D007 records, is
committed. Everything else derived from the scans — scans, raw model responses,
the benchmark set, spike output — stays in `data/`, gitignored.

- IT-120's pipeline writes there by default (`SURVEY_OUTPUT_DIR=./results`).
- Raw Gemini responses stay in `data/runs/`. IT-125 needs them, but they are
  not the dataset.
- The IT-73 structure-spike output that used to sit in `results/` moves to
  `data/structure/`.

Size is fine: about 6,500 cards × 62 fields × 6 keys is tens of MB in total and
about 1 MB per region, well under GitHub's 100 MB file limit.

**The review tool writes records, never the schema.** `schema/` changes only
through a reviewed PR. A correction that could change the schema would make
every downstream validation meaningless.

## Open question: protected `main` (D002)

`main` rejects direct pushes, so the review tool cannot commit corrections to
it. Options:

- **(a) A long-lived `review` branch.** Reviewers' corrections commit there,
  and one PR per region merges it into `main` when that region's review is
  done. *Recommended:* keeps D002 intact and gives one reviewable PR per region.
- **(b) A separate unprotected data repo for `results/`.** Breaks the
  one-repo goal.
- **(c) A ruleset bypass for the review tool's token.** Weakens D002 for every
  path, not just `results/`.

This record states the constraint. The choice belongs to the first review-tool
ticket and must be made before that ticket starts.

## Consequences

- Anyone with a local `results/` folder from IT-73 must move it to
  `data/structure/` before pulling, or `git status` will offer to commit it.
- `results/` diffs show up in PRs; reviewers should expect large but
  line-oriented JSONL changes.

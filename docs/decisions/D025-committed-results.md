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

### A second extractor's results (IT-124, 2026-10-16)

A second extractor's run is committed beside the primary one, under
`results/<extractor>/<region>.jsonl`. The folder is the extractor's cache name,
for example `results/qwen2.5-vl-server-2000000px/`. Same schema, same
validation: CI runs `survey validate-results` on every folder under
`results/`, not only the top level.

The two arms are kept apart on purpose. Nothing reads the subfolder as the
dataset: the review tool and `survey flags` use `results/<region>.jsonl`.
IT-125 merges the arms by card (D026), and the merged output replaces the
top-level files. The Qwen run is 39 MB, at most 2 MB a file, beside the
primary run's 110 MB, so each file stays well under GitHub's 100 MB limit.

## Sharing branch: resolved by D029

[D029](D029-review-persistence.md) selects the same repository's `review-data`
branch and a separate checkout for the authoritative review dataset. Code and
schema changes continue through reviewed PRs to `main`. Corpus results may be
included in an extraction PR as a reproducible baseline, then handed to the
review-data owner; reruns must preserve reviewed fields rather than overwrite
that branch with a fresh baseline. Do not run extraction in the active review
checkout concurrently with its writer.

Raw responses and scan images remain in the restricted shared archive, outside
Git. Small region/PDF/page classification decisions and run summaries in
`docs/runs/` document how the baseline was built. This does not move scans,
raw prompts or model responses into Git. Git LFS or external dataset hosting
would be a new team decision, not a prerequisite imposed by this PR.

The previous alternatives below are retained as historical context; D029
resolved the open question.

### Original alternatives: protected `main` (D002)

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

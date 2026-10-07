# D027 — A region is one archive unit folder

**Status:** Accepted
**Date:** 2026-10-07
**Decided by:** Skanda Ramanan (IT-122 assignee)
**Linear issue:** IT-122

## Context

FR-02 asks for the dataset to be processed in region batches matching how the
scans are already organised, with output partitioned by region and no
cross-contamination. The archive arrives as 45 unit folders (`216412` …
`216463`), one PDF each, and no mapping from unit to suburb exists. The region
name becomes a results file name (D025), a cache folder, and the reviewer's
queue filter (02/10 client meeting), and the full-corpus runs (IT-123, IT-124)
are split across five machines.

## Decision

- A region is one unit folder. `survey extract <folder>` names it after the
  folder; `--region` overrides.
- A region name is lowercase letters, digits, `-` and `_`. Anything else is
  refused before the run, so a name can't escape `results/` or collide by case
  on macOS/Windows.
- A run refuses a results file holding a record of another region, before any
  extraction, the same way it refuses a damaged one (D026).

## Alternatives

- **Suburb names** (`williamstown`). Friendlier in the reviewer filter, but no
  mapping exists, so every name would be a guess.
- **Free-form `--region` only** (IT-120). One mistyped name on one machine
  makes two files for one unit.

## Consequences

- IT-123 and IT-124 run each folder with no name to type:
  `uv run survey extract data/Wilfred_Prest_Survey_Data/216429`.
- Running one folder under two names still duplicates its cards across two
  files; a run never reads another region's file to catch it.
- Renaming regions later means renaming files and rewriting `region` on every
  record, including reviewed ones.

## Revisit if

The Archives supply a unit-to-suburb mapping the reviewers would rather filter
on.

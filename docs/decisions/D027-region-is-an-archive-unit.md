# D027 — A region is one scan folder

**Status:** Accepted (amended 2026-10-07: a folder-to-suburb mapping exists; folders are UMA items, not archive units)
**Date:** 2026-10-07
**Decided by:** Skanda Ramanan (IT-122 assignee)
**Linear issue:** IT-122

## Context

FR-02 asks for the dataset to be processed in region batches matching how the
scans are already organised, with output partitioned by region and no
cross-contamination. The archive arrives as 45 folders (`216412` … `216463`),
one PDF each. Each folder is a UMA item, named by its "Node ID" in the
`metadata.csv` that ships with the scans. They are not archive units: the CSV's
`Unit` column groups several folders per unit (Unit 0001 holds Box Hill and
both Brighton parts).

`metadata.csv` gives each folder a title, which is usually a suburb plus its
code-book municipality code ("Box Hill 00", "Oakleigh 19"). It is not
one-to-one with suburbs:

- 9 suburbs are split across several folders ("Brunswick 02 - Part 1" to
  "Part 3", "Prahran 21 - Part 1" to "Part 4").
- Some folders are not a single suburb ("Braybrook 28, Maribyrnong,
  Sunshine", "Shared houses Prahran", "Rise in income- Footscray").
- Williamstown has two folders, `216459` and `216460`, one of them without a
  code.

The region name becomes a results file name (D025), a cache folder, and the
reviewer's queue filter (02/10 client meeting), and the full-corpus runs
(IT-123, IT-124) are split across five machines.

## Decision

- A region is one folder. `survey extract <folder>` names it after the
  folder's Node ID; `--region` overrides.
- A region name is lowercase letters, digits, `-` and `_`. Anything else is
  refused before the run, so a name can't escape `results/` or collide by case
  on macOS/Windows.
- A run refuses a results file holding a record of another region, before any
  extraction, the same way it refuses a damaged one (D026).

## Alternatives

- **Suburb names from `metadata.csv`** (`brunswick`). Friendlier in the
  reviewer filter, but a suburb split across parts would mean one region per
  several folders. That makes each folder's run touch a shared results file,
  which the five-machine split can't do safely. Multi-suburb and "shared
  houses" folders have no single suburb name at all.
- **Free-form `--region` only** (IT-120). One mistyped name on one machine
  makes two files for one folder.

## Consequences

- IT-123 and IT-124 run each folder with no name to type:
  `uv run survey extract data/Wilfred_Prest_Survey_Data/216429`.
- A suburb's records are spread across one results file per part. A dwelling
  whose cards straddle two parts is split into two regions and is not
  re-joined.
- Running one folder under two names still duplicates its cards across two
  files; a run never reads another region's file to catch it.
- Renaming regions later means renaming files and rewriting `region` on every
  record, including reviewed ones.

## Revisit if

- Reviewers want to filter by suburb. Show the `metadata.csv` title as a
  display label next to the region, and group parts under it, rather than
  renaming regions.
- A check is wanted that a record's coding-card Municipality matches its
  folder's code in the title.

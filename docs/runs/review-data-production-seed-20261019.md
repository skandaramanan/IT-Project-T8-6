# Production review-data seed — 19 October 2026

The previous `review-data` tip, `752b8093f3c7afc250be93bef39ad62940b75d2c`,
is preserved at
[`archive/review-data-acceptance-2026-10-18`](https://github.com/skandaramanan/IT-Project-T8-6/tree/archive/review-data-acceptance-2026-10-18).
All 38 commits from the acceptance seed `f641e43` through that tip were authored
by acceptance-test identities. Its active dataset comprised two synthetic regions
and a two-dwelling 216418 sample; it was not a complete production dataset.
The archive retains the test corrections and undo history without treating them
as production reviewer decisions.

Production seeding merges the compatible published `main` revision
`424dc57f101fc370e5667d5ce82ea5772faf4175` into the existing data branch, selecting
that revision's complete tree as the baseline. Both histories are retained; no
force push, branch deletion or history rewrite is used. The seed's `results/`
tree is exactly `7f35cc32617b079d4a21dbb829ebf3a6b41522af`, matching that `main`
revision byte-for-byte, including `merge-manifest.json`, the independent Qwen
outputs and all existing protected human edits in the merged records.

The canonical top-level dataset contains 44 nonempty region JSONL files,
5,375 dwellings and 5,430 physical coding cards. Manifest region 216461 is
explicitly empty (front-only material with no coding records in either arm).
The full dataset is retained irrespective of review eligibility: agreement and
unflagged fields are included. Only review flags select work for the queue.
The synthetic demo files and acceptance sample payloads are absent from the
active production tree; their originals remain in the archive and Git history.

Local validation uses `survey.records.read_dataset` on every top-level region
file, covering schema and review history across the complete canonical dataset.
The exact Git results-tree comparison also verifies preservation of the published
secondary outputs and provenance without re-extracting or rescoring any field.

Use fresh production checkouts after this change. Retire all former acceptance
workspaces and their pinned old runners: their original manifests target
`review-data`, and old code must not be rerun there. Updated acceptance tooling
rejects those manifests, including for repinning. Prepare a separate workspace
on `review-data-acceptance`; the application production default remains
`review-data`. Production rollout, credentials, reviewer assignments and scan
availability remain the operator's responsibilities.

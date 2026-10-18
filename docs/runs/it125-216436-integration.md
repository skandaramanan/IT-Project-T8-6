# IT-125: 216436 integration and pull recovery — 18 October 2026

## Git recovery

The attempted pull fetched both merged PRs but left local `main` at `5569133`.
There was no active merge or unresolved conflict. The only overlapping local
path was `results/216436.jsonl`, containing the previous IT-125 paired output.

All 66 modified/untracked IT-125 files were copied, hashed and saved in
`data/it125-pull-recovery-20261018/files/`, together with a binary working-tree
patch and snapshot metadata. Only the overlapping file was returned to its
previous tracked baseline, then `main` fast-forwarded to `50ad42b`:

- #63 / `5b45a21`: 19 additional Gemini coding sources and source-verified corrections.
- #64 / `50ad42b`: 146 fresh Qwen coding-source exports for the complete scan.

All other local files matched their pre-pull hashes immediately after the
fast-forward. No branch switch, reset, stash, new commit, push, PR mutation or
Linear update was performed. Subsequent local edits add a stale-cache guard and
this status documentation; the ongoing IT-125 work remains uncommitted.

## Current active dataset

- 44 nonempty region files, 45 regions accounted for.
- **5,375 Gemini dwelling records / 5,430 coding sources.**
- **5,422 Qwen dwelling records / 5,429 coding sources.**
- Both arms now publish **146 sources in 216436**, retaining all 127 prior
  coordinates and adding 19 pages. The sole missing exported Qwen source across
  the corpus remains 216419 / `423497_1973-0002-00008-00001.pdf` / p103.
- **43 regions retain their existing IT-125 paired output, byte-for-byte.**
- **216436 currently uses the newly merged Gemini baseline with standalone
  scores.** No field clears review through confidence alone under D022. Its new
  protected source corrections remain intact and are not reopened by this pull. It is explicitly pending paired
  scoring; old paired scores have not been copied onto the new Qwen run.
  Its 146 coding cards have standalone scores; the retained upstream baseline
  still has 151 uncalibrated front/back card scores at null. Current whole-corpus
  AC2 is therefore temporarily pending for this region as well. The final paired
  merge will apply the established zero-evidence card fallback after the fresh
  Qwen handoff is verified.
- All **218 excluded sources** remain excluded, including 216436 p272/p570.

The 17 October merge report is retained as a historical snapshot, with a clear
update banner. Its overall agreement/review percentages must not be interpreted
as current whole-corpus figures. `results/merge-manifest.json` records the new
input hashes, exclusions and the region's pending status.

## Scan and Gemini cache adoption

The complete 594-page PDF is installed under the canonical review path:
`data/Wilfred_Prest_Survey_Data/216436/1264179_1973-0002-00025.pdf`.
Its SHA-256 is
`6d7b64bc0bb82e499ac35a6d32872409572ec484f8670a9368b834ab9c3796f0`.
The former 514-page PDF is preserved in the recovery directory as
`1264179_1973-0002-00025-514-pages.pdf` (SHA-256
`7c9a57e270ea48038c593f40781d9f113c67d892d8710f45585b5e9d01fab5f6`).

All 60 added Gemini cache entries (19 coding, 20 fronts, 20 notes, one identity
crop) were copied from the isolated additions worktree into `data/runs/216436/`.
No existing cache was overwritten. Each entry matches its counterpart in the
safety-checked handoff archive. An updated immutable primary input snapshot is
available at `data/it125-inputs-after216436/results/`; the older
`data/it125-originals/results/` remains unchanged.

The Qwen run document describes changed page order. Independent visual matching
of the actual available PDF hashes confirms that the original card-bearing
pages retain their coordinates, with 80 appended pages. Image resolution and
compression differ. This does not make old Qwen readings equivalent to the
fresh run: 125/127 were replaced, with 684 normalized field differences.

## Remaining input needed

Jacob has not yet shared a refreshed raw handoff for this region. The existing
archive supplies 127 **old** Qwen readings, lacks the 19 added pages, and does
not reproduce the newly merged export. The same PDF filename and model
configuration do not prove that a cache belongs to the current reading.

To finish IT-125 scoring here, share the fresh region cache directory, including
all 146 kept readings and its `extractor.json` manifest. The rerun log and scan
hash should accompany it for provenance. A complete archive of every other
region is unnecessary. **No further model run is required.**

The merger now checks each Qwen export field against that household's normalized
raw cache before it scores or writes. It respects first-household ownership of
shared dwelling fields, exact aliases, explicit blanks and omissions. Stale
values or reviewed discrepancies refuse. All other 43 regions pass this check;
the old 216436 cache correctly refuses at p3, Structural Material.

After receiving the refreshed handoff, verify archive safety, preserve existing
caches, compose a separate complete cache tree, run the merger with
`--primary data/it125-inputs-after216436/results`, validate the candidate and
refresh its report before replacing this region's active scores. The new
source-verified Gemini corrections must survive unchanged.

## Local verification evidence

- `data/it125-pull-recovery-20261018/snapshot.json`: pre-pull hashes and Git state.
- `source-adoption.json`: PDF and cache adoption, backups and updated input snapshot.
- `after-pull-status.json`: current coverage and explicit pending status.
- `pytest-final.log`: combined IT-125 and merged-PR regression suite.
- `pytest.log`: initial run identifying the merged integration test's branch-isolation assumption; fixed with a scratch-directory replay and a
  separate active-main refusal check.
- `validation.log`: current active dataset schema validation.
- `final-review.md`: independent verification of pull preservation, coverage and safety.

The supplementary handwriting / numbers-first review preference and the policy
to ignore unsupported forms are separate review-workflow alignment work. They
were not silently changed while repairing this pull.

Final combined verification: **791 passed, 13 skipped**, no calibration xfails.
Ruff lint/format, whitespace checks and active dataset validation pass.
Independent review confirms preservation of all 43 other regions and the new
146-source baseline; the pending raw-handoff/scoring status above remains explicit.

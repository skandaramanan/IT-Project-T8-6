# IT-125 close-out: refreshed 216436 integration — 19 October 2026

All three local close-out items are complete: the refreshed raw handoff is
verified, the complete corpus is paired and published locally, and the current
figures/report replace the historical 17 October snapshot. No new model calls,
commits, pushes, PR actions or issue-status updates were made during this close-out.

## 1. Verified fresh Qwen handoff

`data/it124-216436-qwen-handoff.tar.gz` is now a valid 42,509-byte gzip archive,
SHA-256 `ef8f3f082d7ca0ec33bd9d548cd626a24009113c9c5d0fcab5956ce96f4d69a9`.
The earlier 204-byte download contained a WSL command error and supplied no
readings; it was never extracted or used for scoring.

All 153 archive members were checked before extraction: 151 regular files,
two directories, no unsafe paths, links or duplicate destinations. Extraction
used a new `data/it125-closeout-20261019/handoff/` directory. Its 148 readings
comprise all 146 PR #64 coding sources plus excluded p272 and p570. The manifest
matches the calibrated Q6_K / 2 MP / greedy / repeat-penalty 1.05 configuration
and prompt hash `2ef780a239078c7d`. The archive also supplies the rerun log.

An independent check compared every published Qwen field with its own physical
page's raw reading: **9,052 comparisons, zero discrepancies**. The separate
whole-corpus raw/export check also passed. The isolated composite cache at
`data/it125-closeout-20261019/qwen-cache/` points the entire 216436 region to
this fresh handoff and the other 44 regions to the preserved original handoff.
No original cache was overwritten and no model rerun was needed.

The handoff README repeats an earlier claim that page order differs throughout.
Independent visual evidence in the recovery audit instead found the original
card-bearing coordinates retained, with 80 pages appended. Pairing uses the
actual region/PDF/page coordinates; equivalence of the old and new readings was
never inferred from that statement or the shared filename.

## 2. Paired dataset and local publication

The primary input is the immutable
`data/it125-inputs-after216436/results/` snapshot, incorporating merged PRs
#63/#64 and source-verified Gemini corrections. Gemini's structure, handwriting,
notes, associations and human decisions remain authoritative. Each household's
own raw reading supplies all 62 comparison fields. An individual blank or
omitted Gemini field never takes a Qwen replacement.

Final publication: **`results/<region>.jsonl`**, with
**5,375 dwellings / 5,430 coding sources / 10,104 stored cards** across 44
nonempty regions. Front-only 216461 accounts for the 45th region and has no
invented coding records. Only `results/216436.jsonl` changes relative to the
pre-close-out dataset; the other 43 region files are byte-identical. The
manifest now records current input hashes, configuration and handoff provenance.

- All **340,880 stored coding leaves** have numeric confidence.
- All **10,104 cards** have numeric confidence. The former 151 null front/back
  scores in 216436 now use the established zero-evidence card marker.
- **554,451 supplementary handwriting/person/note fields** retain null
  confidence. Their text is accepted as-is; zero card confidence does not claim
  a measured handwriting error rate or define handwriting queue priority.
- All **34 protected field payloads** and their review histories are unchanged.
- **1,106 primary omissions** are recovered through explicit Gemini label aliases;
  accepted omissions stay untouched. Gemini crop identities lacking paired
  calibration remain preserved with zero calibrated confidence.
- All **218 excluded sources** remain excluded. No published coding source is
  lost or duplicated. Existing grouping/identity flags and 460 null household
  identities are preserved rather than silently repaired.
- The sole unavailable Qwen arm remains 216419 /
  `423497_1973-0002-00008-00001.pdf` / p103, explicitly a failed reading.
  Its surviving Gemini fields receive single-arm evidence, never agreement.

The complete scan remains installed under the canonical review path
`data/Wilfred_Prest_Survey_Data/216436/1264179_1973-0002-00025.pdf`, SHA-256
`6d7b64bc0bb82e499ac35a6d32872409572ec484f8670a9368b834ab9c3796f0`.
The old 514-page PDF, original Gemini inputs and pre-pull files remain preserved
in the earlier recovery directories. The active files replaced by this
close-out have an additional backup under
`data/it125-closeout-20261019/before-publication/`.

## 3. Current figures and acceptance

The [current merge report](it125-merge-report.md) and its JSON companion contain
per-region agreement, review eligibility, confidence summaries, configuration,
input hashes and verification evidence. Raw normalized agreement is
**265,167 / 336,660 = 78.76%** of all expected comparison fields. Under D022,
**269,035 / 895,331 = 30.05%** of stored field leaves are eligible to skip
review, or **78.92%** of numeric coding leaves. Human-reviewed leaves are
excluded from automatic eligibility; identity flags may still require review.
These are eligibility measurements, not a corpus accuracy guarantee.

The current calibration was reproduced from the saved 30-card Q6 2MP benchmark:
the summary is byte-identical to `it125-calibration.json`. Qwen remains
1,574/1,860 correct (84.62%). Unbanded primary-arm agreement correctness is
1,486/1,523; 37 agreeing fields were jointly wrong. The banded pairing and
small-sample fallbacks remain documented. This is development-benchmark
calibration, with no held-out accuracy claim or newly enabled bypass policy.

**AC1 and AC2 are met. AC3 is met under the user's clarified scope:** the
regional figures and known C3/S3/R1 counts are reported. Historical sample
counts are **C3 4, S3 10, R1 12**; intersections with this dataset are 4, 3 and
2 physical sources respectively. Full-corpus subtype prevalence remains
unknown. The user excluded unsupported-form processing from the required
close-out; these observations are not presented as a completed subtype census.
Retained known C3 placeholders remain conservatively scored zero.

Review queue filtering, numbers-first ordering and lower handwriting priority
belong to **IT-109 / IT-115**. Front-only records (**IT-133**) and strike handling
(**IT-134**) also remain outside IT-125. The technical merge report is supplied
locally. A separate user-requested [presentation brief](https://linear.app/um-it-project/document/full-corpus-results-presentation-brief-draft-ecb35757656f)
is available under Product in Linear; ticket statuses remain unchanged.

## Post-publication validation fix

The independent review reproduced one test failure after paired publication:
the standalone Gemini additions test used the active paired dataset as its
expected fixture. The earlier 791-test run preceded publication, so it did not
establish that the final checkout's complete suite passed.

The test now starts with the original 127-record Gemini baseline and compares
the real rebuild against the immutable 146-record PR #63 blob
`5b45a21aba1283eb41ceaeff130837234c2c35b0`. A second build must reproduce both
the same output and report bytes. Existing source/correction/raw-cache checks
remain intact, and the active paired publication is explicitly checked unchanged.

The complete **post-publication suite now passes: 807 passed, 13 skipped**.
The focused additions suite also passes all 10 cases. All **92 published
files**, including the separate Qwen exports and manifest, retain their exact
pre-fix hashes. No scoring, dataset, source-cache or model configuration change
was needed. Fix, preservation and independent sign-off evidence is in
`data/it125-validation-fix-20261019/`.

## Verification and reproduction

`data/it125-closeout-20261019/` contains:

- `archive-audit.json`, `input-audit.md`, `composition.json`: handoff/configuration
  safety and raw/export reconciliation.
- `candidate/` and `repeat/`: independently built outputs, all **90 files
  byte-identical**, including 44 region files, 44 pairing audits, summary and
  manifest. `determinism.json` records hashes before and after identical
  close-out provenance metadata was attached.
- `closeout-metadata.json`: the explicit dated region inventory, paths and
  handoff receipt added identically to both algorithm-produced manifests;
  it changes no score or dataset record.
- `schema.log`: all 44 region files validate.
- `independent_audit.py`, `independent-audit.json`, `final-review.md`: independent
  full-corpus preservation, raw-field, state, score, exclusion and bypass checks.
- `pytest.log`: historical **791 passed, 13 skipped**, before final publication.
- `report-tests.log`: **16 report tests passed**, covering stale summaries/evidence
  and coding leaves without an explicit `source` label; these are included in the
  subsequent complete 807-test pass, not additional to it.
- `../it125-validation-fix-20261019/pytest.log`: authoritative final
  **807 passed, 13 skipped**, against the published paired dataset.
- `ruff.log`: repository lint and formatting passed.
- `runtime.json`: the full offline merge took **109.13 seconds** on this machine.
- `publication.json`: every active region file and manifest matches the
  verified candidate, with backups and changed-file inventory.
- `verification.json`: manifest-bound inputs to the report generator.

Use the current commands in the README to rebuild into a new, isolated output.
The final report was generated with:

```sh
uv run python scripts/report_scored_results.py \
  --dataset data/it125-closeout-20261019/candidate \
  --runtime data/it125-closeout-20261019/runtime.json \
  --evidence data/it125-closeout-20261019/verification.json \
  --report-date 2026-10-19 --output docs/runs/it125-merge-report
```

The earlier Git recovery evidence remains in
`data/it125-pull-recovery-20261018/`. It records the fast-forward to `50ad42b`
and preservation of the earlier IT-125 work, subsequently committed as
`1dfbd66` under the user's separate authorization. This close-out adds only
local, uncommitted changes on the correctly labelled IT-125 branch.

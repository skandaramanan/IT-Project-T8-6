# IT-125 candidate merge report — 2026-10-19

This report describes candidate `/Users/skandaramanan/Documents/IT-Project-T8-6/data/it125-closeout-20261019/candidate`: **5,375 dwellings / 5,430 physical coding cards**, with 44 nonempty regions. It does not establish that this candidate is the current published dataset.

Candidate creation date: 2026-10-19. Region names accounted for in the supplied artifacts: 45; full project region inventory supplied. Empty-region declarations: `{"216461": "front-only material; no coding records in either arm"}`.

## Agreement and review eligibility

Raw normalized agreement: **265,167/336,660 = 78.76%** across expected comparison fields; **81.19%** where both arms read a nonblank value. Raw and effective class counts remain separate where evidence is uncalibrated or protected.

Candidate policy: `D021 Gemini primary, D016 normalized Q6 calibration, D018 weakest quarter, D022 clean agreement`. Review-eligible bypass share: **269,035/895,331 = 30.05%** of stored field leaves; 78.92% of numeric leaves. These are policy eligibility counts, not a guarantee that the eventual review queue bypasses those fields. Identity flags can still require review; protected human-reviewed fields are excluded from automatic eligibility.

Confidence summarizes the calibrated evidence for the selected reading. Agreement is not a corpus accuracy guarantee. Blank, omitted, absent and failed readings must remain distinct; Gemini stays primary, including an individual blank or omission. Qwen supplies a value only when the entire primary arm is unavailable.

## Scores, preservation and discrepancies

D018 aggregates each coding card's own paired fields with the weakest-quarter mean. Uncalibrated fronts and backs use card score 0 as a no-evidence marker; supplementary handwriting/person/note field confidences may remain null. Neither marker measures handwriting accuracy.

Stored fields: 895,331; numeric scores: 340,880; null scores: 554,451; invalid scores: 0. Coding-source leaves with numeric scores: 340,880/340,880. Mean numeric field score: 0.9036.

Stored cards: 10,104, by role `{"coding-front": 5430, "survey-back": 20, "survey-front": 4654}`; unscored/invalid cards: 0. Mean numeric card score: 0.3847. These are score summaries, not measured corpus accuracies.

Protected field leaves present: **34**. Audit override counts: `{"gemini_identity_recovery_uncalibrated": 121, "human_review_preserved": 18, "primary_label_alias_recovered": 1106}`. Null household identities: 460; grouping/identity flags: `{"duplicate_dwelling_no": 215, "duplicate_record_id": 351, "fronts_disagree": 196, "identity_reread": 116, "missing_dwelling_no": 238, "missing_record_id": 64, "municipality_mismatch": 5, "out_of_order": 855, "paired_by_position": 451, "persons_unassigned": 43, "unplaced": 978}`. Presence and counts do not independently establish unchanged human payloads; preservation checks belong in the supplied verification evidence.

Excluded-source count declared by this candidate manifest: **218**. Missing/failed secondary arms in this candidate: `[{"page": 103, "pdf": "423497_1973-0002-00008-00001.pdf", "region": "216419", "state": "failed"}]`. The report does not infer zero lost or unclassified archive cards from these observations.

## Clarified scope and secondary counts

Unsupported secondary forms are ignored for the scored extraction scope; any retained placeholders do not gain C1/C2 validation.
Known C3/S3/R1 sample counts are reported honestly; unknown full-corpus prevalence is not an acceptance blocker under the clarified scope.
Handwriting, notes and person text are accepted as-is as supplementary information; no accuracy is inferred from their retention.
Queue implementation belongs to IT-109/IT-115 and is outside IT-125; reported skip shares describe eligibility under the candidate policy.

| Form | Identified in supplied sample | Present in candidate | Present as coding source |
| --- | ---: | ---: | ---: |
| C3 | 4 | 4 | 4 |
| R1 | 12 | 2 | 0 |
| S3 | 10 | 3 | 0 |

## Per-region figures

| Region | Dwellings | Coding cards | Raw agree / fields | Raw agree % | Effective agree % | Skip fields / stored | Skip % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 216412 | 75 | 75 | 3497/4650 | 75.20% | 75.20% | 3506/13588 | 25.80% |
| 216413 | 113 | 116 | 6099/7192 | 84.80% | 84.80% | 6159/17063 | 36.10% |
| 216414 | 130 | 132 | 6798/8184 | 83.06% | 83.06% | 6865/19100 | 35.94% |
| 216415 | 145 | 146 | 7645/9052 | 84.46% | 84.46% | 7766/24314 | 31.94% |
| 216416 | 109 | 109 | 5683/6758 | 84.09% | 84.09% | 5785/18747 | 30.86% |
| 216417 | 84 | 84 | 4380/5208 | 84.10% | 84.10% | 4463/14017 | 31.84% |
| 216418 | 116 | 116 | 5205/7192 | 72.37% | 72.37% | 5316/18789 | 28.29% |
| 216419 | 133 | 133 | 5974/8246 | 72.45% | 72.45% | 6102/23435 | 26.04% |
| 216420 | 243 | 244 | 11024/15128 | 72.87% | 72.86% | 11202/42884 | 26.12% |
| 216421 | 123 | 125 | 6199/7750 | 79.99% | 79.99% | 6264/20785 | 30.14% |
| 216422 | 165 | 166 | 7959/10292 | 77.33% | 77.33% | 8086/27256 | 29.67% |
| 216423 | 117 | 118 | 5468/7316 | 74.74% | 74.66% | 5552/18298 | 30.34% |
| 216424 | 194 | 195 | 9757/12090 | 80.70% | 80.70% | 9899/31170 | 31.76% |
| 216425 | 107 | 107 | 5302/6634 | 79.92% | 79.92% | 5404/16986 | 31.81% |
| 216426 | 93 | 93 | 4602/5766 | 79.81% | 79.81% | 4693/15490 | 30.30% |
| 216427 | 86 | 87 | 4335/5394 | 80.37% | 80.37% | 4401/14477 | 30.40% |
| 216428 | 168 | 170 | 8222/10540 | 78.01% | 78.01% | 8350/30048 | 27.79% |
| 216429 | 30 | 30 | 1554/1860 | 83.55% | 83.55% | 1583/5323 | 29.74% |
| 216431 | 65 | 65 | 3058/4030 | 75.88% | 75.88% | 3106/9592 | 32.38% |
| 216433 | 125 | 125 | 6211/7750 | 80.14% | 80.14% | 6326/19542 | 32.37% |
| 216434 | 109 | 109 | 4775/6758 | 70.66% | 70.66% | 4872/18222 | 26.74% |
| 216435 | 95 | 95 | 4747/5890 | 80.59% | 80.59% | 4839/15793 | 30.64% |
| 216436 | 146 | 146 | 7385/9052 | 81.58% | 81.57% | 7513/25400 | 29.58% |
| 216437 | 179 | 179 | 8419/11098 | 75.86% | 75.86% | 8593/29433 | 29.20% |
| 216438 | 166 | 166 | 8327/10292 | 80.91% | 80.91% | 8463/27858 | 30.38% |
| 216439 | 170 | 170 | 8681/10540 | 82.36% | 82.36% | 8848/26455 | 33.45% |
| 216440 | 143 | 143 | 7011/8866 | 79.08% | 79.04% | 7148/22541 | 31.71% |
| 216441 | 32 | 32 | 1554/1984 | 78.33% | 78.33% | 1581/5952 | 26.56% |
| 216442 | 88 | 88 | 4349/5456 | 79.71% | 79.71% | 4424/14562 | 30.38% |
| 216443 | 107 | 115 | 5763/7130 | 80.83% | 80.83% | 5732/18179 | 31.53% |
| 216444 | 76 | 79 | 3864/4898 | 78.89% | 78.87% | 3903/12029 | 32.45% |
| 216445 | 100 | 101 | 5347/6262 | 85.39% | 85.39% | 5429/16036 | 33.86% |
| 216446 | 88 | 92 | 4641/5704 | 81.36% | 81.36% | 4657/12058 | 38.62% |
| 216447 | 270 | 271 | 12123/16802 | 72.15% | 72.15% | 12373/48193 | 25.67% |
| 216448 | 133 | 135 | 6708/8370 | 80.14% | 80.14% | 6784/21664 | 31.31% |
| 216449 | 233 | 236 | 11914/14632 | 81.42% | 81.42% | 12085/43613 | 27.71% |
| 216450 | 102 | 102 | 5175/6324 | 81.83% | 81.83% | 5269/16423 | 32.08% |
| 216451 | 112 | 114 | 5739/7068 | 81.20% | 81.20% | 5814/19718 | 29.49% |
| 216452 | 162 | 167 | 8444/10354 | 81.55% | 81.55% | 8520/25174 | 33.84% |
| 216453 | 176 | 179 | 9018/11098 | 81.26% | 81.26% | 9136/28708 | 31.82% |
| 216454 | 44 | 44 | 2125/2728 | 77.90% | 77.90% | 2169/6988 | 31.04% |
| 216459 | 54 | 54 | 2771/3348 | 82.77% | 82.77% | 2818/13168 | 21.40% |
| 216460 | 105 | 108 | 5554/6696 | 82.95% | 82.95% | 5586/15995 | 34.92% |
| 216463 | 64 | 69 | 1761/4278 | 41.16% | 39.69% | 1651/10265 | 16.08% |
| 216461 | 0 | 0 | 0/0 | unknown | unknown | 0/0 | unknown |

## Acceptance observations

- **AC1:** `{"coding_confidence_complete": true, "schema_and_preservation": "see supplied verification evidence; not inferred from report generation"}`
- **AC2:** `{"all_stored_cards_numerically_scored": true}`
- **AC3:** `{"full_census_required": false, "known_secondary_counts_reported": true, "regional_agreement_and_review_share_reported": true}`

These observations establish only the counts/completeness checked by this generator. Acceptance and publication require the relevant candidate-specific verification evidence; generating this report does not run the test suite, schema validator, independent review or determinism checks.

## Provenance and supplied verification

Manifest `/Users/skandaramanan/Documents/IT-Project-T8-6/data/it125-closeout-20261019/candidate/merge-manifest.json` SHA-256 `38436446bb4ca45c98052a1aa37780cd05d2e88edf8c93f8cc1a8f74f9e36dcc`; summary SHA-256 `ebe0f734c085e1b3c0fb4565836aa4a65768b52cb50424391c4e76e715c856e0`. Candidate paths: `{"candidate": "/Users/skandaramanan/Documents/IT-Project-T8-6/data/it125-closeout-20261019/candidate", "gemini_cache": "data/runs", "primary": "data/it125-inputs-after216436/results", "publication": "results", "qwen_cache": "data/it125-closeout-20261019/qwen-cache", "secondary": "results/qwen2.5-vl-server-2000000px"}`. Input/configuration, exclusion/calibration hashes and candidate file hashes are retained in the JSON report's provenance object.

Supplied merge-runtime evidence:

```json
{
  "elapsed_seconds": 109.1322903749533,
  "operation": "full offline merge with validation; no model calls"
}
```

Supplied verification evidence (attributed to the supplying checks; not rerun by this report):

```json
{
  "calibration": {
    "benchmark_cards": 30,
    "evidence": "data/it125-closeout-20261019/calibration.json",
    "fields": 1860,
    "status": "passed",
    "summary_byte_identical_to_tracked_artifact": true
  },
  "candidate_manifest_sha256": "38436446bb4ca45c98052a1aa37780cd05d2e88edf8c93f8cc1a8f74f9e36dcc",
  "determinism": {
    "byte_identical_files": 90,
    "evidence": "data/it125-closeout-20261019/determinism.json",
    "status": "passed"
  },
  "full_suite": {
    "evidence": "data/it125-validation-fix-20261019/pytest.log",
    "failed": 0,
    "passed": 807,
    "phase": "after final dataset publication",
    "skipped": 13,
    "status": "passed"
  },
  "handoff": {
    "evidence": "data/it125-closeout-20261019/input-audit.md",
    "export_field_checks": 9052,
    "mismatches": 0,
    "published_readings": 146,
    "raw_readings": 148,
    "status": "passed"
  },
  "independent_review": {
    "all_scoped_acceptance_criteria_satisfied": true,
    "blocking_findings": 0,
    "evidence": "data/it125-validation-fix-20261019/final-review.md",
    "status": "passed",
    "validation_gap_resolved": true
  },
  "lint_format": {
    "evidence": "data/it125-validation-fix-20261019/ruff.log",
    "status": "passed"
  },
  "pre_publication_suite": {
    "evidence": "data/it125-closeout-20261019/pytest.log",
    "passed": 791,
    "phase": "before final paired dataset publication; historical evidence",
    "skipped": 13,
    "status": "passed"
  },
  "preservation": {
    "evidence": "data/it125-closeout-20261019/independent-audit.json",
    "independent_audit_errors": 0,
    "lost_published_coding_sources": 0,
    "protected_payloads_unchanged": 34,
    "status": "passed"
  },
  "previous_independent_review": {
    "all_scoped_acceptance_criteria_satisfied": true,
    "blocking_findings": 0,
    "evidence": "data/it125-closeout-20261019/final-review.md",
    "phase": "initial data review; later fixture finding recorded separately",
    "status": "passed"
  },
  "publication": {
    "candidate_files_match": true,
    "changed_region_files": [
      "216436.jsonl"
    ],
    "evidence": "data/it125-closeout-20261019/publication.json",
    "path": "results",
    "status": "passed"
  },
  "report_tests": {
    "evidence": "data/it125-closeout-20261019/report-tests.log",
    "included_in_full_suite": true,
    "passed": 16,
    "status": "passed"
  },
  "schema": {
    "dwellings": 5375,
    "evidence": "data/it125-closeout-20261019/schema.log",
    "region_files": 44,
    "status": "passed"
  },
  "scope": {
    "handwriting": "Supplementary; accepted as-is. Numbers-first/lower handwriting queue priority belongs to IT-109/IT-115.",
    "remaining_upstream": "216461 front-only IT-133; strike handling IT-134; review queue/UI IT-109/IT-115. These are outside IT-125.",
    "secondary_forms": "Ignored under user clarification; known sample C3=4/S3=10/R1=12 reported, full-corpus prevalence unknown. No fabricated census."
  },
  "validation_fix": {
    "builds_per_replay": 2,
    "expected_commit": "5b45a21aba1283eb41ceaeff130837234c2c35b0",
    "fixture_stage": "standalone Gemini PR63",
    "focused_tests_passed": 10,
    "preservation_evidence": "data/it125-validation-fix-20261019/after.json",
    "previous_failure_evidence": "data/it125-independent-review-20261019/pytest.log",
    "published_files_unchanged": 92,
    "status": "passed",
    "test_sha256": "efc52c973ad61b3224d8265b68e1a113c92ccc0503d2e78bf3d27295d65917cb"
  }
}
```

## Reproduce this report

```sh
uv run python scripts/report_scored_results.py --dataset "/Users/skandaramanan/Documents/IT-Project-T8-6/data/it125-closeout-20261019/candidate" --output <report-prefix>
```

Optional --runtime, --evidence, --secondary-evidence and --report-date attach candidate-specific measurements, verification evidence, hash-matched sample sources and a chosen report date. Report generation reads the candidate and writes only the requested report prefix.

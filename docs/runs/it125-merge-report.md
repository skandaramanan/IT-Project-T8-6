> **18 October update:** Main now includes PRs #63/#64. The current local dataset has **5,375 dwellings / 5,430 coding sources**. Region 216436 contains the new 146-record Gemini baseline with single-extractor scores; its machine scores do not clear review while the refreshed Qwen raw handoff is pending; source-verified corrections remain protected. The other 43 paired regions are unchanged. The figures below are the **17 October snapshot**, not current whole-corpus agreement figures. See [the integration status](it125-216436-integration.md). The complete 594-page scan is installed locally; the old 514-page scan and previous scored dataset are backed up.

# IT-125 local merge report — 17 October 2026

Built **5,356 dwellings / 5,411 physical coding cards**, covering 44 nonempty region files. Region 216461 is front-only and explicitly has zero coding records. All 45 regions are accounted for.

Final local publication: `results/<region>.jsonl`. Qwen inputs remain in `results/qwen2.5-vl-server-2000000px/`; original Gemini files are preserved at `data/it125-originals/results/`. Candidate and per-source pairing evidence: `data/it125-repeat/` (with `pairing/`, `summary.json`, `merge-manifest.json`). No model calls or remote writes were used.

## Agreement and review policy

Raw normalized agreement is **264,289/335,482 = 78.78%** across all 62 fields per card, or **81.21%** where both read nonblank values. Raw classes are separate from effective scored classes: unsupported C3 fields and preserved Gemini-only identity recoveries receive no paired calibration evidence.

Under D022's current clean-agreement policy, **268,146/891,553 = 30.08%** of stored field leaves are eligible to skip review; **78.94%** of numeric coding leaves. These denominators include the schema's municipality aliases and exclude review history snapshots. They differ from 62 × card counts because shared dwelling fields are stored once, while municipality is duplicated. Identity flags can still force queue entries. Human-reviewed leaves are excluded from automatic-skip counts.

The 0.98 cutoff follows the recalibrated D016 agree constant. This is the existing interim policy on the development benchmark, not a 99% corpus accuracy guarantee. 37/1,523 agreeing unbanded benchmark fields were wrong. There is no held-out evaluation or human ceiling. Both-blank has zero Q6 benchmark support and remains in review via status; banded low-sample fallbacks do not establish a new bypass policy.

## Scores and preservation

Every stored coding field has numeric confidence (339,683 leaves); 551,870 handwriting/person/note leaves remain null under D028. Every stored card has numeric confidence (10,045 cards). The mean numeric field score is 0.9036; mean stored-card score is 0.3857, including zero evidence fronts/backs. These are score summaries, not measured full-corpus accuracies.

Each coding card uses its own 62 raw Gemini/Qwen fields and D018's weakest-quarter mean. Gemini remains primary even for individual blanks and omissions. Omitted selected fields score zero; absence never counts as agreement. Uncalibrated fronts/backs receive card score 0.0 as a no-evidence triage marker; their fields remain null. No handwriting accuracy is inferred.

All 13 legacy corrected field payloads remain unchanged, including their confidence and provenance. The merge also preserves audit histories and accepted omissions in regression tests. It recovers 1,106 previously omitted Gemini fields from explicit aliases (1,081 populated, 25 explicit blanks), never Qwen substitutes. Separately recovered Gemini identity values are preserved and scored zero because their crop prompt has no paired calibration. The inputs' 460 null household IDs and all grouping/association flags remain unchanged.

All 216 excluded sources remain excluded. Region 216414 p194 is present. The only missing Qwen arm is 216419 / `423497_1973-0002-00008-00001.pdf` / p103 (failed token-cap loop); all 62 surviving Gemini fields remain in the output with single-arm evidence. The one unused nonexcluded Qwen cache, 216434 p2, is blank and adds no source.

Measured local full offline merge runtime: **89.40 seconds**, including input/output validation and staged writes. No model calls. Runtime evidence is an observation of this machine, not an extraction throughput claim.

Missed-card accounting: zero published Gemini coding sources lost; one failed/missing Qwen reading (p103). The number of genuinely missed or unclassified archive cards remains unknown because no new full typed scan audit was performed. The truncated 216436 scan and upstream discovery gaps prevent a claim of zero missing archive cards.

## Secondary forms and acceptance limitation

The historical structure sample identifies **C3: 4, S3: 10, R1: 12** among 843 successfully analyzed pages (880 sampled; 44 readable units). Published-source intersections are **C3: 4, S3: 3, R1: 2**. These are observed counts and corpus lower bounds, not a full prevalence census. The exact sources and evidence references are in `it125-known-secondary-sources.json`. All four known C3 sources remain present, with coding/card scores zero and review required. Known S3/R1 stored cards have zero evidence scores and uncalibrated handwriting.

No complete subtype inventory exists in the repository or supplied handoff; the generic segmenter does not distinguish these forms, and no additional inventory was available. The full-corpus C3/S3/R1 totals therefore remain **unknown**. A typed page audit is needed to close that part of AC3. Existing truncated 216436 material, front-only 216461, unplaced cards and absent strike detection remain upstream limitations. No broad model rerun is justified by this merge.

## Acceptance status

- **AC1 met** for the retained corpus: schema valid, resolved values and complete coding scores; null only for documented uncalibrated fields.
- **AC2 met:** every stored card is numerically scored, with conservative no-evidence handling.
- **AC3 partially met:** per-region agreement and skip-review shares are complete; exact known sample/output subtype counts are reported, but full-corpus prevalence is unavailable. The requested Linear report is supplied locally here under the no-Linear-updates instruction.

## Per-region figures

Agreement is raw nonblank agreement / all expected card fields. Effective agreement excludes uncalibrated identity/C3 evidence. Skip share is D022-eligible leaves / all stored field leaves.

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
| 216436 | 127 | 127 | 6507/7874 | 82.64% | 82.63% | 6624/21622 | 30.64% |
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
| 216461 | 0 | 0 | 0/0 | n/a | n/a | 0/0 | n/a |

## Validation

The completed local full suite passed **775 tests**, with **13 skipped** and no calibration xfails. Ruff lint/format and `git diff --check` passed. `survey validate-results` passed all 44 region files. An independent reviewer separately validated all 5,356 schema envelopes, every raw arm field, card aggregation, protected payloads, exclusions, source uniqueness and review bypass: zero unsafe skips. Same-input runs produced byte-identical 44 region files, 44 pairing files and summary; final published files match the verified candidate. The final manifest also pins calibration and secondary-type evidence hashes.

Detailed local evidence: `data/it125-final-tests.log`, `data/it125-validation.log`, `data/it125-context/final-review.md`, `determinism.json`, `publication.json` and `runtime.json`. The supplied raw caches and original Gemini/Qwen files remain preserved. No commit, push, merge, PR comment or Linear update was made.

## Reproduce

```bash
uv run python benchmark/calibrate_confidence.py --qwen-raw data/it124-review-20261017/handoff/data/benchmark/results/q6-2mp-rp1.05/raw --output data/it125-calibration/calibration.json --summary-output docs/runs/it125-calibration.json
uv run python scripts/merge_scored_results.py --primary data/it125-originals/results --output data/it125-new-candidate
uv run survey validate-results data/it125-new-candidate
uv run python scripts/report_scored_results.py --dataset data/it125-new-candidate --output data/it125-new-report
```

The output directory must be new/empty and disjoint from all inputs. The merge never calls either model, `--fresh`, or the IT-124 patch helper. The two accepted maintenance defects remain separate from this implementation.

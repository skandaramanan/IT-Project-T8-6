# IT-123 review resolution — 15 October 2026

Local rebuild of the Gemini Flash-Lite baseline using the existing cached
readings. No model client was constructed and no API requests were made.
Configuration remains D028: unbanded, no struck detection.

## Verified outcome

- 45 regions accounted for; 44 nonempty JSONL files validate at schema 0.6.0.
- 5,356 dwelling records and 5,411 household coding-card sources retained.
- Every original coding-card source and every protected field payload survived.
- Positional pairs reduced from 1,228 to 451. Every remaining positional pair
  has usable numbers within one edit; lettered dwelling numbers agree exactly.
- Unplaced records increased from 201 to 978. Rejected front associations no
  longer lend an address/person grid to their coding card. Their original
  front readings remain cached for later matching; coding values are retained.
- Every nonnull ID matches that household's own municipality and identity fields.
  One former ID (`216446`, PDF page 35, `21-0038-01`) is now null and flagged.
  The newly eligible cached reread on page 105 changes `43(a)` to `38`, creating
  a competing claim to that ID; both remain null for review. The scan contains
  crossed-out/annotated numbering, so this reread is not verified ground truth.
  All other published household IDs are unchanged.
- Repeating the offline rebuild produced byte-identical output in all 44 files.
- Published front-data coverage deliberately decreased: records with addresses
  fell from 5,133 to 4,356, and attached person rows from 19,908 to 16,926.
  Rejected links are insufficiently supported, not all proven incorrect. Raw
  front readings remain cached for manual matching. House, head, counts, coding
  and household-number payloads compare identically by physical coding card.

## Review comments

1. **Empty region:** `216461` has no coding records. Its empty JSONL was removed,
   and extraction no longer publishes zero-record files. This is represented by
   the zero count below, rather than an invalid dataset placeholder. Dataset
   validation now runs in PR CI as well as on `review-data` pushes.
2. **Position pairing:** both usable numbers must be within one insertion,
   deletion or substitution. Different lettered dwellings and unusable numbers
   do not pair by position. Other cards remain `unplaced`, not discarded.
3. **Front recovery:** a populated front cannot be retyped solely because a
   coding prompt returns a plausible ID. Persons and meaningful handwritten
   fields prevent automatic conversion. Inspection of all 72 previously
   recovered pages affected by this guard showed actual coding-card layouts;
   the front prompt had populated spurious front/person fields. Their explicit
   classifications are in `it123-verified-coding.json`. This is classification
   evidence, not a claim that every transcribed digit has been checked.
4. **Municipality:** each household retains its own field even when its ID is
   null. The first household's shared alias remains for compatibility. No dummy
   municipality or global uncertainty blocker is needed. A unique explicit
   identity correction wins a machine collision; conflicting corrections stay
   null and flagged. Protected identity values are applied before association,
   so stricter pairing does not detach a corrected front. Caches stay unchanged.
5. **Partial identity reread:** a blank crop part has no opinion about an already
   valid first part. Explicit contradictions and incomplete identities still fail.
6. **Malformed review identities:** identity fields are already accept-only in
   the review API. Invalid legacy/manual identity edits still refuse the region
   rewrite without changing its existing file; silently keeping an inconsistent
   ID is unsafe. This refusal and the FRONT_FLAGS replacement have regression tests.
7. **Storage:** D025 now points to D029's existing same-repository `review-data`
   decision. The extraction baseline can be reviewed on `main`; sharing reviewed
   corrections uses the dedicated checkout/branch. Raw responses/scans remain
   outside Git. This change does not choose a new LFS or external hosting scheme.

## Reproduce without model access

From the repository root, using the existing `data/runs/<region>/` caches:

```bash
uv run python scripts/rebuild_cached_results.py --output data/it123-rebuild/results
uv run survey validate-results data/it123-rebuild/results
uv run python scripts/rebuild_cached_results.py --previous data/it123-rebuild/results --output data/it123-rebuild-repeat/results
```

The replay uses the published coding-card inventory, cached front readings and
explicit scan classifications. It does not treat abandoned probes from older
segmentation runs as additional coding cards. Missing primary coding caches,
regrouped reviewed households and lost protected payloads stop the rebuild.

For a normal extraction rerun of a verified region, supply the same decisions:

```bash
uv run survey extract data/Wilfred_Prest_Survey_Data/216414 --verified-coding docs/runs/it123-verified-coding.json
```

That command can make requests for missing readings; the offline replay above
cannot. Original files are backed up locally in
`data/backups/results-before-it123-review/`.

## Outstanding corpus gaps

- `216436`: the archive PDF is truncated; outputs cover the 514 intact pages.
  A complete replacement is still needed from the client.
- `216461`: front-only material, no coding records; 62 front responses are in
  this local cache. Inclusion of that 1943 material remains a client question.
- Faint missed fronts and unplaced cards still need source matching/review.
  IT-123 should remain open for those corpus gaps.

## Per-region counts

| Region | Records | Households |
| --- | ---: | ---: |
| 216412 | 75 | 75 |
| 216413 | 113 | 116 |
| 216414 | 130 | 132 |
| 216415 | 145 | 146 |
| 216416 | 109 | 109 |
| 216417 | 84 | 84 |
| 216418 | 116 | 116 |
| 216419 | 133 | 133 |
| 216420 | 243 | 244 |
| 216421 | 123 | 125 |
| 216422 | 165 | 166 |
| 216423 | 117 | 118 |
| 216424 | 194 | 195 |
| 216425 | 107 | 107 |
| 216426 | 93 | 93 |
| 216427 | 86 | 87 |
| 216428 | 168 | 170 |
| 216429 | 30 | 30 |
| 216431 | 65 | 65 |
| 216433 | 125 | 125 |
| 216434 | 109 | 109 |
| 216435 | 95 | 95 |
| 216436 | 127 | 127 |
| 216437 | 179 | 179 |
| 216438 | 166 | 166 |
| 216439 | 170 | 170 |
| 216440 | 143 | 143 |
| 216441 | 32 | 32 |
| 216442 | 88 | 88 |
| 216443 | 107 | 115 |
| 216444 | 76 | 79 |
| 216445 | 100 | 101 |
| 216446 | 88 | 92 |
| 216447 | 270 | 271 |
| 216448 | 133 | 135 |
| 216449 | 233 | 236 |
| 216450 | 102 | 102 |
| 216451 | 112 | 114 |
| 216452 | 162 | 167 |
| 216453 | 176 | 179 |
| 216454 | 44 | 44 |
| 216459 | 54 | 54 |
| 216460 | 105 | 108 |
| 216461 | 0 | 0 |
| 216463 | 64 | 69 |

## Final verification

- `uv run pytest -q`: 666 passed, 13 skipped.
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- `git diff --check`: passed.
- `uv run survey validate-results results`: all 44 nonempty region files passed.
- Offline rerun: all 44 output files byte-identical.
- Physical-card inventory and original protected-payload comparisons passed.

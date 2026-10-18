# 216436 replacement: Gemini additions

Processed locally on `skandar/it-123-216436-gemini-additions`, based on committed main
`5569133` (merged IT-124). The original checkout contains ongoing IT-125 work;
none of its changes were copied into this worktree or modified. This is the
standalone Gemini arm, pending Qwen and the IT-125 merge.

## Inputs and provenance

The client replacement `1973-0002-00025-00001.pdf` has 594 pages. The previous
repaired scan has 514. Comparison found the original card-bearing pages in the
same positions. Visual inspection of all pages 515–594 found 19 populated
coding cards, 20 survey fronts and their backs. Page 570 is a blank crossed-out
numeric form and is excluded from requests and output.

A separate copy of the replacement is stored in this worktree at
`data/Wilfred_Prest_Survey_Data/216436/1264179_1973-0002-00025.pdf`.
The established PDF name is retained as the canonical source name for the
region's existing page references; the download name and replacement SHA-256
are recorded in `216436-gemini-additions.json`. The original checkout's PDF
was not replaced. When adopting these additions elsewhere, the replacement
must also be installed under that canonical name so pages above 514 resolve.

## Extraction and result

- D028 configuration: `gemini-3.5-flash-lite`, default media resolution,
  unbanded and no struck detection. Single-card requests; no batch prompts.
- 19 coding readings, 20 fronts, 20 back-note readings, and one identity crop.
- `results/216436.jsonl`: **127 -> 146 records / physical coding sources**.
- All 127 original JSONL lines are preserved exactly. Other region files and
  Qwen results are unchanged.
- Source inspection resolved all nine previously unmatched fronts and their
  notes. All 20 fronts and 20 backs are now attached to the 19 coding records;
  no positional associations were forced and no general association rule changed.
- `216436-source-corrections.json` records 19 page-specific corrections:
  11 front dwelling numbers and eight coding fields. Crossed-out old numbers
  and top-right archive references caused most errors. Every correction records
  the original cached value, the replacement, and the scan evidence.
- All 19 new coding identities were checked against the scans. This also
  corrected p539's municipality, p547/p555's cancelled municipality/dwelling
  pairs, and p573's misread dwelling number. P551 is now `14-0209-01`;
  its crop read the cancelled legacy values and remains unchanged in the cache.
- P585's `Type of Family` is visibly **1**. Its original reply used
  `Type_of_Family: null`; this was both a wrong blank and a label variant.
  The output now carries 1 as a source-verified correction.
- Fronts p527 and p529 continue one dwelling, `14-0191-01`, and share coding
  p531. Both person grids and both backs survive. There are 12 resident
  columns plus a separately written "Another expected" column; all 13
  transcribed columns are retained, without equating grid length to residents.
- One `fronts_disagree` flag remains on those continuation sheets: the cached
  municipality text differs (`Armadale` versus `Truedale(21)`, from the older
  annotation). The first sheet supplies the published municipality text.
  This flag remains visible instead of suppressing the discrepancy.
- Corrected output fields carry `origin: corrected` and `original_value`.
  Raw caches stay byte-identical; no new model requests were needed for this
  investigation. Fields retain the existing confidence; teammate review remains
  pending. IT-125 must preserve corrections.
- Confidence is the existing standalone Gemini confidence, not IT-125's
  calibrated paired score. These readings must not be treated as dual agreement.

## Verification

- Every expected new coding page is present exactly once; p570 is absent.
- All 44 nonempty region files pass `survey validate-results results`.
- Offline rebuilding produces byte-identical output.
- 129 focused tests pass: 120 association/notes/pipeline tests and nine new
  correction/continuation/regression checks. The new tests cover immutable raw
  readings, unexpected-cache refusal, page/field restrictions, duplicate
  decisions, original-value metadata, municipality aliases, continuation grids
  and backs, complete source coverage, and deterministic rebuilding. A published
  correction/review payload cannot be overwritten by the rebuild.
- Ruff passes. No production extraction/association implementation was changed.
- Checksums of 300 tracked/nonignored files in the original checkout match
  the pre-run snapshot, including every ongoing IT-125 change.
- Evidence: `data/216436-additions/verification.json`, worker/build logs,
  `gap-review/schema-validation.log`, and `gap-review/verification-tests.log`.

## Reproduce in this worktree

The default command is an offline cache replay. It cannot construct a model
client or make API requests:

```bash
uv run python scripts/extract_216436_additions.py
uv run survey validate-results results
```

For initial extraction, workers 0/1 use separate existing keys from the given
credential file, read only these page lists, and resume from their own caches:

```bash
uv run python scripts/extract_216436_additions.py --worker 0 --credentials /path/to/.env
uv run python scripts/extract_216436_additions.py --worker 1 --credentials /path/to/.env
uv run python scripts/extract_216436_additions.py --identity --credentials /path/to/.env
```

The offline build applies the source-correction manifest to copies of the
cached fields before association. It refuses a different PDF hash or a changed
machine value, then verifies the exact 20 inspected front-to-coding links.
It marks the selected published fields corrected while preserving machine
values and immutable raw caches.

The script refuses other branches, shared data/results paths or imports from
another checkout. It always merges against the pinned original Gemini
baseline and refuses changes to any existing record. Caches live under this
worktree's `data/runs/216436/`, with canonical PDF names and absolute PDF pages.
The local handoff archive contains those raw responses, the incremental
records, orphan readings and verification metadata; it contains no credentials
or scan images. Raw responses and scans remain outside Git.

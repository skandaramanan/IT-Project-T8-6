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
- Page 551's full-card identity and crop disagree on municipality (14 vs 21).
  Its ID remains null; the raw readings and review flag are preserved.
- Eight new coding records remain unplaced by the existing association rules.
  Nine fronts and their notes could not be attached safely. All their raw
  readings are retained; structured orphan payloads are under
  `data/216436-additions/unattached-fronts.json` and `unattached-notes.json`.
  No positional association was forced to increase coverage.
- Page 585 returned `Type_of_Family` instead of `Type of Family`. Its canonical
  field stays explicitly omitted for review; no value was guessed.
- Confidence is the existing standalone Gemini confidence, not IT-125's
  calibrated paired score. These readings must not be treated as dual agreement.

## Verification

- Every expected new coding page is present exactly once; p570 is absent.
- All 44 nonempty region files pass `survey validate-results results`.
- Offline rebuilding produces byte-identical output.
- 120 association, notes and pipeline tests pass; the extraction script passes
  Ruff. No production extraction/association implementation was changed.
- Checksums of 300 tracked/nonignored files in the original checkout match
  the pre-run snapshot, including every ongoing IT-125 change.
- Evidence: `data/216436-additions/verification.json`, worker/build logs,
  `schema-validation.log`, and `verification-tests.log`.

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

The script refuses other branches, shared data/results paths or imports from
another checkout. It always merges against the pinned original Gemini
baseline and refuses changes to any existing record. Caches live under this
worktree's `data/runs/216436/`, with canonical PDF names and absolute PDF pages.
The local handoff archive contains those raw responses, the incremental
records, orphan readings and verification metadata; it contains no credentials
or scan images. Raw responses and scans remain outside Git.

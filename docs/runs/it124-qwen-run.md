# IT-124 Qwen run: what was read, removed and skipped — 17 October 2026

The second extractor's corpus run (D019 addendum): Qwen2.5-VL-7B Q6_K at 2 MP
through LM Studio, `survey extract --model qwen2.5-vl-server`, over all 45
folders. It reads coding cards only. Fronts, backs and identity re-reads are
Gemini's. Output is in `results/qwen2.5-vl-server-2000000px/` (D025), with the
run's configuration in `extractor.json` beside it.

## Totals

- **5,421 dwelling records**, every file valid at schema 0.6.0. 216461 has
  none, as in the Gemini run, so it has no file.
- **5,283 coding cards shared with the Gemini run** outside 216436, out of
  its 5,284, paired by PDF and page (D026). No card is in this run alone.
  216436 was read again from a complete scan (below); Gemini's is being rerun
  on the same file.
- The one Gemini card with no Qwen reading is 216419,
  `423497_1973-0002-00008-00001.pdf` p103. The model repeats `0` until the
  2,048-token cap on every read, so the reply is refused rather than cached
  as a partial reading. It is the run's only failed card.
- **218 sources excluded**: pages the review checked against the scans and
  found are not coding cards (below).
- 692 pages skipped: 688 not recognised as a card, 3 with no decodable image,
  and 1 blank coding card. Each is listed in `it124-qwen-skipped-pages.json`.
- 163 records flagged `unplaced` (the card fits no dwelling), 129
  `missing_record_id` (the ID is blank or malformed) and 349
  `duplicate_record_id` (another household has the same ID). All are written,
  not dropped (IT-123). The ID still agrees with Gemini's on 3,541 of the 5,283
  shared cards, so IT-125 pairs the runs by card, not by `record_id`.

## Excluded sources

`it124-excluded-sources.json` lists 218 pages, in the same region/PDF/page
format as `it123-verified-coding.json`. The first run published a record for
216 of them, and none is a numeric coding card. Two independent visual audits in the
PR review checked every one. For example, 216461 p9 is a letter that was
published as `10-0001-01`, and 216414 p101 is interview notes published as
`15-0001-01`. Gemini read the same pages and returned nothing usable. Qwen
filled in a plausible household. The 216436 rerun added two more, checked
against the scan: p272 is a blank card back (`05-0001-01`) and p570 a blank,
voided coding card (`05-1234567890-1234567890`).

`survey extract` reads the list by default (`--excluded-sources` overrides
it), for either model:

- An excluded page is never read, nor offered to front recovery.
- A record built from one earlier is removed from the previous results before
  they are merged, so a rerun cannot bring it back.
- If removing it would split a dwelling that also holds a kept card, or would
  drop reviewed fields, the run refuses and writes nothing.

A page can't be both verified coding and excluded.

## Misspelt labels

The prompt asks for each field by the label printed on the card, and Gemini
copies it. Qwen sometimes writes it another way:

| Qwen wrote | Card and schema | Readings |
| -- | -- | -- |
| `Washhouse` | `Washouse` | all 5,626 |
| `Pre-war Occupation` | `Pre-War Occupation` | 1,524 |
| `Number 5 - 10` | `Number 5-10` | 834 |
| `Children of H. or wife` with `Living`/`Dead`/`Total` nested, or `Children of H. or Wife: Living` and similar | `Children of H. or wife: Living` etc. | 430 |
| `Main Source of Head's Unearned Income`, `Subsidiary Source of Head's Income`, labels with a trailing `:` | the card's abbreviations | 43 |
| `Number of Households` | `Number of Household` | 4 |

Until now each of these fields was exported as `omitted`. Every exported
`washouse`, for one. `json_extraction.FIELD_ALIASES` now reads these exact
spellings under the schema's label, for fresh replies and cached ones alike.
The value keeps its own confidence band and strike. A label the reply also gave
under its own name, even blank, keeps that value, and two spellings that
disagree are left omitted. One reply gave the children's total as the string
`"Total: 0"`, so it stays omitted.

## How the results were corrected

The committed records were corrected in place from the cached readings, by
`scripts/patch_qwen_results.py`, without segmenting the scans again:

1. The 216 excluded records were removed.
2. 9,113 omitted fields were filled from the cached reply's misspelt labels.
   No field that had a value was touched.
3. Every record was scored again, and each region's identities settled again,
   with the pipeline's own functions. That brings 4 households their number,
   and leaves 129 missing and 349 duplicate IDs, down from 133 and 356.

A second run of the script changes nothing. A pipeline rerun of a folder,
`--cached-only` below, builds the same corrections from the same cache.

216414 p194 is a genuine coding card that the segmenter takes for a front.
Gemini recovered it by reading the front with the coding prompt, which this
run never does. It is now in `it123-verified-coding.json`, was read with the
Q6_K model on 17 October (`01-0320-01`, the same ID as Gemini's), and was
added to `216414.jsonl`. It was built without its PDF's other pages, so it is
flagged `unplaced`. Gemini pairs it with the front after it (`out_of_order`).

## Configuration and cache

| Setting | Value |
| -- | -- |
| Model id | `qwen/qwen2.5-vl-7b` (LM Studio) |
| Weights | `Qwen2.5-VL-7B-Instruct-Q6_K.gguf`, with `mmproj-model-f16.gguf` |
| Image | 2 MP (`QWEN_MAX_PIXELS=2000000`) |
| Decoding | greedy, repeat penalty 1.05, 2,048-token cap |
| Prompt | `EXTRACTION_PROMPT`, sha256 `2ef780a239078c7d…`, unchanged in every commit since 1 October |

The same LM Studio id served Q4_K_M during the benchmark sweep, so the id
alone does not say which weights made a reading. The extractor now asks the
server: LM Studio's `quantization`, or the GGUF file llama.cpp loaded.
`QWEN_SERVER_WEIGHTS` must agree with it, and is required where the server
can't say. Readings cache under the weights, in
`data/runs/<region>/qwen2.5-vl-server-2000000px/qwen-qwen2.5-vl-7b-q6_k/`, so
other weights read every card again instead of replaying these. Each cache
folder and the results folder hold `extractor.json`, the full configuration. A
run with a different one refuses to write there.

**The caches were not mixed.** All 5,626 readings were written between
02:00 on 12 October and 01:00 on 16 October. That is after the last Q4_K_M
benchmark (00:55 on 12 October), and the run script and dashboard only started
or reloaded the model after checking that `llama-server` had
`Qwen2.5-VL-7B-Instruct-Q6_K.gguf` loaded. The replies themselves agree:

- 29 of the 30 benchmark cards were also read in the corpus run. 21 of those
  readings are byte-identical to the Q6_K 2 MP benchmark reply, including
  three written on 16 October.
- The other 8 differ by 1 to 3 fields. The Q6_K benchmark run with 3 parallel
  slots differs from the single-slot run by the same amount.
- Against Q4_K_M at 2 MP, only 1 corpus reply is identical (216439 p35,
  which Q6_K at 2 MP also reads the same). The rest differ by 1 to 13 fields.

## By folder

`Records`, `Unreadable ID`, `Duplicate ID` and `Unplaced` count dwellings; the
other columns count pages. Blank coding-card backs are expected and not
counted.

| Folder | Records | Pages skipped | Excluded | Unreadable ID | Duplicate ID | Unplaced | Failed |
| -- | -- | -- | -- | -- | -- | -- | -- |
| 216412 | 75 | 0 | 1 | 0 | 4 | 1 | 0 |
| 216413 | 116 | 0 | 2 | 0 | 7 | 3 | 0 |
| 216414 | 132 | 1 | 1 | 2 | 17 | 9 | 0 |
| 216415 | 146 | 0 | 16 | 2 | 12 | 16 | 0 |
| 216416 | 109 | 23 | 5 | 4 | 6 | 3 | 0 |
| 216417 | 84 | 31 | 2 | 0 | 2 | 2 | 0 |
| 216418 | 116 | 32 | 7 | 0 | 9 | 1 | 0 |
| 216419 | 132 | 23 | 2 | 2 | 2 | 3 | 1 |
| 216420 | 244 | 40 | 2 | 7 | 12 | 7 | 0 |
| 216421 | 125 | 0 | 1 | 1 | 17 | 3 | 0 |
| 216422 | 166 | 1 | 0 | 1 | 8 | 2 | 0 |
| 216423 | 118 | 0 | 0 | 19 | 8 | 6 | 0 |
| 216424 | 195 | 18 | 5 | 3 | 11 | 1 | 0 |
| 216425 | 107 | 54 | 4 | 0 | 19 | 0 | 0 |
| 216426 | 93 | 34 | 3 | 0 | 6 | 1 | 0 |
| 216427 | 87 | 43 | 26 | 0 | 6 | 0 | 0 |
| 216428 | 170 | 12 | 2 | 1 | 7 | 1 | 0 |
| 216429 | 30 | 5 | 0 | 0 | 0 | 0 | 0 |
| 216431 | 65 | 9 | 25 | 0 | 0 | 7 | 0 |
| 216433 | 125 | 17 | 6 | 1 | 8 | 2 | 0 |
| 216434 | 109 | 15 | 2 | 0 | 8 | 0 | 0 |
| 216435 | 95 | 19 | 1 | 2 | 2 | 0 | 0 |
| 216436 | 145 | 12 | 2 | 1 | 4 | 2 | 0 |
| 216437 | 179 | 15 | 5 | 1 | 8 | 5 | 0 |
| 216438 | 166 | 11 | 3 | 2 | 17 | 2 | 0 |
| 216439 | 170 | 66 | 2 | 1 | 8 | 2 | 0 |
| 216440 | 143 | 27 | 1 | 34 | 2 | 22 | 0 |
| 216441 | 32 | 0 | 1 | 0 | 0 | 0 | 0 |
| 216442 | 88 | 14 | 7 | 0 | 0 | 3 | 0 |
| 216443 | 115 | 2 | 4 | 3 | 2 | 8 | 0 |
| 216444 | 79 | 2 | 0 | 1 | 4 | 0 | 0 |
| 216445 | 101 | 15 | 3 | 3 | 2 | 3 | 0 |
| 216446 | 92 | 2 | 1 | 17 | 12 | 9 | 0 |
| 216447 | 271 | 0 | 1 | 1 | 11 | 3 | 0 |
| 216448 | 135 | 13 | 5 | 4 | 12 | 5 | 0 |
| 216449 | 236 | 85 | 17 | 1 | 36 | 2 | 0 |
| 216450 | 102 | 6 | 5 | 2 | 4 | 1 | 0 |
| 216451 | 114 | 12 | 3 | 0 | 4 | 1 | 0 |
| 216452 | 167 | 5 | 2 | 4 | 21 | 1 | 0 |
| 216453 | 179 | 11 | 3 | 7 | 14 | 4 | 0 |
| 216454 | 44 | 6 | 4 | 0 | 6 | 3 | 0 |
| 216459 | 54 | 3 | 15 | 1 | 0 | 6 | 0 |
| 216460 | 107 | 5 | 2 | 1 | 9 | 6 | 0 |
| 216461 | 0 | 2 | 6 | 0 | 0 | 0 | 0 |
| 216463 | 63 | 1 | 13 | 0 | 2 | 7 | 0 |
| **Total** | **5,421** | **692** | **218** | **129** | **349** | **163** | **1** |

## Pages with no image

`pypdf` needs the `jbig2dec` binary to decode these pages, and it was not
installed on the machine that ran them. They are listed as `no_image`:

- 216416, `423466_1973-0002-00005-00001.pdf` p158 and p358
- 216417, `423473_1973-0002-00006-00001.pdf` p90

Installing `jbig2dec` and rerunning those two folders reads them.

## Damaged scan

The Drive copy of 216436's PDF was damaged: no xref table or trailer, and its
index, rebuilt locally, found 514 pages. A complete copy (17 October) has 594,
a different scan at a lower resolution (2644×1642 against 3861×2400) and in a
different page order, so none of the old page numbers carry over. It replaced
the local file under the same name, `1264179_1973-0002-00025.pdf`, and 216436
was read again from scratch: 147 cards, 145 records once p272 and p570 were
excluded, none failed. The old scan, its cached readings and its 127 records
are kept outside Git, in `data/damaged/it124-216436-514-page-scan/`. The Gemini
run's 216436 still refers to the old scan's pages until its rerun on the new
file lands, and IT-125 can't pair that folder before then.

## How the run went

1. A full run, then 22 cut-off readings from a slow period (GPU memory
   spilling into system RAM) were moved aside and read again.
2. Rebased on IT-123 and replayed from the cache. 98 cards were read fresh:
   earlier failures, and pages IT-123's verified coding now reads as coding
   cards. 13 of them failed and were read again on a second pass: 12 hit
   LM Studio's per-request context (about 3,500 tokens until it was raised to
   8,192) and 1 hit a model reload.
3. A scan of every cached reply for JSON that does not parse found one cut-off
   reading (216419 p103). It was moved aside and its folder rerun. The card
   failed again, and the record built from the cut-off reading was removed.
4. Review (17 October): the 216 excluded records removed, the misspelt labels
   read, p194 read, and the cache moved under its weights, as above.
5. 216436 read again from the complete scan, and its two invented records
   excluded (`data/bench-logs/rerun_216436.log`).

## For IT-125

`data/handoff/it124-qwen-handoff.tar.gz` holds everything this run read from,
outside Git, for the shared Drive:

- the corpus caches (`data/runs/<region>/qwen2.5-vl-server-2000000px/`, with
  their `extractor.json`);
- the 30-card benchmark replies for every configuration tried
  (`data/benchmark/results/q4-*`, `q6-*`, `q8-*`; the run's is
  `q6-2mp-rp1.05`);
- the run scripts and logs (`data/bench-logs/`, `data/qwen_dashboard.py`).

Recalibration stays in IT-125. Reading the misspelt labels moves fields
between D016's agreement classes (D016 addendum C), so neither D016's
constants nor the benchmark figures in D019's addendum describe the pairing
these results give. Calibrated scores, and any review bypass that relies on
them (D022's `agree`), need IT-125's comparison on this pairing first.

## Reproducing

Run from the repository root. With the readings cached, no model server is
needed:

```bash
QWEN_SERVER_MODEL=qwen/qwen2.5-vl-7b QWEN_SERVER_WEIGHTS=Q6_K QWEN_MAX_PIXELS=2000000 \
  uv run survey extract data/Wilfred_Prest_Survey_Data/<folder>/ --model qwen2.5-vl-server --cached-only
uv run survey validate-results results/qwen2.5-vl-server-2000000px
```

A card with no cached reading fails under `--cached-only`. Without it, the
same command reads that card from the server, which must have the same
weights loaded.

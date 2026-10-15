# IT-124 Qwen run: skipped and failed pages — 16 October 2026

The second extractor's corpus run (D019 addendum): Qwen2.5-VL-7B Q6_K at 2 MP
through LM Studio, `survey extract --model qwen2.5-vl-server`, over all 45
folders. It reads coding cards only. Fronts, backs and identity re-reads are
Gemini's. Output is in `results/qwen2.5-vl-server-2000000px/` (D025).

## Totals

- 5,626 coding-card readings cached, and 5,617 dwelling records written. Every
  file validates at schema 0.6.0.
- 696 pages skipped: 692 not recognised as a card, 3 with no decodable image,
  and 1 blank coding card. Each is listed in `it124-qwen-skipped-pages.json`.
- 1 card failed and has no record. 216419, `423497_1973-0002-00008-00001.pdf`
  p103: on every read, the model repeats `0` until the 2,048-token cap. That
  reply used to be cached as a partial reading. It now raises, so the card
  fails and nothing is cached.
- 187 records flagged `unplaced` (the card fits no dwelling) and 187 flagged
  `missing_record_id` (the ID is blank or malformed). Both are written, not
  dropped (IT-123).

## By folder

`Unreadable ID` and `Unplaced` count dwellings; the other columns count pages.
Blank coding-card backs are expected and not counted.

| Folder | Records | Pages skipped | Unreadable ID | Unplaced | Failed |
| -- | -- | -- | -- | -- | -- |
| 216412 | 76 | 0 | 0 | 1 | 0 |
| 216413 | 118 | 0 | 0 | 3 | 0 |
| 216414 | 132 | 1 | 2 | 8 | 0 |
| 216415 | 162 | 0 | 2 | 16 | 0 |
| 216416 | 114 | 23 | 5 | 4 | 0 |
| 216417 | 86 | 31 | 0 | 2 | 0 |
| 216418 | 123 | 32 | 4 | 2 | 0 |
| 216419 | 134 | 23 | 3 | 3 | 1 |
| 216420 | 246 | 40 | 8 | 9 | 0 |
| 216421 | 126 | 0 | 1 | 4 | 0 |
| 216422 | 166 | 1 | 1 | 2 | 0 |
| 216423 | 118 | 0 | 19 | 6 | 0 |
| 216424 | 200 | 18 | 4 | 1 | 0 |
| 216425 | 111 | 54 | 3 | 1 | 0 |
| 216426 | 96 | 34 | 0 | 1 | 0 |
| 216427 | 113 | 43 | 9 | 0 | 0 |
| 216428 | 172 | 12 | 2 | 1 | 0 |
| 216429 | 30 | 5 | 0 | 0 | 0 |
| 216431 | 90 | 9 | 11 | 7 | 0 |
| 216433 | 131 | 17 | 2 | 4 | 0 |
| 216434 | 111 | 15 | 6 | 0 | 0 |
| 216435 | 96 | 19 | 3 | 0 | 0 |
| 216436 | 127 | 16 | 1 | 3 | 0 |
| 216437 | 184 | 15 | 4 | 8 | 0 |
| 216438 | 169 | 11 | 3 | 2 | 0 |
| 216439 | 172 | 66 | 1 | 2 | 0 |
| 216440 | 144 | 27 | 34 | 22 | 0 |
| 216441 | 33 | 0 | 1 | 1 | 0 |
| 216442 | 95 | 14 | 0 | 3 | 0 |
| 216443 | 119 | 2 | 3 | 8 | 0 |
| 216444 | 79 | 2 | 1 | 0 | 0 |
| 216445 | 104 | 15 | 3 | 3 | 0 |
| 216446 | 93 | 2 | 18 | 9 | 0 |
| 216447 | 272 | 0 | 1 | 3 | 0 |
| 216448 | 140 | 13 | 5 | 7 | 0 |
| 216449 | 253 | 85 | 5 | 2 | 0 |
| 216450 | 107 | 6 | 3 | 3 | 0 |
| 216451 | 117 | 12 | 1 | 1 | 0 |
| 216452 | 169 | 5 | 4 | 1 | 0 |
| 216453 | 182 | 11 | 7 | 5 | 0 |
| 216454 | 48 | 6 | 3 | 5 | 0 |
| 216459 | 69 | 3 | 2 | 6 | 0 |
| 216460 | 109 | 5 | 1 | 6 | 0 |
| 216461 | 5 | 2 | 1 | 2 | 0 |
| 216463 | 76 | 1 | 0 | 10 | 0 |
| **Total** | **5,617** | **696** | **187** | **187** | **1** |

## Pages with no image

`pypdf` needs the `jbig2dec` binary to decode these pages, and it was not
installed on the machine that ran them. They are listed as `no_image`:

- 216416, `423466_1973-0002-00005-00001.pdf` p158 and p358
- 216417, `423473_1973-0002-00006-00001.pdf` p90

Installing `jbig2dec` and rerunning those two folders reads them.

## Damaged scan

The Drive copy of 216436's PDF is damaged: it has no xref table or trailer.
All 514 pages were intact, so the index was rebuilt locally by appending only,
and no existing byte changed. The Drive file itself still needs replacing.

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
   failed again, and the record built from the cut-off reading was removed from
   `216419.jsonl`. The merge had kept it as a previous-run record.

## Reproducing

Run from the repository root, with the readings cached in
`data/runs/<region>/qwen2.5-vl-server-2000000px/`:

```bash
QWEN_MAX_PIXELS=2000000 uv run survey extract data/Wilfred_Prest_Survey_Data/<folder>/ --model qwen2.5-vl-server
uv run survey validate-results results/qwen2.5-vl-server-2000000px
```

Move the folder's old results file aside first. Otherwise the merge keeps
records for cards that failed this time.

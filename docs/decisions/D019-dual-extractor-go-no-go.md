# D019 — Dual extraction: go/no-go

**Status:** Accepted, provisional — pending NFR-03 calibration against source images
**Date:** 2026-09-16
**Decided by:** Skanda Ramanan (Design Lead)
**Linear issue:** IT-100, closing IT-84

The 1980s transcription does not calibrate this. It covers the handwritten
front, not the coding card (D017).

## The question

IT-98 wired up a second extractor. IT-99 (D016) turned the two arms' agreement
into a per-field confidence score. Neither answered whether this is worth
running over all ~6,500 cards.

## Decision

**No. Don't run two extractors on every card.**

The local arm alone needs 256 GPU-hours on free Colab — about 21 twelve-hour
sessions, with no guarantee you get them. The hosted side is cheap by
comparison (~$19 of API across the corpus), so the GPU is what rules it out,
not the API bill.

**Ship `gemini-3.5-flash-lite` and use its own self-reported confidence band.**
One pass, ~2.6 days. Keep dual extraction for spot-checking samples, which is
where it earns its keep.

### Why the less accurate model

`gemini-3.5-flash` at batch=10 scores 95.8%. Flash-Lite scores 91.3%. Flash is
better and we are not picking it.

The reason is the band. Flash says `high` to 98% of its fields, so its band
tells you nothing. Flash-Lite's band actually separates: 91.7% correct on
`high`, 9.1% on `low`. FR-10 is a Must and it needs a score that means
something. A confidence number that never varies is not a confidence number.

So the trade is 4.5 points of accuracy for a usable review signal. Revisit it
if the signal starts coming from somewhere else.

One caveat on process: choosing between Gemini variants is really a D012
revision, not this note's call, and IT-84 puts model selection out of scope.
Worth flagging that D012 only ever said "Gemini" — it predates anyone measuring
flash against flash-lite, so nothing has formally chosen between them. D016 §1
assumes flash-lite citing the findings doc, and the findings doc cites D012.
Someone should close that loop properly.

## What the numbers say

30 C1/C2 cards, 62 fields each, 1,860 comparisons, scored against the
hand-typed sheet.

### Agreement between the two arms

| Class | Fields | Share | Confidence |
| -- | -- | -- | -- |
| agree | 1,343 | 72.2% | 0.97 |
| disagree | 398 | 21.4% | 0.75 |
| one blank | 118 | 6.3% | 0.74 |
| both blank | 1 | 0.1% | 0.97 |
| no second opinion | 0 | 0% | — |

They agree on 77.1% of fields where both actually read a code.

### Correlated error (AC2)

Of the 1,343 fields where both arms agreed, **40 were wrong. That is 3.0%.**

Taking only the agreed fields gives 97.0% precision over 72.2% of the data, and
catches 131 of Flash-Lite's 171 errors (76.6%). The other 40 errors ship
looking confident, which is 2.15% of all fields.

### Three figures that were wrong

Everything on the findings page was measured on the `gemini-3.5-flash` pairing.
Flash does not ship. D016 §1 recalibrated the confidence constants to flash-lite
back on 09/09, but the summary figures were never updated with them.

| | Findings page (flash) | Flash-lite |
| -- | -- | -- |
| Correlated error | 1.0% | **3.0%** |
| Precision on agreed fields | 99.0% | **97.0%** |
| Errors caught | 88.8% | **76.6%** |
| Split: gemini vs qwen | 8:1 | **5.4:1** |

Both sets reproduce exactly from saved output, so this is stale documentation
rather than a disputed measurement. The practical upshot is that the dual check
misses about one error in four, not one in nine. The findings page has been
corrected.

### Accuracy (AC3)

| Engine | Requests / 30 cards | Coded-field accuracy |
| -- | -- | -- |
| flash, batch=10 | 3 | 95.8% |
| flash, single-card | 30 | 93.7% |
| flash-lite, single-card | 30 | 91.3% |
| flash-lite, banded | 30 | 88.8% |
| qwen2.5-vl (4-bit, T4) | 30 | 74.8% |

Flash-Lite is fine as a first pass. It is 2.4 points behind Flash, not the 23
the OCR spike reported — that was a *batched* Flash-Lite run, where it stops
reading after about three cards and makes the rest up. Flash batches cleanly,
Flash-Lite does not.

### Cost and speed (AC4)

Measured 16/09, 30 cards, 5 workers.

| | |
| -- | -- |
| Latency | 7.4s median per request |
| Cost | $0.00293 per card |
| Whole corpus | ~$19 at list price, $0 on the free tier |
| Local arm | ~142s per card, so 256 GPU-hours |

Median rather than mean, because requests run concurrently and four cards hit
the 30s rate-limit backoff. The mean makes a card look like it takes 4.3s when
it really takes 7.4s.

`run_benchmark.py` was already working both numbers out and then throwing them
away at the summary. It now prints them.

### Repeat runs differ by about a point

Re-running the same model over the same 30 cards scored 90.0% against the
original 91.3%. Only 10 of the 30 cards scored identically.

The whole 1.3-point gap comes from two cards falling apart (`216417_p0271`,
58 correct fields down to 40, and `216419_p0055`, 49 down to 40). Take those
two out and the repeat lands within 0.2 points.

Two things follow. Gaps of a point or two between configurations are noise, so
Flash-Lite's 2.4-point deficit is real but narrow. And the failure mode to
design against is a single card collapsing, not gradual drift — which is
exactly what card-level confidence catches (IT-85, D018).

## Can we just re-read the bad fields? (AC6)

This is the obvious cheap fallback, and it is worth being careful about,
because the tempting version of the sum is wrong.

Flash is capped at 20 requests/day/key across 5 keys, so 100 requests a day.
**You pay per request, and every request has to carry a card image.** There are
no bounding boxes in this pipeline — the schema is built from prompts, not
layout — so you cannot send a field without sending its card. Counting flagged
*fields* and packing them 50 to a request is not a real saving, because those
50 fields drag 50 images along with them.

And the flagged fields are spread thin rather than clustered:

```
low fields per card: 6, 6, 3, 3, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, ...
```

16 of 30 cards have at least one `low` field. 27 of 30 have at least one `low`
or `medium`. So the real unit is cards, and it is most of them:

| Escalate | Cards | Requests at batch 10 | Days |
| -- | -- | -- | -- |
| `low` only | 53%, ~3,470 | 347 | **3.5** |
| `low` + `medium` | 90%, ~5,850 | 585 | 5.8 |
| everything, no triage | 100%, 6,500 | 650 | 6.5 |

So escalating the worst fields costs 3.5 days on top of the 2.6-day first pass.
It fixes 30 of the 221 errors on the benchmark, about 14%, and those fields are
91% wrong so the re-read is nearly all gain.

**It is worth doing but it is optional, not part of the core recommendation.**
Six days total is close enough to the 6.5 days it would take to run Flash over
everything that the choice should be made on the band, not on the calendar.

Two caveats. Batch=10 is the largest Flash batch anyone has measured, and it
was measured for extraction, not for re-reads. And a re-read prompt does not
exist yet.

**The local → hosted version does not work at all.** The idea is to call Gemini
only where the local model is unsure, but qwen cannot tell you when it is
unsure — asked the same way as Gemini it returned `high` on all 1,104 values
(D016 Addendum A). Its only uncertainty signal is disagreeing with the hosted
arm, which means making the call you were trying to avoid. On top of that the
local pass is 256 GPU-hours before any of this starts.

## Alternatives

**Run full dual extraction anyway.** It catches 76.6% of errors against 13.6%
for the `low` band alone, so this is a real loss, not a wash. Rejected on the
256 GPU-hours, and only on that. If a decent GPU appears, this is the better
mechanism.

**Ship Flash at batch=10.** More accurate (95.8%) and 6.5 days. Rejected
because its band is flat, so it cannot route review. See "Why the less accurate
model".

**Drop the band and keep Flash-Lite's 2.5 accuracy points.** Rejected. The band
is the confidence mechanism. Without it there is nothing to satisfy FR-10 with
short of the dual path we just declined.

## Consequences

- Dual extraction becomes a sampling tool. D016's constants stay valid for that
  and for IT-85 and IT-86.
- IT-86 has its evidence. Across 398 splits, gemini is right 75.1% and qwen
  13.8%, so gemini wins disagreements about 5.4 to 1. On 11.1% of splits
  neither is right, so a split still means a human should look. (75.1% is
  D016's `disagree` constant, re-derived independently.)
- D012 needs amending to name a variant. Not this note's call.
- `run_benchmark.py` reports cost and latency now.
- Nothing in `src/` changes.

## Revisit if

- **Paid Gemini capacity is approved (NFR-10).** The 100/day cap is what shapes
  all of this.
- **A real GPU turns up.** 256 GPU-hours is a property of the free T4, not of
  the design.
- **Flash gets a band that separates.** Then it wins on accuracy and the trade
  above disappears.
- **Review volume shows 13.6% error-catching is too low a floor.**

## How far to trust this

- 30 cards, all of them used to derive the numbers. No held-out split exists
  (Test Plan §5.1).
- Ground truth is single-keyed and unverified (§5.2). Some of the 40 correlated
  errors could be transcription mistakes, which would make the figure better.
- The repeat run above says ±1.3 points on the headline, so treat small gaps as
  noise.
- ~6,500 cards is the roadmap's estimate. Every extrapolation scales with it.
- The escalation days are arithmetic on measured band shares, not an observed
  run.

## Reproducing

```
# cached, no API calls
uv run python spike/dual_extract.py --models gemini-3.5-flash-lite qwen2.5-vl --no-fetch
uv run python spike/run_benchmark.py --model gemini --rescore

# live, 30 requests. --results-root keeps the calibrated output untouched
uv run python spike/run_benchmark.py --model gemini --workers 5 --results-root <scratch>
```

Working for every confidence constant and the band tables: [D016](D016-agreement-to-confidence.md).

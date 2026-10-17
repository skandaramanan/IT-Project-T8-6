# D019 — Dual extraction: go/no-go

**Status:** Accepted as a conditional go — route pending follow-ups with the
subject coordinator and the client. Figures provisional pending NFR-03
calibration against source images.
**Date:** 2026-09-16 (amended 2026-10-16 by IT-124: the route taken, see the
addendum)
**Decided by:** Skanda Ramanan (Design Lead)
**Linear issue:** IT-100, closing IT-84

The 1980s transcription does not calibrate this. It covers the handwritten
front, not the coding card (D017).

## The question

IT-98 wired up a second extractor. IT-99 (D016) turned the two arms' agreement
into a per-field confidence score. Neither answered whether this is worth
running over all ~6,500 cards.

## Decision

**Conditional go. Run both extractors over every card, on whichever of three
compute routes clears first.**

The signal is worth having. With both arms and Flash-Lite's band combined
(D016's full formula), 83% of Flash-Lite's errors get flagged, against 38.5% for
the band on its own. The only thing against it was compute: qwen needs about
256 T4-hours for the corpus, and free Colab can't reliably supply that. The
hosted arm is cheap (~$19 of API across the corpus).

Gemini Flash-Lite stays the primary arm and reads every card either way, about
2.6 days. The question is where the second arm runs:

| Route | Condition | Why this one | Cost |
| -- | -- | -- | -- |
| **1. Spartan** (UniMelb HPC) | Subject coordinator sponsors access | Free A100/H100s, and the scans stay inside the university | Free. Probably days, unmeasured |
| **2. OpenRouter** (hosted Qwen2.5-VL) | Client approves the spend and sending scans to another provider | No GPU to manage at all | ~$7 for the corpus, estimated not measured |
| **3. Kaggle** | None. This is the default | Free, no card, no quota request. The T4 is the same GPU D016 was calibrated on | Free. ~30 GPU-h/week each, so ~2 weeks across 5 people |

Take the first route that clears. If neither follow-up comes back in time for
the Cycle 4 full-scale run, go with Kaggle.

**Before the full run, on whichever route:** run the 30 benchmark cards there
first. That times it and checks the confidence constants still hold.
`test_constants_still_match_the_benchmark` fails if they move by more than 0.03.

- Spartan uses a different GPU. With the same 4-bit setup and image cap, the
  constants should hold, but check them anyway.
- OpenRouter serves a different model (72B, not 4-bit 7B), so the constants
  **will** need recalibrating on those 30 cards. That costs a few cents.
- Kaggle on the T4 accelerator should reproduce the calibrated setup exactly.

Each Kaggle account belongs to one person. Kaggle allows one account per
person, so five people means five accounts and no more. Split the corpus into
five fixed chunks so no card gets read twice or skipped. It does mean uploading
the scans to Kaggle as a private dataset, so mention that in the same client
email.

**If all three fall through:** fall back to Flash-Lite plus its band alone, and
use dual extraction only to spot-check samples.

### Why the less accurate model

`gemini-3.5-flash` at batch=10 scores 95.8%. Flash-Lite scores 91.3%. Flash is
better and we are not picking it.

The reason is the band. Flash says `high` to 98% of its fields, so its band
tells you nothing. Flash-Lite's band actually separates: 91.7% correct on
`high`, 9.1% on `low`. FR-10 is a Must and it needs a score that means
something. A confidence number that never varies is not a confidence number.

So the trade is 4.5 points of accuracy for a usable review signal.

This gets closer once dual extraction runs, because agreement adds a signal of
its own. Paired with qwen, Flash at batch=10 ships 14 unflagged errors against
Flash-Lite's 37 (D016 Addendum B), but takes 6.5 days a pass instead of 2.6.
Whoever revises D012 should weigh that.

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

### Four figures that were wrong

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

**With dual extraction going ahead, this is only a fallback** for the case
where all three compute routes fall through. Even then, six days total is close
enough to the 6.5 days it would take to run Flash over everything that the
choice should be made on the band, not on the calendar.

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

**No-go: Flash-Lite and its band only, dual for spot checks.** The first draft
of this note recommended this, turning dual down on free-Colab compute alone.
It's now the fallback. It catches far less (38.5% of errors with `low` and
`medium` flagged, against 83% with both arms), and the compute objection has
three possible answers.

**Azure for Students.** Rejected. Student subscriptions are capped at 3 vCPUs
and can't create GPU VMs without upgrading to pay-as-you-go.

**Google Cloud $300 trial.** Not chosen. GPUs are blocked during the trial, so
each person would have to upgrade to paid billing with a card and then request
GPU quota. Kaggle gets the same result with none of that.

**SageMaker Studio Lab, Modal, Lightning AI.** Not chosen. Studio Lab (8 GPU-h
a day, 4-hour sessions) would work but needs a lot of babysitting. Modal means
rewriting the notebook as code. Lightning's free tier is ~22 T4-hours a month,
too slow.

**Ship Flash at batch=10.** More accurate (95.8%) and 6.5 days. Not adopted
here because its band is flat. Now that agreement supplies a second signal,
it's a live option for the D012 revision. See "Why the less accurate model".

**Drop the band and keep Flash-Lite's 2.5 accuracy points.** Rejected. The band
is still part of D016's formula, and the fallback needs it.

## Consequences

- Two follow-ups gate the route: the subject coordinator (Spartan access) and
  the client (OpenRouter spend and data). Kaggle needs neither.
- The full-scale run in Cycle 4 runs both arms. D016's constants carry over on
  Kaggle, get re-checked on Spartan, and get recalibrated on OpenRouter.
  IT-85 and IT-86 build on them either way.
- IT-86 has its evidence. Across 398 splits, gemini is right 75.1% and qwen
  13.8%, so gemini wins disagreements about 5.4 to 1. On 11.1% of splits
  neither is right, so a split still means a human should look. (75.1% is
  D016's `disagree` constant, re-derived independently.)
- D012 needs amending to name a variant. Not this note's call.
- `run_benchmark.py` reports cost and latency now.
- Nothing in `backend/survey/extraction/` changes.

## Revisit if

- **Paid Gemini capacity is approved (NFR-10).** The 100/day cap is what shapes
  all of this.
- **The 30-card test run on the chosen route is much slower than expected**, or
  the constants move past tolerance and recalibration doesn't settle them.
- **All three routes fall through.** Then it's the Flash-Lite-and-band fallback.
- **Flash gets a band that separates.** Then it wins on accuracy and the trade
  above disappears.

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
- None of the three compute routes has been timed. Kaggle's quota (~30 GPU-h a
  week), Spartan's eligibility and OpenRouter's ~$7 all come from published
  pages and a token estimate, checked 16/09/2026. Free tiers change, and the 30-card
  test run is what confirms them.

## Reproducing

```
# cached, no API calls
uv run python benchmark/dual_extract.py --models gemini-3.5-flash-lite qwen2.5-vl --no-fetch
uv run python benchmark/run_benchmark.py --model gemini --rescore

# live, 30 requests. --results-root keeps the calibrated output untouched
uv run python benchmark/run_benchmark.py --model gemini --workers 5 --results-root <scratch>
```

Working for every confidence constant and the band tables: [D016](D016-agreement-to-confidence.md).

## Addendum: the route taken (IT-124, 2026-10-16)

**None of the three.** The second arm ran on a team member's own machine, an
AMD Radeon RX 9070 XT (16 GB), through LM Studio's llama.cpp server. It went
through `survey extract --model qwen2.5-vl-server`
(`backend/survey/extraction/qwen_server.py`). `qwen.py` could not run there,
because bitsandbytes needs CUDA. Spartan and OpenRouter were never cleared,
and the Kaggle split was not needed once one machine could do the whole corpus.

**Configuration**, chosen on the 30 benchmark cards before the full run:

| Setting | Value |
| -- | -- |
| Weights | Qwen2.5-VL-7B-Instruct, Q6_K GGUF, with the f16 vision projector |
| Image | 2 MP (`QWEN_MAX_PIXELS=2000000`), resized client-side to multiples of 28 |
| Decoding | greedy (temperature 0, top-k 1), repeat penalty 1.05, the model's own default |
| Prompt | the plain extraction prompt; no struck detection (8 of 28 labelled strikes found, 7 false flags) |
| Server | `--gpu max`, 3 parallel slots, 24,576 tokens of context (8,192 a request) |

Every sampler setting is sent with each request. Left unset, LM Studio's
presets apply instead, and they scored 68.2%.

**AC1: time and agreement on the 30 cards.** Coded-field accuracy against the
hand-typed sheet:

| Setup | Accuracy | Time per card |
| -- | -- | -- |
| `qwen2.5-vl`, bitsandbytes 4-bit on a T4 (D016's calibration) | 75.0% | ~142 s |
| Q4_K_M, 1 MP / 2 MP | 76.9% / 81.8% | |
| Q6_K, 1 MP | 78.6% | 11.8–12.7 s |
| **Q6_K, 2 MP (the run)** | **84.1%** | 15.8 s alone, 12.6 s with 3 slots |
| Q8_0, 2 MP | 84.2% | spilled into system RAM mid-run |

Q6_K at 2 MP against Q6_K at 1 MP is +5.5 points (95% interval +2.8 to +8.1).
Against Q4_K_M at 2 MP it is +2.3 (+1.1 to +3.6). Q8_0 adds nothing (+0.1).
3 MP and 4 MP scored about the same as 2 MP but spilled out of VRAM.

D016's classes, re-derived the way `test_constants_still_match_the_benchmark`
does it (Flash-Lite primary, 1,860 fields). **Scored before the misspelt
labels were read** (D016 addendum C): every Qwen reply's `Washhouse`, among
others, counted as blank. Reading them moves fields between classes, so these
figures describe the pre-alias pairing only and do not validate the one the
pipeline now builds.

| Class | Constant | T4 4-bit: n, measured | Q6_K 2 MP: n, measured |
| -- | -- | -- | -- |
| `agree` | 0.97 | 1,343, 97.0% | **1,487, 97.6%** |
| `disagree` | 0.75 | 395, 75.7% | **285, 63.9%** |
| `one_blank` | 0.74 | 121, 73.6% | **88, 64.8%** |
| `both_blank` | 0.97 | 1, — | 0, — |

- **`agree` holds, and covers more.** 1,487 fields agree instead of 1,343, and
  35 of them are wrong instead of 40. Flash-Lite errors caught (any class
  but `agree`) go from 129 of 169 to 134 of 169: 79.3% against 76.3%.
- **`disagree` and `one_blank` sit about 0.1 under their constants.** A
  better second arm disagrees less often, and when it does, it is right more
  often. That leaves Flash-Lite right less often, so the constants overstate
  these two classes, and the test's 0.03 tolerance would fail on this pairing.
- **Not recalibrated here.** IT-124 only flags a disagreement (out of scope:
  "re-calibrating D016's constants"). `model_id` stays `qwen2.5-vl` so the
  pipeline can look the tables up, not because they are known to hold. IT-125
  recalibrates on the normalised Q6_K pairing. Calibrated scores, and any
  review bypass that relies on them (D022's `agree`), need that comparison
  first: these figures are not it.

**The run.** All 45 folders: 5,403 dwelling records in
`results/qwen2.5-vl-server-2000000px/` (D025), covering 5,410 of the Gemini
run's 5,411 coding cards. 216 pages the first run published as households are
not coding cards and were removed (`docs/runs/it124-excluded-sources.json`).
Survey fronts, backs and identity re-reads are Gemini's alone. Removed,
skipped and failed pages, and the evidence that every reading came from the
Q6_K weights, are in `docs/runs/it124-qwen-run.md`.

**Reproducing.** The benchmark readings are in `data/benchmark/results/`
(`q6-2mp-rp1.05` and the other configurations). The run's readings are cached
in `data/runs/<region>/qwen2.5-vl-server-2000000px/qwen-qwen2.5-vl-7b-q6_k/`,
and both are in the IT-125 handoff archive (`data/handoff/`).

```
QWEN_MAX_PIXELS=2000000 uv run python benchmark/run_benchmark.py --model qwen2.5-vl-server
QWEN_MAX_PIXELS=2000000 uv run survey extract <scan folder> --model qwen2.5-vl-server
```

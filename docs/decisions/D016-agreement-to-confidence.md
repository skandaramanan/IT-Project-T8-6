# D016 — Agreement to confidence: the formula and its constants

**Status:** Accepted
**Date:** 2026-09-09 (recalibrated to flash-lite same day — see §1)
**Decided by:** Skanda Ramanan (Design Lead)
**Linear issue:** IT-99

## Context

FR-10 wants a numeric confidence score on every extracted field, and no
benchmarked engine produces one. IT-98 manufactures the evidence instead: two
independent extractors read every card, and their agreement stands in for a
signal no single engine gives. What IT-98 does not do is turn that agreement
into a number — it emits one of five agreement classes per field
(`spike/dual_extract.py`) and stops there by design, leaving the arithmetic to
this issue.

D007 already committed the shape this has to fill: `confidence` is
`["number", "null"]`, 0–1, on every field object. `src/extraction/base.py`
independently confirms it — `ExtractionResult.confidence` is
`dict[str, float] | None`. Both predate this decision and both say the same
thing: a float, not a category.

## Decision

**The rule, stated once:** a field's confidence is the measured probability
that the primary arm's reading is correct, given the agreement class the field
fell into, refined by the primary arm's self-reported band when it gave one.
One rule for all 62 fields — the same constant applies regardless of which
field it is (IT-99 AC3).

The constants were measured 2026-09-09 by pairing `gemini-3.5-flash-lite`
against `qwen2.5-vl` (30 cards, 1,860 field comparisons) against the
hand-typed benchmark sheet, and are checked against it on every test run —
`test_constants_still_match_the_benchmark` in `tests/test_confidence.py`
re-derives them and fails if they drift by more than 0.03.

| Class | n | Measured | Constant | Status |
| -- | -- | -- | -- | -- |
| `agree` | 1,343 | 97.0% | **0.97** | measured |
| `disagree` | 398 | 75.1% | **0.75** | measured |
| `one_blank` | 118 | 73.7% | **0.74** | measured |
| `both_blank` | 1 | — | **0.97** | reasoned |
| `no_second_opinion` | 0 | — | *per surviving arm* | reasoned |

### 1. Calibrated to `gemini-3.5-flash-lite`, not `gemini-3.5-flash`

**This supersedes the constants this document originally shipped with, on the
same day.** The first version measured `agree`/`disagree`/`one_blank` on a
`gemini-3.5-flash` × `qwen2.5-vl` pairing, because that was the pairing IT-98
happened to produce. But flash does not ship: the findings doc's own go/no-go
puts `gemini-3.5-flash-lite` into production (2.6-day corpus pass against
flash's 65), so a formula priced on flash was pricing confidence for a model
nobody runs.

Pairing flash-lite against qwen directly instead:

| Class | flash (superseded) | flash-lite (current) | Δ |
| -- | -- | -- | -- |
| `agree` | 99.0% | 97.0% | −2.0 |
| `disagree` | 79.1% | 75.1% | −4.0 |
| `one_blank` | 85.1% | 73.7% | **−11.4** |

`one_blank` moved the most, and moved past `disagree`: on flash it was the
stronger evidence (85.1% > 79.1%), on flash-lite the two are a near-tie with
`disagree` fractionally ahead (75.1% vs 73.7%). `test_agreement_scores_
higher_than_disagreement` no longer asserts that ordering — it asserted an
artefact of which model happened to get measured, not a property IT-99 AC2
actually requires (AC2 only asks that agreement scores high and disagreement
scores materially lower than agreement, not that the two disagreement-adjacent
classes rank a particular way against each other).

`one_blank` still earns its keep as a separate class: once band is folded in
(§6), `one_blank`'s and `disagree`'s numbers diverge sharply again —
`one_blank`/low (13.6%) is the single worst cell in the whole table, well
below `disagree`/low's fallback. The flat constants converging does not mean
the class distinction stopped mattering; it means the class distinction alone
stopped being enough, which is exactly what §6 addresses.

### 2. `no_second_opinion` varies by which arm survived, not one constant

A hosted-path failure (IT-98 AC3) leaves exactly one reading. What that one
reading is worth depends on which model produced it — a lone `gemini-3.5-flash`
reading is not worth the same as a lone `qwen2.5-vl` reading. A single constant
here would either understate the stronger arm or flatter the weaker one, so the
value is the surviving arm's own standalone accuracy, harness-scored in the
findings doc:

| Arm | Coded-field accuracy | Constant |
| -- | -- | -- |
| `gemini-3.5-flash` | 93.7% | 0.94 |
| `gemini-3.5-flash-lite` | 91.3% | 0.91 |
| `qwen2.5-vl` | 74.8% | 0.75 |
| unrecognised arm | — | falls back to the weakest (0.75) |
| neither arm read the card | no evidence at all | 0.0 |

This table is untouched by §1's recalibration — it was already keyed per arm,
including flash-lite, before this document's first version shipped. This is
still one uniform rule (AC3) — it is keyed on which arm answered, never on
which field. An unrecognised model name falls back to the *weakest* measured
arm rather than the strongest: understating a field's confidence routes it to
review, which is recoverable; overstating ships an unchecked value, which
breaches NFR-01. Two arms both failing to read a card is the one place a zero
is honest — there is no evidence of any kind to price.

### 3. `both_blank` is reasoned, not measured

n=1 on the flash-lite pairing (up from n=0 on flash — one field, banded
`low`, wrong): all 30 cards are dense (1,834 of 1,860 fields carry a code),
so a card being empty on *both* arms is rare regardless of which arm is
paired. `both_blank` inherits `agree`'s flat constant on the argument that it
is the same kind of evidence — two independent readings corroborating each
other, just about emptiness rather than about a code.

This is a judgement call, not a measurement, and it has a known gap: two
models both missing a faint code looks identical to two models correctly
reading an empty cell, and 0.97 cannot tell them apart. One wrong observation
does not close that gap — flagged as a `ponytail:` comment in
`spike/confidence.py`, alongside `test_both_blank_is_still_too_thin_to_
measure`, which fails the moment a benchmark run produces enough of them to
actually calibrate against.

### 4. What the score is attached to

`score_fields()` in `spike/confidence.py` emits `{value, confidence,
source_agreement}` per field. `value` is the primary arm's (gemini's)
normalised reading, and stays the primary arm's **even when that reading is
blank** — the `one_blank` constant is P(primary correct) measured over cases
that include the primary correctly reading an empty cell, so swapping in the
other arm's value there would attach a number to a reading it was never
measured about. Only `no_second_opinion` substitutes the other arm's value,
because that is the one case where the primary arm produced nothing at all.

`assert_every_field_scored()` enforces IT-99 AC1 directly: every field numeric,
in 0.0–1.0, on all 62 fields — 62, not 60, because 62 is the C1/C2 card (98% of
the coding cards) and an assertion hardcoded to C3's 60 fails on every real
card. It raises rather than warns, and sits inside `pair_cards()` rather than
at each call site, so every consumer — IT-100's benchmark run, IT-85's
card-level aggregation — inherits the guarantee rather than each having to
remember to call it.

### 5. `GEMINI_CONFIDENCE_BAND`, live-tested

`GEMINI_CONFIDENCE_BAND` was built under IT-98 and never run against a real
model until 09/09/2026, when it was — `gemini_extractor.py` names this issue
as the place the band-to-number decision belongs ("turning 'high' into 0.9 is
IT-99's decision, not this adapter's"), so it stayed unpriced rather than
being decided by the adapter that built the plumbing.

A single live run, 30 cards, `gemini-3.5-flash-lite` (the arm that ships),
`GEMINI_CONFIDENCE_BAND=1`. **Banding costs accuracy, measured rather than
assumed:** coded-field accuracy dropped from 91.3% unbanded to 88.8% banded —
2.5 points, the exact risk `BANDED_EXTRACTION_PROMPT`'s docstring flagged as
untested. The separation between bands is worth that cost for the fields it
flags, but the cost is real and belongs in any decision about running this in
production.

### 6. The band prices `agree`/`disagree`/`one_blank` too, not only `no_second_opinion`

The band was first folded in for `NO_SECOND_OPINION` only, scored standalone
against ground truth (band, unconditioned on class — there is no agreement
class without a second reading):

| Band | Fields | Accuracy | Constant |
| -- | -- | -- | -- |
| high | 1,633 | 91.7% | 0.92 |
| medium | 193 | 71.5% | 0.72 |
| low | 33 | 9.1% | **0.09** |

`low` is a far stronger "do not trust this" than `disagree`'s flat 0.75 —
worth acting on precisely because it is more decisive, and cheaper to obtain
(one model, one call, versus two).

**Extended the same day** by pairing the banded flash-lite run against qwen —
rather than scoring it standalone — giving real `(class, band)` accuracy
instead of accuracy-by-band alone:

| Class | Band | n | Accuracy | Constant |
| -- | -- | -- | -- | -- |
| `agree` | high | 1,211 | 96.9% | 0.97 |
| `agree` | medium | 104 | 91.3% | 0.91 |
| `agree` | low | 2 | 0.0% | *n<10, falls back to 0.97* |
| `disagree` | high | 332 | 75.0% | 0.75 |
| `disagree` | medium | 78 | 44.9% | **0.45** |
| `disagree` | low | 8 | 0.0% | *n<10, falls back to 0.75* |
| `one_blank` | high | 90 | 82.2% | 0.82 |
| `one_blank` | medium | 11 | 72.7% | 0.73 |
| `one_blank` | low | 22 | 13.6% | **0.14** |

**One documented rule, not a per-cell choice:** a `(class, band)` cell is
trusted only at n ≥ 10. `agree`/low (n=2) and `disagree`/low (n=8) are
excluded on that rule and fall back to the flat class constant — `disagree`/
low's 0/8 is suggestive (every single one was wrong) but eight observations
is not a measurement, and a documented threshold applied uniformly beats a
judgement call about which thin cells "feel" trustworthy.

This is where the band earns its keep beyond `NO_SECOND_OPINION`:
`disagree`/medium (0.45) is barely better than a coin flip, well below plain
`disagree`'s 0.75 — a disagreeing field is not one uniform kind of uncertain,
and a band tells you which kind. `one_blank`/low (0.14) is the single worst
cell in the entire formula, lower than any flat constant this document
defines.

`test_band_constants_still_match_the_live_run` pins both tables against the
saved banded output, at a wider ±0.05 tolerance than the flat class
constants' ±0.03 — every cell here has thinner support, and the tolerance
says so honestly rather than implying precision the sample doesn't support.

The constants above are measured on `gemini-3.5-flash-lite` only, and nothing
here assumes they carry to another arm — flash-lite is what ships. They do
not carry: `gemini-3.5-flash` batched at 10 was measured later the same day
and bands almost everything `high`, with no usable `low` cell at all. See
Addendum B, which leaves these constants unchanged and records the
alternative rather than adopting it.

## Deliberately not done here

- **Banding `both_blank`.** n=1, banded, wrong — one observation is not a
  cell. `both_blank` always reads as the flat (inherited) constant regardless
  of band; see §3.
- **Choosing which value wins a disagreement.** Resolved by IT-86 in D021.
  D021 selects the primary arm's reading, including a primary blank, so the
  score remains attached to the reading it was measured about. Any later
  policy that selects the other arm's value must recalibrate against the value
  actually written.
- **Writing into a D007 record.** `src/extraction/record.py` still emits
  `confidence: None`. D007's field object is `additionalProperties: false`
  with no `source_agreement` key, so carrying this triple into a real record
  needs a D007 amendment first. That downstream record work is separate from
  D021's paired-output resolution policy, so this confidence decision does not
  widen the schema unilaterally.

## Alternatives considered

**Keep the flash-based constants; treat flash-lite as close enough.** Rejected
— the gap is too large to wave off as noise, worst on `one_blank` at 11.4
points, and flash-lite is not an approximation of flash for this purpose, it
is the actual production arm. A formula whose numbers describe a model nobody
runs is not a formula that describes production, whatever its accuracy in the
abstract.

**One constant per class, no split by surviving arm and no band.** Simpler,
but on flash-lite `disagree` and `one_blank`'s flat constants are within a
point of each other — a single merged number would hide that the band still
separates them sharply (§6). Rejected: AC3 asks for a rule, not the *simplest*
possible rule, and the split is supported by data already in hand.

**Categorical output (low/medium/high) instead of a number.** Rejected before
this decision was written — D007 and `ExtractionResult.confidence` both
already commit to a float, and changing that would mean reopening D007.

**Leave `no_second_opinion` and `both_blank` unscored until measured.**
Rejected: IT-99 AC1 fails the run on a missing score, and IT-98 AC3 requires
the run to complete on a hosted-path failure. The two ACs together force a
number even where the evidence is thin — better to write down a reasoned
number and its ceiling than to leave a gap the assertion cannot pass.

**Trust every `(class, band)` cell regardless of n.** Rejected — `agree`/low
(n=2) and `disagree`/low (n=8) would otherwise hand out numbers from single-
or low-digit samples. The n ≥ 10 threshold is arbitrary in the sense that any
cutoff is, but it is one documented number applied to every cell alike, not a
judgement call made cell by cell.

## Consequences

- Every field the dual path produces carries a numeric confidence, in
  0.0–1.0, sourced to one of five agreement classes and, where available, a
  self-reported band.
- **The recalibration is a real behaviour change, not a rounding fix.** Every
  `agree`/`disagree`/`one_blank` field scores differently than it did on the
  version of this document published earlier the same day — `one_blank`
  fields drop the most, by 11.4 points.
- `disagree` and `one_blank`'s flat constants are now a near-tie (75.1% vs
  73.7%), reversed from flash's clear separation (79.1% vs 85.1%). The class
  distinction is still real once band is considered (§6); it is materially
  weaker when band is absent.
- Three of the five constants (`both_blank`, `no_second_opinion`'s per-arm
  table, and seven of `BAND_ACCURACY_BY_CLASS`'s nine possible cells) rest on
  thin or zero support and are reasoned or thresholded rather than flatly
  measured. They are marked as such in `spike/confidence.py` and here.
- `no_second_opinion`'s score depends on which arm survived, and now — like
  every other class — on the surviving/primary arm's band when it gave one.
  The same class can carry different confidence values on different fields;
  that is by design, not drift.
- The constants are pinned against the live benchmark by
  `test_constants_still_match_the_benchmark` and `test_band_constants_still_
  match_the_live_run`; adding cards to the benchmark, or a fresh banded run,
  that shift the measured percentages beyond tolerance fails those tests
  rather than silently drifting from this document.
- Running `GEMINI_CONFIDENCE_BAND=1` in production costs 2.5 points of
  coded-field accuracy against the unbanded prompt. That trade is not this
  document's to make — it belongs to whoever decides whether the band ships
  at corpus scale — but the number it would be made against now exists, for
  both the standalone and the class-conditioned case.
- `src/` is unaffected. `src/extraction/record.py` still writes
  `confidence: None`; nothing here changes production behaviour.

## Revisit if

**The band is proposed for production at corpus scale.** §5/§6's 2.5-point
accuracy cost, and the thin support behind most `(class, band)` cells, both
belong in that decision.

**A sparser benchmark produces enough `both_blank` fields to measure.**
`test_both_blank_is_still_too_thin_to_measure` will fail when it does — that
is the trigger to replace the inherited `agree` constant with a real one.

**A sparser benchmark pushes any `(class, band)` cell past n=10.** `agree`/low
and `disagree`/low would then get real constants instead of falling back to
the flat class value — `test_band_constants_still_match_the_live_run` checks
only the cells currently in the table, so a newly-measurable cell needs adding
by hand, not just a passing test.

**`gemini-3.5-flash`'s band behaviour gets measured.** ~~Nothing here assumes
it matches flash-lite's; if flash is ever reconsidered for production, its band
needs its own live run, not an inherited table.~~ **Done — see Addendum B.** It
does not match: flash batched at 10 bands 98% of fields `high` and produces no
usable `low` cell at all. It is the more accurate arm and the less informative
one. The trigger that remains is the production decision itself, which is
D012/IT-100's, not this document's.

**D021's resolution policy changes.** It currently writes the primary arm's
value, which is what these constants measure. If a later policy writes the
non-primary arm's value on a disagreement, the score attached to that field
has to be recomputed against the value actually written.

**D007 is amended to carry `source_agreement`.** Then `src/extraction/record.py`
can stop emitting `confidence: None` for dual-extracted fields, and this
formula's output has somewhere real to land.

## How far to trust this

Carried over from the findings doc's own limits, because the constants come
from the same 30 cards:

- **Dev-set figures.** All 30 cards were used to derive these constants; no
  held-out split exists yet (Test Plan §5.1).
- **Ground truth is single-keyed and unverified** (Test Plan §5.2). An error
  in it is indistinguishable from a model error on any of these constants —
  which could make them understate or overstate the real reliability, not
  predictably either way.
- **n = 30 cards, and several `(class, band)` cells are thinner than that.**
  The flat class constants' direction is clear at n ≈ 100–1,300 fields; the
  band-conditioned cells range from n=1,211 (`agree`/high) down to the n ≥ 10
  threshold itself. The closer a cell sits to that floor, the less its second
  decimal place means.
- **The recalibration itself has not been independently re-verified.** One
  pairing run, one day, one person. The magnitude of the flash → flash-lite
  shift (§1) is real and reproducible from saved data, but has not yet been
  sanity-checked by a second pass or a second reviewer.

**Provisional**, consistent with the FR-01 spike decision record, pending the
1980s dataset — which Client Meeting #3 already agreed is directional rather
than ground truth, so it would not settle these figures even once reviewed.

---

## Addendum A — qwen cannot usefully self-report a band (09/09/2026)

§6 measured the band on Gemini only, and left open whether the other arm could
supply one too. It was built and run: `QWEN_CONFIDENCE_BAND`, mirroring
`GEMINI_CONFIDENCE_BAND`, sending the same model-agnostic
`BANDED_EXTRACTION_PROMPT`. One live run, the same 30 cards, on a Colab T4.

**The answer is no, and not marginally.**

| What was measured | Result |
| -- | -- |
| Confidence values emitted | 1,104 — **every one of them `high`** |
| `medium` / `low` emitted | 0 / 0 |
| Cards that banded at all | 18 of 30 |
| Cards returning the flat shape, ignoring the prompt | 12 of 30 |
| Coded-field accuracy, banded vs unbanded | 74.4% vs 74.8% |
| Wall time per card, banded | ~310s (see cost note below) |

Not a parsing artifact — `high` is the literal value in the raw JSON, and
`parse_confidence_bands` filtered nothing out.

**Why this kills it.** A band is only worth reading if it separates: the whole
value of §6's table is that `P(correct | low)` is far below `P(correct |
high)`. qwen is 74.4% accurate and says `high` on all of it, so `P(correct |
qwen says high)` is just qwen's base rate. It cannot distinguish the quarter
of its readings that are wrong from the three quarters that are not. Compare
what makes Gemini's worth having:

| Arm | high | medium | low |
| -- | -- | -- | -- |
| `gemini-3.5-flash-lite` | 91.7% | 71.5% | **9.1%** |
| `qwen2.5-vl` | 74.4% *(all of them)* | — | — |

**This is about self-report, not about qwen.** Nothing here says qwen is a
poor second arm — its readings are exactly as useful as they were, and the
dual-extraction design already extracts that value structurally, through
whether it *agrees*. What it cannot do is introspect. The two signals are
independent, and only one of them was ever coming from this arm.

**Mechanism is inferred, not measured.** A 7B open-weight model loaded 4-bit,
with no training toward calibrated self-assessment, producing an
all-`high` distribution and dropping a nested output shape on 40% of cards, is
consistent with weak instruction-following on a compound structural change —
but this run does not isolate that, and a differently-prompted or
differently-quantised qwen was not tried. The finding that stands is the
measured one: no variance, therefore no signal.

**Cost, for completeness.** The banded run's first card took 590.8s, of which
~280s was the one-time 16.6GB model download and 4-bit load (`extract()` loads
lazily, inside the timed region), leaving **~310s of actual inference per
card**. The banded output is **2.1x the size of the unbanded** (median 3,862
bytes against 1,817), and decode dominates on a 4-bit T4, so roughly double
the per-card time is what that ratio predicts.

The unbanded arm's per-card time was never recorded, so "roughly double" is
the prediction from the output-size ratio plus the recollection that the
original run took about an hour — **not a measured comparison**. The 590.8s
and the 2.1x are measured; the unbanded baseline is not.

Coded accuracy cost 0.4 points, which is inside noise at this n.

### The key-completeness prompt fix, tested in the same run — also negative

qwen omits schema keys outright rather than answering `null`: `Washouse`
missing on 29 of 30 cards, `Pre-War Occupation` on 13, the three `Children of
H. or wife` fields on 11 each. A prompt hint was appended to qwen's request
(and only qwen's — the shared `EXTRACTION_PROMPT` was left alone precisely so
these constants stay comparable) demanding every key be present, `null` where
blank.

**`Washouse` stayed missing on 29 of 30. The hint moved nothing.**

Total missing keys went 78 → 87 across the run, but **that delta is
confounded and should not be quoted**: this run changed banding *and* the hint
at once, which is the exact trap `gemini_extractor.py`'s docstring warns about
when stacking untested prompt changes. Isolating the hint needs an
unbanded-with-hint run that has not been done. What is not confounded is the
headline case: `Washouse` absent either way.

Not truncation — banded output peaked at 4,668 bytes, roughly 1,300 tokens
against the 2,048 `max_new_tokens` cap, so the omissions are genuine
omissions rather than a response cut off mid-JSON and salvaged by
`_repair_truncated_object`.

**Consequence: both changes were reverted — neither ships.** The banding
is opt-in and off by default, so it costs nothing at runtime, but it is
measured-dead capability; the key-completeness hint is worse, being an
unconditional change to qwen's live prompt that bought nothing. A negative
result recorded here is worth more than either sitting in the tree.

## Addendum B — `gemini-3.5-flash` batched-and-banded, paired against qwen (09/09/2026)

§6 closes by noting flash's band behaviour is unmeasured and that nothing
depends on it. It has now been measured, because batching made flash
reconsiderable: `extract_batch` previously hardcoded the flat prompt and
could not carry a band at all, which is now fixed, so a banded batch=10 run
is possible for the first time. 30 cards, 3 requests, `GEMINI_CONFIDENCE_BAND=1`.

Both arms paired against the same unbanded qwen, so only the Gemini side varies:

| Class | Band | flash-lite-banded (single) | flash-banded batch=10 |
| -- | -- | -- | -- |
| `agree` | (all) | 1,317 / 96.4% | 1,358 / **98.7%** |
| | high | 1,211 / 96.9% | 1,339 / 99.0% |
| | medium | 104 / 91.3% | 19 / 78.9% |
| | low | 2 *(n<10)* | — |
| `disagree` | (all) | 418 / 67.9% | 390 / **87.7%** |
| | high | 332 / 75.0% | 374 / 89.3% |
| | medium | 78 / 44.9% | 16 / 50.0% |
| | low | 8 *(n<10)* | — |
| `one_blank` | (all) | 124 / 68.5% | 112 / **92.0%** |
| | high | 90 / 82.2% | 110 / 93.6% |
| | medium | 11 / 72.7% | 1 *(n<10)* |
| | low | 22 / 13.6% | 1 *(n<10)* |

**flash-batch10 is better in every class** — `disagree` by 19.8 points,
`one_blank` by 23.5.

**But its band stops earning its keep.** 1,823 of its 1,860 fields come back
`high` (98%). Only `agree`/medium (n=19) and `disagree`/medium (n=16) clear
the n ≥ 10 rule; there is effectively no `low` band at all (one field, whole
run). `one_blank`/low — 13.6%, the single most informative cell in §6 — has no
counterpart here. On this arm `BAND_ACCURACY_BY_CLASS` would collapse to
almost entirely flat class constants. **The band's value, as measured, is
substantially a flash-lite phenomenon**: the weaker arm is the one that knows
when it is struggling.

**The decisive figure is unflagged error** — wrong values the formula scores
as `agree`/high, which no reviewer would ever look at:

| Arm | Errors | Flagged | **Ships unflagged** | % of all fields |
| -- | -- | -- | -- | -- |
| flash-lite-banded (single) | 222 | 185 (83%) | **37** | 2.0% |
| flash-banded batch=10 | 75 | 61 (81%) | **14** | 0.75% |

flash-batch10 catches a slightly smaller *share* of its errors and still ships
2.6x fewer of them, because it makes far fewer to begin with. Better accuracy
beats better calibration here.

**The trade is throughput, and it is not free:**

| Config | Full ~6,500-card pass |
| -- | -- |
| flash-lite, single-card | ~2.6 days (2,500 req/day) |
| flash, batch=10 | ~6.5 days (650 requests, 100/day across 5 keys) |
| flash-lite, batched | not viable — loses 23 points, stops reading after ~3 cards |

2.5x the calendar time for 2.6x fewer silent errors.

**Nothing in this document changes on the strength of this.** The constants
above stay calibrated to flash-lite, which is still what ships (D012). This
addendum records that a better-quality configuration now exists and what it
would cost — the choice belongs to IT-100 and any revision of D012, not here.
Taking it would mean recalibrating these constants a third time, and retiring
most of §6 along with them.

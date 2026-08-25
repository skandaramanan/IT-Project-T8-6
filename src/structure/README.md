# Card structure discovery

Works out what card structures actually exist across the archive, rather than
assuming the four-page record cycle holds. Feeds the extraction work: you cannot
write a schema for forms you have not seen.

The question it answers is **what structures are there**, not *what does every
page say*. That distinction drives every design decision below.

It serves **IT-52** (US-01, extract numeric coding-card information) — FR-01,
FR-19 and FR-21 — and IT-73's assessment of secondary card types. *What this
means for IT-52* below answers each requirement directly; read that first if
you want the decisions rather than the method.

## The three passes

| Pass | What it does | Cost |
| --- | --- | --- |
| `analyze` | One VLM call per page → one JSONL row per page | Network, rate-limited, resumable |
| `report` | Clusters those rows into distinct structures | Free, local, instant |
| `synthesize` | One multi-image call describing the clusters | One request — **currently broken, see below** |

They stay separate because they fail differently. `analyze` is a long throttled
network job; `report` is pure local computation you can re-run at a different
`--merge-threshold` as often as you like without paying for the model again.

## Running it

```bash
uv run main.py analyze --per-unit 20 --workers 32 --max-requests 940
uv run main.py report --export-images --reference-cards
```

880 pages across all 44 readable units, roughly half an hour. Then `report`
writes the clusters, per-cluster label frequencies, ranked anomalies, four-page
cycle breaks, and — with `--export-images` — the scans of the exception pages so
you can look at the real oddities yourself.

`anomalies.csv` is the low-yield one: 97% of its rows appear on exactly one
card, and the recurring ones are punch holes in eleven spellings. Skim the top
by `cards` and ignore the tail.

**Where this is up to.** After a partial 2026-08-25 run, `results/pages.jsonl`
holds **738 pages from 39 units** and 15 failures. It stopped early — see *A
second 429, and it is not the daily cap* below — leaving **142 pages
outstanding**, so units **216453, 216454, 216459, 216460, 216463** are still
thin or empty. The 2026-08-24 `200 with no choices: 502` failures on the JPEG
2000 units cleared on retry, which confirms they were provider flakiness rather
than a structural signal. Rerunning the same command finishes them:
selection is deterministic, `completed_ids` skips what is done, and failures are
retried unless you pass `--skip-failed`. `--dry-run` prints the outstanding count
without sending anything.

That gap matters more than 142 pages suggests. The missing units are contiguous
at the tail of the archive, and 216431 has already shown that one unit can hold a
form nothing else does — so *"no other card types exist"* is not yet a claim this
data supports.

`report` is free and local. Rerun it whenever, including at a different
threshold: `report --sweep`, then `report --merge-threshold 0.75
--export-images`.

**Do not run two `analyze` commands at once.** There is a `flock` on the results
file that will stop you, for a reason recorded under *Concurrency* below.

## What the run found

843 pages sampled from all 44 readable units — 3.9% of the archive. Every share
below is a sample rate, not a count.

**There are six printed front forms and one printed reverse form.** An earlier
version of this document said three. That was wrong twice over, and both errors
are worth knowing about because both are easy to repeat.

### The forms

| | form | pages | units |
| --- | --- | --- | --- |
| **S1** | Survey card, canonical | 242 | 43 |
| **S2** | Survey card, 2nd printing — `Frontage` where S1 has `Probable Age` | 3 | 216434, 216435 |
| **S3** | **1941/43 longitudinal card** — two dated blocks per person, plus `Reasons for Change` and `Reception` | 9 | 216459, 216461 |
| **C1** | Coding card, canonical | 153 | 37 |
| **C2** | **Coding card #2** — carries `No. of Family Boarders`, spells out `...Unearned Income` where C1 truncates to `I` | 72 | 20 |
| **C3** | **Multi-family punch-card sheet** — fields numbered 1–80, repeating blocks for `Dominant Family` / `Family 2` / `3` / `4` | 4 | 216463 |
| **R1** | Finance and wartime opinion, on the reverse — `Cost of Living`, `Rationing`, `War Loan`, `Attitude to Post-War` | 12 | 216431, 216459, 216461 |

Example scans for every front form are in `results/reference_cards/`, indexed by
`results/front_structures.md`.

S3, C3 and two thirds of R1 came from five units that had never been sampled.
C2 was hiding in plain sight — see below.

### What this means for IT-52

IT-52 is *US-01 — extract numeric coding-card information*. Each requirement,
answered against the data above.

#### FR-01 (Must) — extract fields from the numeric coding card

**The primary extraction target is not one form. It is two, and a schema built
on C1 alone fails on roughly a third of it.**

| | pages | share of coding cards |
| --- | --- | --- |
| C1 canonical | 153 | 68% |
| C2 | 72 | **32%** |
| C3 multi-family punch-card sheet | 4 | 2% |

C2 differs from C1 by a handful of fields, not a redesign, so one schema with
C2's extra fields marked optional covers both. C3 is a different card — 80
numbered columns, repeating per-family blocks — and needs its own schema or an
explicit exclusion.

#### FR-19 (Must) — split each scan into front, reverse and coding card

**Solved, deterministically, with no model call.** Two steps:

1. **Front vs reverse — page parity.** Odd pages are fronts 91%, even are
   reverses 84%. Take the phase per unit: five units number their fronts even.
2. **Survey vs coding — label-set overlap.** The two canonical sets share only
   10 labels, 17% of the smaller set. Scoring each page against both and taking
   the winner misclassifies **0 of 495 pages**.

Do not use the model's own `page_role`: it called 148 pages a "back" and was
confident about 7.

Two findings the implementation has to respect:

- **The cards are interleaved, not segregated.** A real unit runs
  `SCCCSSSCSCSSCSCSCSCS`. Nothing positional will work.
- **"Fewer than 3 present" is the common case, not an edge case.** Only **16 of
  44 units** hold roughly equal numbers of survey and coding fronts. Unit
  216461 has 10 survey fronts and **zero** coding cards; 216444 has 1 survey to
  9 coding. FR-19's clause about missing cards is load-bearing and must be
  built for, not bolted on.

#### FR-21 (TBC) — a secondary card type

The ticket makes this conditional: prevalence decides whether it becomes a
formal FR or an explicit non-goal.

**The evidence says formal FR. Three distinct secondary types exist, not one:**

| | pages | units |
| --- | --- | --- |
| R1 finance / wartime opinion (on the reverse) | 12 | 216431, 216459, 216461 |
| S3 1941/43 longitudinal survey card | 9 | 216459, 216461 |
| C3 multi-family punch-card sheet | 4 | 216463 |

Each recurs within its units rather than appearing once, so none is an
annotation or a stray. **Caveat: the ticket asks for a prevalence check across
the full 6,000-card set, and this is a 3.9% sample.** It is enough to rule out
"no secondary types exist" — it is not the prevalence figure the ticket asks
for. What it does establish is that the answer is not a non-goal.

#### NFR-06 (Should) — traceability

Every row in `results/pages.jsonl` carries `card_id`, `unit`, `pdf` and
`page_number`, so any extracted value traces to a source page without extra
work. Field-level location within a page is not captured and would need the
extractor to return bounding boxes.

### Two mistakes this spike made

**A cluster is not a form, and a big cluster is not one form.** C2 does not
differ from C1 by enough to clear the 0.8 merge threshold, so 61 of its pages
were absorbed into the C1 cluster and the remaining 11 looked like a fringe
oddity. Checking whether the big cluster was internally uniform is what found
it, and the split is total:

| cards inside the C1 cluster | also carry ≥2 other C2 markers |
| --- | --- |
| 61 with `No. of Family Boarders` | **100%** |
| 151 without | **0%** |

Not a gradient — a partition. **C2 is roughly a third of all coding cards**, not
a curiosity. The same test run against the S1 cluster comes back clean, so this
was specific to the coding cards, but the check belongs on every large cluster.

**A field the model reads unevenly looks exactly like a variant field.** The
honest test is whether a candidate field *partitions* the pages:

| | appears on | verdict |
| --- | --- | --- |
| `Frontage` vs `Probable Age` | 3 pages vs 241, never both | real: S2 |
| `wkly cost transport` vs `wkly cost transpor` | 142 and 99, summing to 241 | one field, read two ways |

Anything that sums to the cluster size is transcription noise. Anything that
splits it is a form.

### Bleed-through looks exactly like a new form

A blank reverse whose printed front shows through the paper is read as a front,
mirrored, and clusters on its own. Five of those were briefly reported as new
front structures, and all five sat on reverse pages.

Two filters catch them, and the first is the one to rely on:

- **A front cluster with no printed labels at all is a contradiction** — dropped
  outright. This needs no per-unit phase, so a bad phase estimate cannot defeat it.
- **A cluster with most of its pages on reverse parity is a reverse cluster**,
  however the odd page out is labelled.

The per-unit phase itself must be taken only from clusters carrying a real
printed label set. Deriving it from every page the model *called* a front is
circular: bleed-through is called a front, so in a unit with enough of it the
phase flips and then waves the bleed-through through.

### What is on a page

| | pages | share | ~archive-wide |
| --- | --- | --- | --- |
| A printed front | 495 | 58.7% | 12,750 |
| Reverse carrying handwriting | 240 | 28.5% | 6,180 |
| Genuinely empty | 108 | 12.8% | 2,780 |

**Reverses are not blank.** 240 of 348 — 69%, across 41 of 44 units — carry
handwriting. Any plan that skips the reverses drops most of them.

### White blocks over the values

83 pages, **~11%**, concentrated in 11 units: white rectangles sitting over the
field values. One coding-front cluster (`ee86fadc`) is nothing but a C2 card
under them — all 42 of its readable labels are a subset of C2's.

**The evidence points at a scanning fault, not archival redaction.** The blocks
are pure white with hard, pixel-aligned edges, sitting over the scan rather than
on the card; redaction on a 1940s card is physical and would photograph with
texture and ragged edges. Concentration in 11 units fits a scanning batch.

Confirm this with whoever ran the digitisation. **A scanning fault can be
rescanned; redaction is a permanent ceiling on extraction accuracy that belongs
in the requirements.**

### How far to trust this

All 44 readable units now have pages, which removes the largest gap. What
remains is depth, and one number sets the scale: **S2 appears on 3 of the 40
pages sampled from the two units that carry it.** A form at that rate is missed
about one time in five by a 20-page sample of a unit that holds it — and C3 was
found on 4 pages of one unit, S3 on 9 pages of two.

So forms this rare are found by luck, not by coverage, and the sample is 3.9% of
the archive. The supportable claim is **"seven forms exist and rare ones are
probably still unfound"** — not "seven is the total".

37 pages remain unanalysed (all provider timeouts, not cap failures).

### Next steps

| | what it settles | ticket | cost |
| --- | --- | --- | --- |
| Extend the coding schema to C2 | C2 is 32% of the primary extraction target | **FR-01** | no requests |
| Build the splitter: parity, then label-set score | Both steps measured; 0/495 misclassified | **FR-19** | no requests |
| Deepen 216459, 216461, 216463 | Whether S3, C3 and R1 are unit-local or archive-wide | **FR-21** | ~60 pages/unit |
| Open two reference cards | White blocks: scanning fault or redaction | requirements | free |
| Retry the 37 failures at `--workers 8` | Completes the sample | — | ~40 requests |

The first two need no further model runs and can start now. FR-21 is the one
still open: the ticket wants prevalence across the full card set, and this is a
3.9% sample — enough to show secondary types exist, not enough to size them.

## What we measured

Everything here was measured on this archive against `stealth/ox-alpha`, not
assumed. Where an earlier assumption was wrong, that is noted, because the wrong
version is the one someone will otherwise re-derive.

### There is a daily request cap

1,000 free-model requests per day, resetting 00:00 UTC:

```
429 Rate limit exceeded: free-models-per-day-stealth
X-RateLimit-Limit: 1000  X-RateLimit-Remaining: 0
```

An earlier probe of 120 pages drew no 429 and we concluded no cap bound. It
does — the probe simply never reached it. Absence of a 429 at 300 requests says
nothing about the cap at 1,000.

It counts **requests**, so `--workers` cannot stretch it, and two things spend it
for nothing: a request that crosses the client timeout is still billed, and a
stubborn page can spend up to `attempts` of them.

The reset is 00:00 UTC, which in Melbourne is **10:00 AEST**. Two runs on the
same calendar afternoon and the following morning therefore share one budget —
that is not obvious and it has already cost a run.

A capped run does not fail, it goes silent. The 429 carries no `Retry-After`, so
`retry_after_from` falls back to `X-RateLimit-Reset` and `gate.pause()` parks
every worker until the reset — hours, not seconds. It looks identical to a hang:
threads alive, no output, no new rows. Tell them apart without guessing — a
parked run holds **zero open sockets and ~0% CPU** (`lsof -nP -p <pid> -a -i`),
where a working one holds dozens. `curl` the API with a one-token request and
read `X-RateLimit-Remaining`; a 429 costs nothing, because it is refused before
generation.

### A second 429, and it is not the daily cap

Two different 429s arrive from this provider and they need opposite responses:

| | daily cap | shared upstream pool |
| --- | --- | --- |
| body | `Rate limit exceeded: free-models-per-day-stealth` | `limit_source: upstream_provider_shared_pool` |
| headers | `X-RateLimit-Reset` | none |
| clears in | hours, at 00:00 UTC | minutes |
| right response | park until the reset | wait a minute, retry |

`retry_after_from` reads the reset header, so the daily one parks correctly. The
pool one names no header at all, and the backoff used to fall through to
`min(2**attempt, 30)` — 2s, 4s, 8s, 16s. All four attempts land inside 30
seconds, well before a queue that clears in minutes, so the page is recorded as
a failure having spent **four billed requests** on nothing.

Measured 2026-08-25: 13 of the first 97 pages, **100% of that run's failures**.
The backoff for a pool 429 is now 60s per attempt. `spike/ox_alpha_extractor.py`
had already found this and used 60s; the structure client had not learned it.

The lesson generalises past this bug: a 429 is not one condition. Read
`limit_source` before deciding how long to wait, and treat "no `Retry-After`" as
"the provider did not say", not as "retry immediately".

### There is a ~175 second generation ceiling

This is the finding that shaped the plan. Measured 2026-08-24 on 30 pages of
unit 216418:

| `--batch` | latency | result |
| --- | --- | --- |
| 1 | 16–114s | 22/30 ok |
| 5 | 175–180s, **uniform** | 0/30 |
| 10 | ~178s per attempt | 0/30 |

Uniform latency at the point of failure is the tell: a wall the provider holds
up, not queueing, and not our client timeout — those were set to 540s and 840s
for the batched arms and never fired.

The failure arrives as an **HTTP 200**. OpenRouter pads the socket with
whitespace while the upstream works, then closes it with either nothing or an
`{"error": ...}` behind the padding. A direct probe returned 4,017 bytes of pure
whitespace and no JSON at all. Neither shape has a `choices` key, which is why
`_post` now reads the envelope before indexing into it.

### Concurrency is the expensive mistake

Four `analyze` runs were once started concurrently at 1,114 workers between
them. Each read the same empty results file, computed the same to-do list, and
consumed the entire day's 1,000 requests re-analysing identical pages — and
recorded zero rows, because every request queued past the timeout.

`completed_ids` reads the results file once at startup and cannot see a run
still in progress. Hence the `flock`: one writer at a time. It releases on
process death, so a hard kill leaves no stale lock.

### Worker count

32 workers gave 27.5 pages/min; 60 gave 18.9. Past the knee the provider absorbs
concurrency by getting slower rather than refusing, and the tail crosses the
client timeout. Nothing below 32 has been measured, so 32 is the best known
value, not a proven optimum.

## What we tested and rejected

**Batching several pages per request.** Implemented, tested, and shelved. The
cap counts requests, so `--batch N` divides the bill by N — but every batch
crosses the 175s wall. The flag still exists and is correct (one request, one
row per page, keyed by card id, all-or-nothing validation so a short response
retries whole rather than silently recording N-1 pages). It is simply not usable
against this provider. `calibrate.py` is the harness that measured it; the arms
cost 45 requests.

Note this also casts doubt on `synthesize`, which sends ~24 images in one call.
It was cited as precedent that multi-image requests work. There is no evidence it
has ever succeeded, and given a two-image request cannot finish in 175s, it
almost certainly has not. **Treat pass 3 as unproven.** `report` is the real
deliverable.

**Alternative providers.** TokenRa and AI/ML API both resell the same anonymous
stealth slot that OpenRouter originates — AI/ML API's own docs say so. Switching
trades a documented cap for an undocumented one. AI/ML API additionally returned
"You've run out of funds" on an unfunded account, behind a Cloudflare
fingerprint block on `Python-urllib` that a `User-Agent` header fixes.

**Filtering blank backs locally, by file size.** Ruled out twice over. Role
averages separate cleanly — survey-front 520 KB, coding-front 388 KB, survey-back
306 KB, coding-back 261 KB — but the ranges overlap (backs 227–368 KB, fronts
375–546 KB), so the filter would not have been accurate. It would also have been
filtering the wrong thing: 57% of reverses carry handwriting, so "blank back" is
not a category that exists at the rate the idea assumed.

## Why sampling, not the whole corpus

21,722 pages at one request each is 21.7 days of daily caps. Batching cannot
compress it and no provider lifts it, so the census is not available — but it was
never necessary.

Within a unit, structure barely moves: every front in unit 216418 came back at
60–62 fields. The marginal page from a unit already sampled buys almost nothing,
while the first page from an unsampled unit can reveal a whole structure. The
signal is entirely in the breadth.

`--per-unit 20` takes 20 pages from each of the 44 units, spread evenly through
each rather than off the front — a unit's first 20 pages are consecutive records
filled in by one clerk in one sitting, the stretch least likely to disagree with
itself. Selection is deterministic, so a run stopped by `--max-requests` resumes
on exactly the same pages.

## Notes on the data

- 44 unit PDFs are readable; **216436 is corrupt** and reported as an unreadable
  unit rather than crashing the run.
- 7 units (216412–216417, 216431) store pages as JPEG 2000, which the provider
  rejects; they are transcoded on the way out.
- 4 units (216424–216427) wrap the scan in a Form XObject, so a top-level-only
  XObject walk finds nothing there.
- 22 of the 44 units have page counts not divisible by four, so the four-page
  record cycle demonstrably breaks somewhere. The pipeline labels each page's
  role and reconstructs the cycle afterwards rather than assuming it — and the
  measured answer is that the four-page cycle holds on 48% of pages while a
  two-page front/reverse one holds on ~87%. See *Separating front from reverse*
  above.
- Pages are never written to disk. Each scan is copied out of the PDF
  byte-for-byte, handed to a worker, and dropped; materialising all ~21.7k would
  put ~6.6 GB of derived data beside a dataset that already holds it.

## Files

| File | |
| --- | --- |
| `cli.py` | The one entry point. Every flag is documented in `--help` |
| `inventory.py` | Enumerates pages, extracts scan bytes, handles the encoding oddities |
| `analyze.py` | Pass 1 — the client, retry ladder, rate gate, batching, sampling |
| `report.py` | Pass 2 — normalise, fingerprint, cluster, rank anomalies, export reference cards |
| `synthesize.py` | Pass 3 — unproven, see above |
| `calibrate.py` | Compares finished `analyze` runs. Sends nothing, re-runnable |

## Output

| In `results/` | |
| --- | --- |
| `front_structures.md` | **Start here.** One row per front-card structure, with its example scan |
| `reference_cards/` | One PNG per front-card structure |
| `structures.csv` | Every cluster, including reverses and defects |
| `canonical.md` | The two canonical label sets, with how often each field appears |
| `processing.md` | Pages analysed, failures, retries spent |
| `exceptions.csv`, `anomalies.csv` | Off-canonical pages, and every anomaly ranked rarest-first |

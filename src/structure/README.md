# Card structure discovery

Works out what card structures actually exist across the archive, rather than
assuming the four-page record cycle holds. Feeds the extraction work: you cannot
write a schema for forms you have not seen.

The question it answers is **what structures are there**, not *what does every
page say*. That distinction drives every design decision below.

It serves IT-73 (assess secondary card types, FR-21) and FR-19 on IT-52
(separating each scan into front, reverse and coding card). *What the run found*
below is written against those.

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
uv run main.py report --export-images
```

880 pages across all 44 readable units, roughly half an hour. Then `report`
writes the clusters, per-cluster label frequencies, ranked anomalies, four-page
cycle breaks, and — with `--export-images` — the scans of the exception pages so
you can look at the real oddities yourself.

`anomalies.csv` is the low-yield one: 97% of its rows appear on exactly one
card, and the recurring ones are punch holes in eleven spellings. Skim the top
by `cards` and ignore the tail.

**Where this is up to.** The 2026-08-24 run holds 642 pages from 34 units in
`results/pages.jsonl`. It stopped on the `--max-requests` budget with **238 pages
outstanding** — 211 never sent plus 27 that failed — so units **216449, 216450,
216451, 216452, 216453, 216454, 216459, 216460, 216461, 216463 have no pages at
all**, and 216448 has 9 of 20. 25 of the 27 failures are `200 with no choices:
502` and 22 of those are in 216412/216413 — provider flakiness on the JPEG 2000
units, not a structural signal. Rerunning the same command finishes them:
selection is deterministic, `completed_ids` skips what is done, and failures are
retried unless you pass `--skip-failed`. `--dry-run` prints the outstanding count
without sending anything.

That gap matters more than 238 pages suggests. The missing units are contiguous
at the tail of the archive, and 216431 has already shown that one unit can hold a
form nothing else does — so *"no other card types exist"* is not yet a claim this
data supports.

`report` is free and local. Rerun it whenever, including at a different
threshold: `report --sweep`, then `report --merge-threshold 0.75
--export-images`.

**Do not run two `analyze` commands at once.** There is a `flock` on the results
file that will stop you, for a reason recorded under *Concurrency* below.

## What the run found

642 pages across 34 of 44 units — 3% of the archive. Shares below are sample
rates; archive-wide figures are extrapolations, not counts.

### Two card structures, not twenty-one

`structures.csv` lists 21 clusters at `--merge-threshold 0.8`. Two are real
forms — **survey-front** (195 pages, 52 labels on ≥90% of them) and
**coding-front** (185 pages, 55). Four are buckets of reverses with no printed
labels. **The remaining fifteen are singletons, and every one is a scan defect
rather than a form**: rotated 90° or 180°, printed content visible only as
bleed-through, or white blocks over the values. Cluster count is not form count.

The long tail in `canonical.md` is transcription noise, not variant fields —
`washhouse` 59% / `washouse` 41% is one field read two ways. The threshold knee
is at 0.75 (20 clusters, 3% off-canonical); the 0.8 default sits just above it.

### What is actually on a page

Each page matched against the two canonical label sets:

| | pages | share | ~archive-wide |
| --- | --- | --- | --- |
| Primary form — survey-front or coding-front | 376 | 58.6% | 12,700 |
| Reverse, handwriting only, no printed fields | 144 | 22.4% | 4,900 |
| Truly empty | 112 | 17.4% | 3,800 |
| Printed form that is neither primary | 10 | 1.6% | 350 |

Six of those last ten are the scan defects. The other four are all in one unit.

### A third printed form, in unit 216431

Typed prompts with handwritten prose beneath — household finance and wartime
opinion, nothing to do with the dwelling grid on either primary form:

```
Expenditure of - Cost of Living:   Rationing:   Furniture, etc.:
Savings Certificates, Stamps and Clubs:   War Loan:   Savings Bank:
Subscriptions and Premiums:   Cash:   Attitude to Post-War:
Miscellaneous:   Human Nature:   General Attitude:
```

Pages 268, 292 and 316 of 216431 carry an almost identical prompt set, so it is
a form in repeated use, not an annotation. All three are on **even** pages, so it
occupies the reverse slot — a variant reverse, not a fourth card in the cycle.
The other 33 units leave the reverse unprinted, carrying at most short notes
along the top.

Three pages in a 486-page unit proves the form exists and says nothing about its
rate. That is the FR-21 answer for IT-73; settling the rate costs one day's cap:
`analyze --units 216431`, 486 pages.

### The cycle is two pages, not four

The four-page cycle holds on 48% of pages and 33 of 34 units break it. A two-page
one holds far better: **odd pages are fronts 91%** (341/373), **even pages are
reverses 84%** (227/269). Page parity is a free, deterministic front/reverse
separator — which is what FR-19 on IT-52 needs, because the model's own role
label is not: every one of the 114 pages it called a back came back below `high`
confidence, and it scattered identical unprinted reverses across four role names
(`coding-back` got 11 pages where the cycle implies ~160).

`cycle_breaks` used to walk the cycle by position in the row list, which is
meaningless on a sample taken every ~25th page; it reported 34/34 units and
13–17 breaks per 20 pages. It now phases off the page's own number. If that
report ever flags every unit again, suspect this first.

### Reverses are not blank

147 of the 259 reverses — **57%** — carry handwriting, across 31 of 34 units.
Only 17% of all pages are genuinely empty.

### A tenth of pages have blocks over the values

63 of 642 pages, 9.8%, ~2,100 archive-wide: white rectangular blocks obscuring
field values, in consistent wording across many units. **Nobody has established
whether this is archival redaction or a scanning artifact** — one is a ceiling on
extraction accuracy that belongs in the requirements, the other is an ingest bug.
Costs nothing to settle: open `results/exception_images/216412_p0182.jpg`.

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
  two-page front/reverse one holds on ~87%. See *The cycle is two pages, not
  four* above.
- Pages are never written to disk. Each scan is copied out of the PDF
  byte-for-byte, handed to a worker, and dropped; materialising all ~21.7k would
  put ~6.6 GB of derived data beside a dataset that already holds it.

## Files

| File | |
| --- | --- |
| `cli.py` | The one entry point. Every flag is documented in `--help` |
| `inventory.py` | Enumerates pages, extracts scan bytes, handles the encoding oddities |
| `analyze.py` | Pass 1 — the client, retry ladder, rate gate, batching, sampling |
| `report.py` | Pass 2 — normalise, fingerprint, cluster, rank anomalies |
| `synthesize.py` | Pass 3 — unproven, see above |
| `calibrate.py` | Compares finished `analyze` runs. Sends nothing, re-runnable |

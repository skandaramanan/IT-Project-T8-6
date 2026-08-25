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

738 pages sampled from 39 of the 44 readable units — 3.4% of the archive. Every
share below is a sample rate, not a count.

**There are three printed forms, not the twenty-one the cluster count suggests:
a survey card in two printings, and one numeric coding card.** The rest of the
clusters are the same forms scanned badly.

### The three forms

`report --reference-cards` writes one example scan per front-card structure to
`results/reference_cards/` and indexes them in `results/front_structures.md`.
All six were opened and looked at:

| structure | pages | verdict |
| --- | --- | --- |
| `36d15987` numeric | 192 | **The coding card.** The canonical numeric form |
| `23d8099c` survey | 215 | **The survey card.** The canonical text form |
| `58fdc422` survey | 3 | **A second printing of the survey card** — has `Frontage` where the canonical has `Probable Age`. Units 216434 and 216435 |
| `88148aab` numeric | 9 | Not a variant. Same card, clustered apart on transcription noise |
| `ee86fadc` numeric | 1 | Same card, white blocks over the left column |
| `b56f9cd3` survey | 1 | Same card, white block over ~80% of the page |

A fourth form exists on the reverse of one unit — see *The 216431 form* below.

### Telling a real variant from a bad scan

This is the part worth reusing, because the cluster count is misleading on its
own and the same test settles every case: **a real variant field partitions the
pages; a misread one is scattered across both groups.**

| | appears on | verdict |
| --- | --- | --- |
| `Frontage` vs `Probable Age` | 3 pages vs 214, **never both on one page** | a real second printing |
| `No. of Family Boarders` | 9 "variant" pages **and 47 of the 192 canonical ones** | one card, read inconsistently |

`88148aab` also sits at 0.797 label overlap against a merge threshold of 0.8 —
it failed to merge by 0.003. Treat anything that close to the threshold as one
form until a field partitions it cleanly.

### Separating front from reverse: use the page number

FR-19 on IT-52 needs each scan split into front and reverse. **Page parity does
it for free and the model's own role label does not.**

- Odd pages are fronts on **90%** of pages; even pages are reverses on **84%**.
- The model labelled 148 pages a "back" and was confident about 7 of them.
- Five units (216412, 216415, 216420, 216423, 216447) number their fronts even,
  so take the parity per unit, not globally.

This also removes a trap. A blank reverse whose printed front shows through the
paper is read as a front, mirrored, and forms its own cluster. Four of those
were briefly reported as new "front structures". All four sat on reverse pages,
so filtering on parity drops them without anyone having to judge.

### What is on a page

| | pages | share | ~archive-wide |
| --- | --- | --- | --- |
| A printed front — survey or coding | 428 | 58.0% | 12,600 |
| Reverse carrying handwriting | 210 | 28.5% | 6,200 |
| Genuinely empty | 100 | 13.6% | 2,900 |

**Reverses are not blank.** 210 of 310 — 68%, across 36 of 39 units — carry
handwriting. Any plan that skips the reverses drops most of them.

### The 216431 form

Unit 216431 carries a form nothing else does: typed prompts with handwritten
prose beneath, on household finance and wartime opinion — `Cost of Living`,
`Rationing`, `War Loan`, `Attitude to Post-War`. It is on pages 268, 292 and 316,
all **even**, so it occupies the reverse slot rather than adding a fourth card.
See `results/reference_cards/` for page 292.

Three pages in a 486-page unit proves the form exists and says nothing about how
often it appears. That is the FR-21 answer for IT-73.

### White blocks over the values

83 pages, **11.2%**, ~2,400 archive-wide, concentrated in 11 units of 39: white
rectangles sitting over the field values.

**The evidence points at a scanning fault, not archival redaction.** In
`coding-front_ee86fadc_216414_p0081.png` and `survey-front_b56f9cd3_216431_p0219.png`
the blocks are pure white with hard, pixel-aligned edges, sitting over the scan
rather than on the card; redaction on a 1940s card is physical and would
photograph with texture and ragged edges. Concentration in 11 units fits a
scanning batch rather than a redaction policy.

This needs confirming with whoever ran the digitisation, because the two answers
have opposite consequences: **a scanning fault can be rescanned; redaction is a
permanent ceiling on extraction accuracy that belongs in the requirements.**

### How far to trust this

The front inventory is complete *for the pages sampled*: no page sitting on a
front-parity page and labelled something else carries 20 or more printed labels,
so no printed form is hiding under a `blank` or `other` label.

The sample is the limit, and one number sets the scale. **The survey second
printing appears on only 3 of the 40 pages sampled from the two units that have
it** — a form at that rate has roughly a 1 in 5 chance of being missed entirely
in a 20-page sample of a unit that holds it. It was nearly missed.

Against that: 5 of the 44 readable units have no pages at all, four more have
fewer than 18, and the whole sample is 3.4% of the archive. So the supportable
claim is *"three forms are what 3.4% of the archive contains"* — not *"these are
the only forms that exist"*.

### Next steps

| | what it settles | cost |
| --- | --- | --- |
| Finish the 5 empty units | Whether a fourth form exists. The biggest open risk | ~150 requests, under a day's cap |
| Open two reference cards | Whether the white blocks are a scanning fault or redaction — a requirements decision | free, the scans are already on disk |
| `analyze --units 216431` | How often the finance/opinion form appears | 486 requests, one day's cap |
| Build the schema on parity | Front/reverse split for FR-19, without the model's role label | already available |

The schema work can start now. It needs the two canonical label sets, plus
`Frontage`/`Probable Age` as alternatives on the survey card.

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

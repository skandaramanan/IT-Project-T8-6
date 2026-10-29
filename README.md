# Wilfred Prest Survey

Tools developed by Team 8/6 for University of Melbourne Archives to extract
structured data from historical survey cards and support human review of
uncertain readings.

The project has two main parts:

- **Extraction pipeline:** reads scanned PDFs and produces structured records
  with source references, field statuses and confidence scores.
- **Review tool:** lets reviewers compare extracted readings with the original
  scans, accept or correct values, and share their decisions.

## Start here

| What you want to do | Where to start |
| --- | --- |
| Review extracted records | Review tool user manual — pending merge (`REVIEW-TOOL-MANUAL.md`) |
| Extract a new batch of scans | Extractor user manual — pending merge (`EXTRACTOR-MANUAL.md`) |
| Build or maintain the application | [Developer setup](#developer-setup) and [technical documentation](#technical-documentation) |
| Understand the output format | [Record schema guide](docs/decisions/D007-output-record-schema.md) |

The review tool runs locally in your browser. Reviewing existing records
does not require a Gemini API key. Until the manuals are merged, use the
[review runbook](docs/review-backend.md) and
[extraction instructions](#extracting-a-new-batch-of-scans) below.

## How the workflow fits together

Scanned PDFs → extraction → structured records → review queue →
human review → corrected records

1. **Extract:** the pipeline reads a region's scanned PDFs and writes
   structured records to a regional JSONL file. An optional second model
   reading can be merged to score confidence from model agreement.
2. **Prepare review:** an operator provides matching records, a review
   assignment and access to the source PDFs. Reviewed data lives in a separate
   checkout of the `review-data` branch.
3. **Review:** choose a region and dwelling, compare each queued field with
   its scan, then accept the reading, fix it, or mark it blank or unreadable
   where those actions are supported. Identity problems can also require
   comparing cards and correcting their dwelling links.
4. **Save and share:** decisions and history save locally. The tool shares
   changes through the `review-data` Git branch. The interface distinguishes
   locally saved work from successfully shared work.
5. **Continue:** reopen the same data checkout and assignment to resume.
   History and Undo support checking and reversing earlier decisions.

Assign different regions to concurrent reviewers. Do not run extraction
against a data checkout while it is being reviewed. Detailed setup, recovery
and relinking behaviour are covered by the guides linked below.

## Layout

- `backend/survey/` — the pipeline, installed as the `survey` package
- `frontend/` — the React review interface and its browser/component tests
- `benchmark/` — calibration harness; imports `survey`, never the reverse
- `schema/` — the output record schema the pipeline, tests and review tool share
- `results/` — the extracted dataset, one `<region>.jsonl` per region (committed)
- `tests/` — tests
- `docs/` — decision records and assets
- `data/` — scans, raw model responses, benchmark set (gitignored)

Why it's laid out this way:
[docs/decisions/D024-repository-layout.md](docs/decisions/D024-repository-layout.md).

## Developer setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) once:

```bash
brew install uv                   # macOS
winget install --id=astral-sh.uv  # Windows
```

Then clone and sync:

```bash
git clone https://github.com/skandaramanan/IT-Project-T8-6.git
cd IT-Project-T8-6
uv sync
```

This installs the Python dependencies. `uv sync` creates the virtualenv and
installs everything from `uv.lock`. You do not need to install Python yourself — the
version is pinned in `.python-version` and uv fetches it for you. The first
sync downloads Python and the packages, so give it a minute; later ones are
near-instant.

Don't activate the venv by hand and don't `pip install` into it — that change
would exist only on your machine. Run things with `uv run`, and add
dependencies with `uv add <package>`, which updates `pyproject.toml` and
`uv.lock` together so everyone gets them.

Why uv, and why Python 3.12:
[docs/decisions/D001-dependency-manager.md](docs/decisions/D001-dependency-manager.md).

### Build the review interface

Building the React reviewer also requires Node **22.12+ in 22.x, or 24+**, and
npm. From the repository root:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

This creates `frontend/dist`, which the local Python backend serves. A fresh
source clone does not include these built assets. Without them the backend
serves a small API integration page instead of the full reviewer. Restart the
backend after building. A prepared reviewer package can include the built
assets, so its operator does not need Node.

See the [frontend guide](docs/reviewer-ui.md#build-and-run) for development
commands and the [review runbook](docs/review-backend.md#setup-and-launch) for
configuration and launch instructions.

## Data and secrets

### The survey scans

The scans are not in this repo and never will be. The archive is 6.4 GiB, which
is well past what git is for, so it lives in a
[shared Google Drive folder](https://drive.google.com/drive/folders/1z8_i1IYzUCZYtE5NxB9xQ8kAQ_rh-DMV),
restricted to the five team accounts. If you land on a request-access screen,
you're signed into the wrong Google account — switch to your student one.

Provenance: sent by Lachlan Glanville (UniMelb Archives) on 6 August 2026 as
`Prest_survey.zip` over AARNet FileSender. That transfer expired on 27 August
2026, so the Drive copy is now the only one — treat it accordingly.

Sync the scans to `data/`, which is gitignored. Nothing under `data/` is ever
committed, including anything you derive from it — raw model responses,
benchmark runs, spike output. The one exception is the scored dataset in
`results/`, which is committed so the client can get corrections through GitHub
([D025](docs/decisions/D025-committed-results.md)).

Three sets of cards exist and they are easy to confuse:

| What | Size | Where it lives |
| --- | --- | --- |
| The scans | 6.4 GiB | Drive; locally under `data/`, gitignored |
| Test fixtures | a handful of cards | `tests/fixtures/`, committed |
| The benchmark set | 15–20 cards plus ground truth | Drive — see IT-37 |

### Secrets

API keys are never committed. Local configuration goes in `.env`, which is
gitignored. `.env.example` lists every variable that exists, with the values
left blank — copy it and fill yours in:

```bash
cp .env.example .env
```

If you add a variable, add it to `.env.example` in the same PR with a blank
value. That file is the only record of what configuration the project expects,
so a variable missing from it is a variable the next person won't know to set.

CI scans every pull request for committed secrets. That is detection, not
prevention — it catches a key once it is already pushed to a branch, so treat
any key that gets that far as compromised and rotate it, rather than deleting it
in a follow-up commit.

Why the scans live in Drive, and why secret scanning works this way:
[docs/decisions/D004-data-storage-and-secret-scanning.md](docs/decisions/D004-data-storage-and-secret-scanning.md).

## Running

Run anything through `uv run` so it uses the pinned environment:

```bash
uv run pytest                                  # tests
uv run ruff check .                            # lint
uv run python benchmark/run_benchmark.py --help  # calibration harness
```

### Running the tests

CI runs gitleaks, `ruff check .`, `ruff format --check .` and pytest with
coverage on every PR. To run the same checks locally:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest --cov=survey --cov-branch --cov-report=term-missing
```

The coverage table lists, per module, the share of lines and branches the
tests run and the line numbers they miss. In CI it also appears on the
run's Summary page. It is reported, not enforced.

The reviewer UI has two more layers, both in CI. `npm test` runs the Vitest
suite against a fake API. `npm run e2e` builds the page and runs Playwright in
Chromium against the real backend, each test on its own synthetic demo and
server: the correct/undo/share/reload journey, a lost save response, two
reviewers on one field, a missing scan, a failed share and a lost session.

```bash
cd frontend
npm ci
npx playwright install chromium   # once
npm test
npm run e2e
```

Some tests skip on purpose, and pytest lists them as `s`:

| Test | Skips unless |
|---|---|
| `test_survey_front_fixtures.py::test_extraction_matches_ground_truth` (one per fixture front) | `GEMINI_API_KEY` is set: it makes live Gemini calls |
| the three calibration tests in `test_confidence.py`, and `test_benchmark_pages.py` | the benchmark set is synced to `data/benchmark/` from Drive |

A skip is not a failure; CI has neither the key nor the data. A failing test
prints the assertion and the values it compared. If you can't fix it in your
own PR, raise a Linear issue with the `Bug` label, the test name and that
output (see the bug process in the Test Plan).

If `uv sync --locked` fails in CI, `pyproject.toml` and `uv.lock` have
drifted: run `uv sync` and commit both. If gitleaks fails, a key reached a
commit. Rotate the key, because deleting it from the branch is not enough (D004).

### Extracting a new batch of scans

Each folder of the archive is one region (D027). Set `GEMINI_API_KEY` in
`.env` and point the command at the folder:

```bash
uv run survey extract data/Wilfred_Prest_Survey_Data/216429
```

The region is named after the folder (`216429`); pass `--region <name>` to
name it yourself (lowercase letters, digits, `-`, `_`). A region's run only
touches `results/<region>.jsonl` and `data/runs/<region>/`, and it refuses a
results file holding another region's records. Run one folder under one name
only: the same scans under two names end up in two files.

There is no separate export step: this one command reads the scans and writes
the region's results file. In order, it:

1. Splits every PDF into pages and sorts the pages into cards. A page that
   isn't a recognised card, or a PDF that can't be opened, is logged and
   skipped; the rest of the batch carries on.
2. Has Gemini read each coding card and scores every field, and read each
   survey front (address, persons), at one more request per front. A front
   with no meaningful handwritten fields or persons can be probed as a coding
   card. A plausible coding ID alone cannot discard existing front data.
   Scan-verified classifications load from `docs/runs/it123-verified-coding.json`
   by default; `--verified-coding` supplies an alternative registry.
   A coding card whose reading gives no usable record_id has its identity
   block read again from a crop, at one more request. Each reading is cached
   in `data/runs/<region>/<extractor>/`
   (gitignored), so no card is paid for twice.
3. Groups the cards into dwellings by scan order and dwelling number (IT-105).
   A front with no number (blank, or its reading was unusable) takes the
   dwelling number of the coding card after it; if an earlier run read that
   front, its previous reading is kept. A dwelling with a card whose request
   failed is not rebuilt, so its previous version (if any) is kept, and the
   card is read again next run. The exception is an extra front with no coding
   card after it: if its request fails, the dwelling before it is written
   without it. A coding card whose number fits no front pairs with the front
   at the batch's usual page offset only when the dwelling numbers are within
   one digit edit (lettered dwellings must agree), flagged `paired_by_position`. One that
   still fits none, or whose identity doesn't check out, is still written,
   with `dwelling.flags` saying why and `record_id` null if it can't be
   trusted (D007). An identity completed by the second reading is flagged
   `identity_reread`. A coding card with no value at all is skipped.
4. Checks every record against `schema/record-envelope.schema.json`. One that
   fails is logged with its record_id and the failing field, and not written,
   so its previous version (if any) is kept.
5. Merges the records into `results/<region>.jsonl`, one D007 record per
   dwelling (its households nested inside), in scan order. Set `SURVEY_OUTPUT_DIR` to write somewhere else.
   A zero-record region is reported without publishing an empty JSONL file.
6. Logs a summary line: records written, pages skipped, cards unreadable,
   cards unplaced, cards failed, PDFs failed, records invalid. The command
   exits 1 if any card, PDF or record failed, so a scheduled run can tell.

`results/` is committed (D025): committing the file is how the client gets
the data and how reviewers' corrections come back.

**Rerunning is safe.** Records are matched to their previous version by scan
and page (D026): no duplicates, a record the run didn't rebuild (or rebuilt
only in part) is kept, and a field a reviewer corrected is never overwritten. Once review has started,
rerun on the branch holding the reviewed file.

| Run | What it does |
|---|---|
| the same command | Replays cards already read on this machine, so only new or unfinished ones cost a request. Use it after an interruption, the daily cap, or new scans landing in the folder. On another machine every card is read again. |
| the same command with `--fresh` | Moves the cached readings aside to `data/runs/<region>/<extractor>.previous/` and reads every card again. Use it after changing a prompt or `GEMINI_MEDIA_RESOLUTION`, which a normal rerun would not pick up. If it is cut short, rerun **without** `--fresh` to carry on; repeating `--fresh` starts over. |
| the same command with `--notes` | Also reads each survey back's interview notes (FR-05) into `dwelling.notes`, at one more request per back. Off by default; a run without it keeps the notes an earlier run read. |

Changing `GEMINI_MODEL`, `GEMINI_CONFIDENCE_BAND` or `GEMINI_STRUCK_DETECTION`
starts a fresh cache by itself. A card Gemini couldn't read is cached too and
not sent again, and fails every run; delete its file,
`data/runs/<region>/<extractor>/<pdf>_pNNNN.json` (or use `--fresh`), to retry
it.

**When a run stops early.** After 3 cards fail in a row (the daily cap, or an
outage) the run stops and writes what it has; rerun later to carry on. A run
that can't merge safely stops with an error naming the line or page, and writes
nothing. A damaged or schema-invalid results file is caught before any card is
read. A reviewed record that no longer lines up with its scan, or that fails
the schema once its corrections are applied (say, a corrected dwelling number
that makes an invalid record_id), is caught after reading; the readings are
cached, so fixing the correction and rerunning costs nothing.

**Assumption:** new batches use the same printed forms as the cards already
measured (coding cards C1/C2). A batch on a different form would still run, but
the field schema and the confidence numbers were calibrated on these forms
only, so its output can't be trusted without a new benchmark.

Reading survey fronts roughly doubles a run's requests (IT-123: about 2.6 to 5
days on 5 keys). A rerun that reads a front differently (an overflow front
joining two dwellings) regroups that dwelling, and a run that would move a
reviewer's correction that way stops instead.

### Building the review queue

```bash
uv run survey flags results > flags.jsonl
```

One line per coding-card field that needs review (D022), in the format
`survey review --flags` reads: least sure card first, each card's fields in
form order. Accepted and corrected fields are left out. Takes files or
folders; each file must be named after its region (`216412.jsonl`). A
household it can't flag is reported and skipped, and the command exits 1.
Skipped-card diagnostics go to stderr. Duplicate card ownership must still be
repaired in the source records before launching the review tool: its backend
rejects ambiguous datasets even when the flags file contains only valid cards.
Regenerate the flags after repairing the records.

For handover, generate from the matching review-data checkout's `results`
directory and retain the flags file across launches. Decisions and audit history
are saved in regional records; flags define a stable assignment and are not
rewritten as work completes. See [the review runbook](docs/review-backend.md#generate-and-retain-a-review-assignment)
for preparation, regeneration and integration-test instructions.

### Merge the two saved runs (IT-125, offline)

**19 October status:** PRs #63/#64 and Jacob’s refreshed 216436 raw
handoff are integrated. The local publication is `results/<region>.jsonl`:
5,375 dwellings / 5,430 coding sources across 44 nonempty regions; front-only
216461 accounts for the 45th region. All 34 protected field payloads are
preserved. Every stored card has a numeric score; uncalibrated fronts/backs
use zero as a no-evidence marker and supplementary handwriting stays as-is.
See [the integration evidence](docs/runs/it125-216436-integration.md).

The independent Qwen export stays in
`results/qwen2.5-vl-server-2000000px/`. The [merge report](docs/runs/it125-merge-report.md)
contains per-region agreement, review eligibility, calibration limitations and
known C3/S3/R1 sample counts. Unsupported forms are outside the agreed scored
scope; these counts do not claim full-corpus prevalence. Review queue behaviour
and handwriting priority belong to IT-109/IT-115.

```bash
uv run python scripts/merge_scored_results.py \
  --primary data/it125-inputs-after216436/results \
  --qwen-cache data/it125-closeout-20261019/qwen-cache \
  --output data/it125-new-candidate
uv run survey validate-results data/it125-new-candidate
uv run python scripts/report_scored_results.py \
  --dataset data/it125-new-candidate --output data/it125-new-report
```

The primary snapshot includes the source-verified Gemini additions. The isolated
Qwen cache tree uses the fresh 216436 handoff for that entire region and the
original handoff for the other regions; extracting the replacement over old
caches is unsafe. Both original archives and the original Gemini snapshot are
preserved. The completed candidate, pairing audit and repeat build are in
`data/it125-closeout-20261019/`. Optional report `--runtime` and `--evidence`
arguments attach measured runtime and candidate-specific verification; report
generation never invents validation or publication evidence.

The output must be separate from all inputs and new or empty. `--primary` can
also name a reviewed Gemini dataset: human decisions and their full payloads
are preserved. Raw caches are required for every published source; no model
clients are constructed. A missing or incompatible configuration refuses the
merge. The supplied archive was safety-checked and matched to the separate
extraction above; `--qwen-cache` can point to another safely extracted copy.
Pairing evidence remains beside the candidate in `pairing/`, outside Git.
Original inputs and caches are unchanged. A normal single-extractor rerun does
not recreate paired confidence; run this offline merge again after extraction.

## Technical documentation

| Guide | Covers |
| --- | --- |
| [Review runbook](docs/review-backend.md) | Configuration, launch, assignments, saving, Git sharing and recovery |
| [Frontend guide](docs/reviewer-ui.md) | Building the React interface and running frontend/browser tests |
| [Card relinking guide](docs/review-relinking.md) | Per-card ownership, identity fixes, comparing/linking cards, retained evidence and Undo |
| [Windows installation and operator checklist](docs/review-windows-acceptance.md) | Building a reviewer package, Windows setup and operator checks |
| [Record schema guide](docs/decisions/D007-output-record-schema.md) | Output structure, field metadata and relationships |
| [Review persistence decision](docs/decisions/D029-review-persistence.md) | JSONL storage and sharing through the data branch |
| [Decision records](docs/decisions/README.md) | Technical decisions and historical audit notes |
| [Third-party licences and notices](THIRD_PARTY_NOTICES.md) | Dependency licences, fonts, optional model tools and external service terms |

## Contributing

One branch per Linear issue, one PR per branch, reviewed by someone else.

- **Branches:** use the name Linear generates, don't invent your own. Open the
  issue in Linear and press `Cmd/Ctrl + Shift + .` to copy it, or grab it from
  the issue's context menu. The shape is `<name>/it-<number>-<slug>`, e.g.
  `skandar/it-21-repository-setup-and-structure`. Using Linear's name is what
  makes the branch, the PR and the issue link to each other automatically —
  which is how individual contribution gets evidenced for assessment.

- **Commits:** `<scope>: IT-<number>: <what the commit does>`

  ```
  repo: IT-33: add GitHub Actions workflow running Ruff and pytest
  ```

  Scope is `repo` for tooling, config and docs; use `src`, `tests`, or a module
  name once there's code to name. Write the description in the imperative
  ("add", not "added"), lowercase, no full stop. One logical change per commit —
  a reviewer should be able to read the subject lines and know what happened
  without opening the diff. The issue number in every commit is what ties the
  work back to Linear even when a branch outlives its PR.

- **`main` is protected.** Direct pushes are rejected by a repository ruleset:

  ```
  remote: - Changes must be made through a pull request.
  ```

  That is expected, not a broken setup. Branch, push, open a PR.

- **Pull requests:** at least one approving review before merge — no
  self-merges, including by the repo owner. Keep them small, and put the Linear
  issue in the title (e.g. "IT-29: add PR template"). The PR template asks what
  changed, which issue, and how you tested it; fill it in rather than deleting
  it.

- **Closing the ticket is yours.** Merging a PR moves its Linear issue to Done
  automatically, so whoever merges is the one closing it — don't merge someone
  else's work for them. Tickets with no PR, like documents and spikes, get moved
  by their assignee.

- **Definition of Done:** before you call anything done, check it against the
  [Definition of Done](https://linear.app/um-it-project/document/definition-of-done-0fce56ee35d6).

## Project management

Work is tracked in [Linear](https://linear.app/um-it-project).

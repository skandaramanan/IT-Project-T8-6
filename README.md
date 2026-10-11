# IT-Project-T8-6

Wilfred Prest Survey IT Project — Team 8/6.

## What this is

A data project analysing the Wilfred Prest survey for our client, The University of Melbourne Archives Team.
The goal is to turn the raw survey responses into clean, analysable data and
findings the client can use.

## Layout

- `backend/survey/` — the pipeline, installed as the `survey` package
- `benchmark/` — calibration harness; imports `survey`, never the reverse
- `schema/` — the output record schema the pipeline, tests and review tool share
- `results/` — the extracted dataset, one `<region>.jsonl` per region (committed)
- `tests/` — tests
- `docs/` — decision records and assets
- `data/` — scans, raw model responses, benchmark set (gitignored)

Why it's laid out this way:
[docs/decisions/D024-repository-layout.md](docs/decisions/D024-repository-layout.md).

## Setup

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

That is the whole setup. `uv sync` creates the virtualenv and installs
everything from `uv.lock`. You do not need to install Python yourself — the
version is pinned in `.python-version` and uv fetches it for you. The first
sync downloads Python and the packages, so give it a minute; later ones are
near-instant.

Don't activate the venv by hand and don't `pip install` into it — that change
would exist only on your machine. Run things with `uv run`, and add
dependencies with `uv add <package>`, which updates `pyproject.toml` and
`uv.lock` together so everyone gets them.

Why uv, and why Python 3.12:
[docs/decisions/D001-dependency-manager.md](docs/decisions/D001-dependency-manager.md).

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
   survey front (address, persons), at one more request per front. Each
   reading is cached in `data/runs/<region>/<extractor>/`
   (gitignored), so no card is paid for twice.
3. Groups the cards into dwellings by scan order and dwelling number (IT-105).
   A front with no number (blank, or its reading was unusable) takes the
   dwelling number of the coding card after it; if an earlier run read that
   front, its previous reading is kept. A dwelling with a card whose request
   failed is not rebuilt, so its previous version (if any) is kept, and the
   card is read again next run. The exception is an extra front with no coding
   card after it: if its request fails, the dwelling before it is written
   without it.
4. Checks every record against `schema/record-envelope.schema.json`. One that
   fails is logged with its record_id and the failing field, and not written,
   so its previous version (if any) is kept.
5. Merges the records into `results/<region>.jsonl`, one D007 record per
   dwelling (its households nested inside), in scan order. Set `SURVEY_OUTPUT_DIR` to write somewhere else.
6. Logs a summary line: records written, pages skipped, cards unreadable,
   cards unplaced, cards failed, PDFs failed, records invalid. The command
   exits 1 if any card, PDF or record failed, or a coding card fit no
   dwelling, so a scheduled run can tell.

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

Work is tracked in Linear: https://linear.app/um-it-project

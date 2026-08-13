# IT-Project-T8-6

Wilfred Prest Survey IT Project — Team 8/6.

## What this is

A data project analysing the Wilfred Prest survey for our client, Wilfred Prest.
The goal is to turn the raw survey responses into clean, analysable data and
findings the client can use.

## Layout

- `src/` — application code
- `tests/` — tests
- `docs/` — documentation
- `data/` — datasets (gitignored; keep raw data out of version control)

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
committed, including anything you derive from it.

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

## Running

No runnable entry point yet — code lands under `src/`. Run anything through
`uv run` so it uses the pinned environment:

```bash
uv run pytest         # tests (none yet)
uv run ruff check .   # lint
```

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

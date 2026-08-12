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

Survey data is not committed. Put local datasets under `data/` (gitignored).

## Running

No runnable entry point yet — code lands under `src/`. Run anything through
`uv run` so it uses the pinned environment:

```bash
uv run pytest         # tests (none yet)
uv run ruff check .   # lint
```

## Contributing

- **Branches:** one per Linear issue, using the name Linear generates —
  `<name>/it-<number>-<slug>` (e.g. `skandar/it-21-repository-setup-and-structure`).
  Don't commit directly to `main`.
- **Pull requests:** every PR needs at least one review approval before merge.
  Keep PRs small and reference the Linear issue (e.g. "IT-21") in the title.

## Project management

Work is tracked in Linear: https://linear.app/um-it-project

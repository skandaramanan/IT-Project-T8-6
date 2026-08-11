# D001 — Dependency manager and Python version

**Status:** Accepted
**Date:** 2026-08-11
**Decided by:** Skanda Ramanan (P1 Foundations lead)
**Linear issue:** IT-25

## Context

Five people will be running this pipeline on their own machines for a semester.
The work involves PDF and image handling, and later either a hosted vision model
or a local open-source one — the model choice is still open (see the token/cost
risk in the Risk Register). Those libraries are exactly where version drift
between machines produces bugs that appear on one laptop and nowhere else, and
they surface late.

We need one dependency manager, one Python version, and a lockfile, so that any
member on a clean machine gets the same environment from one command.

## Decision

**Use `uv`, with Python pinned to 3.12** (`>=3.12,<3.13`).

Setup is a single command: `uv sync`.

## Alternatives considered

### uv — chosen

- Manages the Python interpreter itself (`.python-version` + auto-install), so
  the Python version is pinned by the repo rather than by whatever each person
  happens to have installed. Poetry and pip-tools both assume you already have
  the right interpreter.
- Setup is one command. Poetry needs Poetry installed first, then an env
  selection, then install; pip-tools needs venv creation, activation, then sync.
- `uv.lock` resolves across platforms in a single file. Our team is on a mix of
  macOS and Windows.
- Fast resolution on the heavy image/ML dependencies we expect to add.
- Uses a standard `pyproject.toml`, so moving to Poetry or plain pip later costs
  nothing structural.

Against it: it is the newest of the three, so there is less material online when
something goes wrong, and some of us will not have used it before. The one
command and this record are the mitigation.

### Poetry — rejected

Mature and widely known, but does not manage the Python version, so the largest
source of drift stays unsolved. Multi-step setup, and dependency resolution is
noticeably slow on the kind of libraries this project will pull in.

### pip-tools — rejected

Closest to plain pip and the easiest to explain, but the compiled
`requirements.txt` is platform-specific, which is a real hazard for a mixed
macOS/Windows team and one that fails quietly. Also leaves both the Python
version and the venv as manual steps.

## Why Python 3.12

3.13 still has patchier wheel coverage across the PDF and vision libraries we
are likely to need. 3.11 and below give up recent typing improvements for no
gain here. 3.12 has broad wheel support and is comfortably supported upstream.
Pinned below 3.13 so nobody drifts upward mid-semester.

## Consequences

- Everyone installs `uv` once; after that, setup and dependency changes are
  `uv sync` and `uv add`.
- `pyproject.toml`, `.python-version` and `uv.lock` are committed. The lockfile
  is not gitignored — it is the point.
- Runtime dependencies are deliberately not pre-loaded. Nothing is built yet and
  the extraction approach is not settled, so libraries land with the code that
  needs them. Only a dev group (test runner, linter) is included up front.
- When the hosted-vs-local model question resolves, the heavy local-model
  dependencies go in as an optional extra, so only members testing that path
  install them.

## Revisit if

Setup breaks repeatedly on someone's machine, or `uv` blocks a library we need.
Moving to Poetry or pip-tools from a standard `pyproject.toml` is cheap.

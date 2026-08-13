# D003 — Automated checks on every pull request

**Status:** Accepted — amended by [D004](D004-data-storage-and-secret-scanning.md)
**Date:** 2026-08-12
**Decided by:** Skanda Ramanan (P1 Foundations lead)
**Linear issue:** IT-33

## Context

D002 made review mandatory, but a reviewer should not be the thing that catches
formatting and broken tests. We also needed somewhere for tests to live before
there is anything to test.

## Decision

One GitHub Actions workflow on pull requests and pushes to `main`, running
`uv sync --locked`, `ruff check`, `ruff format --check`, then `pytest`. The job
is called `check` and is a required status check on the `main` ruleset.

**Amended by [D004](D004-data-storage-and-secret-scanning.md), 2026-08-13.** The
same `check` job now runs a gitleaks secret scan as its first step, and checkout
is full-depth so that scan can read commit history. Everything above still
holds — one job, one required status check — and D004 explains why the scan went
inside `check` rather than beside it.

## Alternatives considered

**Ruff over Black + flake8 + isort** — one tool covers lint and formatting, so
there is one config and one failure mode instead of three.

**A Python version matrix** — pointless. D001 pins the interpreter, and uv reads
`.python-version`, so the workflow needs no version input at all and the pin
lives in exactly one place.

**Pre-commit hooks instead of CI** — hooks are skippable and run on the machine
of whoever remembers to install them. CI is not optional.

**Coverage thresholds** — deferred. There is no code to cover, and a threshold
on an empty repo is theatre.

## Consequences

- A red check blocks merge, on top of the review requirement.
- `uv sync --locked` fails the build if `pyproject.toml` and `uv.lock` drift
  apart, which keeps D001 honest.
- Runs cost about 15 seconds, so the feedback is fast enough to trust.

## Revisit if

The extraction work needs heavier test dependencies or fixtures large enough
that a plain checkout stops being cheap.

Partly reached already: IT-36 added 7.2 MB of fixtures and D004 made checkout
full-depth. Runs are still about 15 seconds, so the single-job shape holds.
Revisit properly if CI starts costing a minute or more, or if `tests/fixtures/`
grows past a handful of records — at which point the fixtures likely belong in
shared storage with the benchmark set instead of in git.

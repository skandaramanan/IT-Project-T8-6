# D003 — Automated checks on every pull request

**Status:** Accepted
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

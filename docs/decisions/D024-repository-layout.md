# D024 — Repository layout: one installable package

**Status:** Accepted
**Date:** 2026-10-04
**Decided by:** Qitao Shi (IT-126 assignee)
**Linear issue:** IT-126

## Context

The code sat in two halves that could not import each other cleanly. `src/`
held application code but was not an installed package. `spike/` held about
half the production pipeline — the Gemini and Qwen extractors, response
parsing, confidence scoring, PDF page export — next to benchmark-only code.

Imports worked only through workarounds: `pythonpath = ["src", "spike"]` in
pytest, `sys.path` edits at the top of four scripts and the Colab notebook,
and copies where an import was impossible (D016's `0.97` in the IT-108 PR,
`normalise` in both `src/extraction/record.py` and `spike/scoring.py`).

## Decision

```
backend/survey/   the pipeline, installed through uv_build (package = true)
benchmark/        calibration harness; imports survey, never imported by it
frontend/         reserved for the review UI (created by its first ticket)
schema/           the output record schema — single source of truth
results/          the committed dataset (D025)
tests/  docs/  data/
```

- `pyproject.toml` builds with `uv_build`, `module-name = "survey"`,
  `module-root = "backend"`. `uv sync` installs it editable.
- `benchmark/` is the only path pytest adds, because the harness tests need it.
  `tests/test_layout.py` fails if anything under `backend/survey/` imports a
  harness module.
- Production code lives in `backend/survey/`. `benchmark/` may import it,
  never the reverse.

This replaces the "Application, not a library" reasoning that kept
`package = false`. Installing the package isn't publishing it: it is what makes
imports, a `survey` console command (IT-120) and Windows support work without
path edits.

## Alternatives considered

**Keep `src/` as the folder name.** Rejected: once `frontend/` exists, `src/`
no longer says which half it holds.

**Keep `spike/` and import across it.** Rejected: that is the workaround this
replaces, and it left production code under a name that says "throwaway".

## Consequences

- Imports are `survey.extraction.x`, `survey.confidence.x`, and so on.
- `extraction/field_schema.py` is renamed `card_fields.py`, closing D007's
  open "two artifacts carry the word schema" consequence.
- The agreement classes, `classify()` and `compare_fields()` moved out of
  `dual_extract.py` into `survey/confidence/agreement.py`, which also removed
  the circular import `pair_cards` used to dodge.
- The Colab notebook installs the package (`pip install -e .`) instead of
  editing `sys.path`.
- Open PRs written against `src/`/`spike/` rebase onto the new paths.

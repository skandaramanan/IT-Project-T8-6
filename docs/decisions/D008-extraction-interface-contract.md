# D008 — Extraction interface and result contract

**Status:** Accepted
**Date:** 2026-08-20
**Decided by:** Jacob Ng (Architect Lead)
**Linear issue:** IT-79

## Context

The same `Extractor.extract()` call runs in both the IT-37 spike comparison
and the production pipeline once IT-46 picks an engine — one interface, not
a spike version and a later production one. That is why it lives in
`backend/survey/extraction/` rather than inside the IT-37 spike harness.

D007 (IT-39) requires per-field confidence in the final output (FR-10,
nullable), naming "a conversion step between the `Extractor` interface and
the output" as where it comes from. This record defines that interface.

## Decision

**`Extractor` Protocol:**

```python
class Extractor(Protocol):
    name: str

    def is_available(self) -> bool: ...
    def extract(self, image_path: Path) -> ExtractionResult: ...
```

**`ExtractionResult`:**

```python
@dataclass
class ExtractionResult:
    fields: dict[str, str] = field(default_factory=dict)
    raw_text: str | None = None
    confidence: dict[str, float] | None = None
```

- `fields` defaults to `{}`, never `None` — a card the model fails on scores
  as an empty dict, not a different output shape.
- `raw_text` is diagnostic only: what the model said, never scored.
- `confidence` is optional, `None` when not known or not supported by the
  engine, and keyed the same as `fields`.
- `is_available()` lets a runner skip an engine with a missing dependency or
  API key, rather than crash mid-run.

## Alternatives considered

**`None` on failure instead of `fields={}`.** Rejected — forces every caller
(benchmark scorer, review UI) to branch on a different output shape
depending on whether the call failed, instead of always reading a dict.

**Raising an exception when a dependency/API key is missing.** Rejected —
`is_available()` lets the runner skip an engine before calling `extract()`,
rather than wrapping every call in a try/except.

**Scoring `raw_text`.** Rejected — not comparable in shape across engines (a
VLM's JSON blob vs. a local OCR's plain string). Only `fields` is scored
against ground truth.

**Deferring `confidence` to a later ticket.** Considered, since IT-46 hasn't
picked an engine yet. Rejected once D007 was checked: FR-10 is a firm client
requirement, not a speculative one, and D007 already assumes this interface
is where it comes from. Adding it now avoids a second retrofit once IT-46
lands.

## Consequences

- Every IT-37 candidate extractor, and the production engine IT-46
  eventually selects, returns `ExtractionResult` — not a raw string or dict.
- `code_book.py` and `card_fields.py` (also IT-79) layer on top of `fields`
  to interpret values; neither is part of this interface.
- Whichever engine can't produce a per-field score leaves `confidence=None`
  for those fields rather than a fabricated `1.0`.

## Revisit if

A candidate engine's natural output doesn't fit this shape (e.g. structured
per-field alternatives/candidates) — extend the contract, don't break it.

Also revisit if the Archives team confirms region- or era-specific coding
schemes exist. Municipality `56` alone is 19 of 20 cards in the IT-79
benchmark sample and isn't in the one reference sheet we have (raised on the
Encoding References doc, IT-77). `code_book.py`/`card_fields.py` currently
assume a single universal scheme: `CLOSED_CATEGORIES`/`SENTINEL_CODES` are
flat module dicts, and `FieldSpec.code_book_category` is a plain string key
into them — no batch/region/era axis anywhere. If confirmed, the seam is a
`CodeBook` container bundling both tables, with `FieldSpec` gaining an
optional `code_book: CodeBook` field (defaulting to today's tables so
nothing else changes). Not built speculatively — we don't yet know if this
batch is missing a supplementary sheet (no code change needed) or is
genuinely on a different scheme (needs the above).

# D006 — Source provenance

**Status:** Accepted
**Date:** 2026-09-03
**Decided by:** Qitao Shi (IT-72 assignee)
**Linear issue:** IT-72

## Context

NFR-06 asks that an extracted value can be traced back to the scan it came
from. The client's wording in FR-16 is stronger than a nice-to-have: they are
format-agnostic "provided every card property can be traced to an output
property". An archivist who does not believe a number has to be able to find
the paper.

This record is written after the fact. D007 already cites D006 as settled —
"already settled against in D006 — source-card references on traceability-
relevant values, not coordinates on every field" — and
`docs/schema/record-envelope.schema.json` carries the `source` key with the
same citation. The decision was made and encoded; the record was never
written. So this fixes a dangling reference as much as it decides anything,
and it deliberately restates what the schema already does rather than
reopening it.

One thing worth separating first, because it is the obvious objection. The
record is already identified by municipality, dwelling number and household
number (D007's `record_id`). That is not provenance. Those values are read
*off* the card by the same extractor whose output is in doubt: if the
municipality was misread, the identity that would let you find the card is
itself wrong, and the check is circular. Provenance has to be something the
pipeline knows for certain from ingest — which file, which page — not
something it inferred from handwriting.

## Decision

**A card-role reference on traceability-relevant values, resolved through a
card list that carries the scan path.**

Two parts, both already in the envelope.

### `source` on the field

```json
"address": {
  "value": "164 Hall St, Spotswood",
  "status": "ok",
  "confidence": 0.71,
  "source": "survey-front"
}
```

`source` is a card *role*: `survey-front`, `survey-back`, `coding-front`,
`coding-back`, `secondary`.

### `cards` on the dwelling or household

```json
"cards": [
  { "role": "survey-front", "image": "tests/fixtures/r01-survey-front.jpg", "page": 1, "confidence": 0.74 },
  { "role": "coding-front", "image": "tests/fixtures/r01-coding-front.jpg", "page": 3, "confidence": 0.88 }
]
```

`image` and `page` come from ingest and segmentation (FR-19), not from
reading the card. The chain is value → role → card entry → scan file and
page. Card-level confidence (FR-20) lives here too, alongside the image,
rather than being duplicated onto every field.

### How a role resolves to a card

Cards attach to the **household**, not the dwelling. The survey front is
physically part of a household's set, and on the common one-household dwelling
there is nowhere else to put it — which is why `r01`'s four cards sit under
`households[0]` and `dwelling.cards` is empty.

So resolution is scoped, not a flat lookup:

- a **dwelling-level** `source` resolves against the dwelling's own `cards`
  plus those of every household under it — it looks *down*;
- a **household-level** `source` resolves against its own `cards` plus the
  dwelling's — it looks *up* and at itself, never sideways into a sibling
  household.

`dwelling.cards` stays in the envelope for the case where a card genuinely
spans households — a survey front listing three families is one sheet, not
three. `tests/test_output_schema.py` enforces both scopes.

### Which values are "traceability-relevant"

**Those whose card of origin is not already implied by where they sit in the
record.** In practice that is the values a dwelling can receive from more
than one card:

| Carries `source` | Why |
| --- | --- |
| `municipality`, `dwelling_no`, `address`, `families_in_dwelling` | Dwelling identity appears on both the survey front and the coding card, and the two can disagree |
| `household_no` | Same, and it is half of `record_id` |
| `persons[].*` | From the survey front's column grid, but the head's attributes also appear on the coding card |
| `notes.source` | FR-05 notes are on the survey back, but the back is also where overflow from the front lands |

Everything under `house`, `head`, `counts` and `coding` omits it. Those
branches are defined by D007 as coding-card content; a `source` on each would
be the same string 60 times, and a constant repeated 60 times is not
information. `source` is optional in the schema, and its **absence means
"implied by the branch", not "unknown"**. A value whose origin is genuinely
uncertain is a `status` problem (FR-09), not a provenance one.

## Alternatives considered

**Bounding-box coordinates on every field.** The strongest form: click a value
and the reviewer sees the exact cell on the scan highlighted. Rejected for
now. It ties the output schema to whichever extractor IT-46 picks — Azure
Document Intelligence returns polygons, a raw-OCR path may return nothing
usable — and NFR-06 asks for traceability to the *card*, which the role
reference already gives. It is also not free to store: four coordinate pairs
per field across roughly 60 fields and 6,000 cards is more provenance than
data. Left open below; it is additive if the client asks for it.

**A card identifier or filename on every field**, rather than a role resolved
through `cards`. Rejected: it repeats the same path on every leaf, and the
path is the thing most likely to change — fixtures live in `tests/fixtures/`,
the corpus lives in Drive, and a re-export could move either. One place to
update beats sixty.

**Provenance on every field, including the coding-card branches.** Rejected as
above, and explicitly out of scope in IT-72: "excludes provenance metadata for
every field".

**A separate provenance sidecar file**, keyed by `record_id`. Rejected for the
same reason D007 rejected a parallel confidence map: two files drift the
moment something writes to one and not the other, and a record that has to be
joined to be trusted will be read untrusted.

**Nothing — rely on `record_id`.** The circularity argued in Context. It also
fails outright on a damaged or illegible card, which is exactly the record a
reviewer most wants to open the scan for.

## Consequences

- Every value that could have come from more than one card says which one, and
  the scan is one lookup away. That is NFR-06 satisfied at the level FR-16
  asks for.
- **The reference is to a card role, not a specific card.** If a dwelling ever
  holds two cards with the same role — a second coding front, a re-take, a
  page scanned twice — `"source": "coding-front"` no longer resolves to one
  entry in `cards`. The five fixtures do not show this and the four-page cycle
  in `tests/fixtures/README.md` argues against it, but the corpus has not been
  swept. IT-73's FR-21 spike is where that would surface.
- Because a dwelling-level `source` resolves by looking down, it is unambiguous
  only while no two households under that dwelling hold cards of the same role.
  A three-family dwelling has three coding fronts, and `"source":
  "coding-front"` on the dwelling's own `address` would match all three. The
  same limit as above, reached one level higher, and the same fix — card ids —
  if IT-73 says it is worth paying for.
- `image` is a path, and paths are only as stable as the storage under them.
  Fixture paths are repo-relative and CI-checkable; corpus paths will be
  relative to the Drive layout D004 set up, and a reorganisation there breaks
  every exported reference. `batch` and `page` on the envelope are the
  durable fallback: the source PDF and the page number inside it survive a
  move.
- Provenance is only as honest as segmentation. If FR-19 mis-sorts a page, the
  role is confidently wrong rather than absent, and a wrong pointer is worse
  than no pointer. Card-level `confidence` on the `cards` entry is where that
  doubt belongs.
- The output-property mapping that FR-16 finally reports against is still
  IT-66/IT-67's, not this record's — IT-72 excludes it.

## Revisit if

IT-73 finds cards that break the one-per-role assumption, in which case
`cards` entries need an id and `source` starts referencing it instead of the
role. Or the client asks to see *where* on the card a value sits, rather than
*which* card — that is the coordinate option above, and it is an addition to
this decision rather than a reversal of it.

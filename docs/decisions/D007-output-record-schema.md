# D007 — Output record schema

**Status:** Accepted, provisional — the envelope is settled, the field set is not
**Date:** 2026-08-22
**Decided by:** Skanda Ramanan (IT-39 assignee)
**Linear issue:** IT-39

## Context

Three tickets in the current cycle stop at the same wall and defer to this one.
IT-70 defines "the extraction-level field contract needed by the extractor,
without deciding the final exported JSON/XML schema". IT-74 associates cards
into household records but excludes "the final JSON/XML representation of
households and individuals". IT-72 records provenance but excludes "final
output-property mapping". Nothing can be exported until the shape those three
feed into exists.

Two questions had to be answered before it could: how individuals and
households intersect, and how confidence is recorded.

The client is format-agnostic "provided every card property can be traced to an
output property" (FR-16), asked for confidence at field level and card level,
and asked that the schema be finalised after reviewing the 1980s transcription's
schema. That transcription is located but access-restricted (IT-38), so the
field set cannot be finalised now. The Sprint 1 notes anticipated this and
allow a placeholder.

This record therefore settles the envelope — nesting, identity, what a field
looks like, how batches are written — and deliberately leaves the field list
open. Downstream work can build against the envelope without waiting on the
client, and adding fields later does not renegotiate the structure.

## Decision

**JSON, one dwelling per record, written as JSON Lines partitioned by region.**

### Three levels, not two

```
dwelling  →  household (family)  →  person
```

The ticket originally proposed nesting individuals directly under households.
The fixtures show that loses a level that matters. Reading `r01`:

- The **survey front** carries the dwelling — address (164 Hall St), municipality
  (Spotswood), "No. of Families in Dwelling", structural material, age, tenure,
  facilities — and a per-person column grid: relationship (Head / Wife /
  Daughter), age, earning status, then occupation, earnings and pre-war blocks
  per column.
- The **coding card** is one per *household*, not per dwelling. It opens with
  "Number of Dwelling" and "Number of Household" as separate fields.
- The coding card holds **no individual records at all** — only head attributes
  (age, sex, occupation, earnings, regularity of work) and demographic counts
  (number under 5, adult F breadwinners, home duties, and so on).

So individuals come from the handwritten front and aggregates come from the
coding card, and both hang off a household that hangs off a dwelling. FR-04
association keys on the dwelling; collapsing it into the household would make
that ticket carry a level the schema does not have.

### Identity is a composite key

```
(municipality, dwelling_no, household_no)
```

Rendered as `record_id`, zero-padded: `27-0006-01`.

Observed on the fixtures — `r01` reads municipality 27, dwelling 6, household 1;
`r03` reads 27, 12, 1. Municipality 27 is Williamstown in the code book, and
Spotswood sits inside it, so the coding card and the survey front for `r01`
agree. "No. of Families in Dwelling" on the survey front states how many
household cards to expect under a dwelling.

Dwelling number alone is **not** unique — it repeats across municipalities. That
partly answers the open question in IT-75, which is currently blocked on the
client; the spike still owns whether the number is reliably *present* and
*legible* across the full corpus, and what the fallback is when it is not.

### Every leaf is a field object, never a bare value

```json
{
  "value": "27",
  "code": "27",
  "label": "Williamstown",
  "status": "ok",
  "confidence": 0.94,
  "origin": "extracted"
}
```

`value` is what was read, as text, so leading zeros on codes like `04` survive.
`code` and `label` carry the code book resolution (FR-07) and are null where no
table applies. The remaining keys each exist because a requirement demands them:

| Key | Requirement |
| --- | --- |
| `confidence` | FR-10 — a score on every extracted field |
| `status` | FR-09 — `ok`, `no_data`, `illegible`, `damaged`, `omitted` |
| `negated` | FR-06 — crossed-out resolved as implicit negation |
| `origin`, `original_value` | NFR-05 — human corrections stay distinguishable from the machine value |
| `source` | NFR-06 / D006 — card reference on traceability-relevant values |

`FieldStatus` has the following meanings:

| Status | Definition |
| --- | --- |
| `ok` | The field was read successfully and contains a usable value. |
| `no_data` | The source field is present but contains no value to extract. |
| `illegible` | The source field contains markings that cannot be read reliably. |
| `damaged` | The source field cannot be read because its source area is damaged or obscured. |
| `omitted` | The expected field was not returned by the extractor. |

Sentinels are **values, not statuses**. `999` in Earnings of Head means "over
£10" and `997` means "refused"; both round-trip as ordinary values with a label,
never as `no_data`. That is FR-08, and it is the one rule most likely to be
broken by a well-meaning simplification.

`confidence` is required but nullable. IT-46 has not yet picked an engine, and
raw-OCR candidates have no per-field score to give. A null means "this engine
cannot say", which is honest; silently writing `1.0` would not be, and NFR-01
forbids presenting an uncertain extraction as certain.

Card-level confidence (FR-20) lives on the `cards` entries alongside the image
reference, not on the fields.

### JSON Lines, partitioned by region

One dwelling per line, one file per region batch. Each line repeats `region` and
`batch` so a record stays self-describing when files are concatenated. This is
what makes FR-02's region partitioning, NFR-04's idempotent re-runs and NFR-07's
mid-batch resumability cheap: a run appends lines, and a resume reads back which
`record_id`s are already present.

### The field set is out of scope here

This record does not enumerate the card's fields. That work is already split
across IT-79 (the coding card's 60 fields, typed against the code book), IT-70
(the extraction-level contract) and IT-66 / IT-67 (export and Archives
alignment). What is fixed here is that whatever those tickets produce is
expressed as field objects at one of the three levels.

`docs/schema/record-envelope.schema.json` encodes the envelope. It accepts any
field *names* and enforces that every one of them is a field object — which
makes FR-10 checkable today without pretending the field list is settled.

## Alternatives considered

**XML.** Stronger schema validation via XSD, and the better answer if a legacy
data standard required it. Rejected: the client confirmed format-agnosticism, so
no standard forces it; nesting a value/confidence/status object per field is
clumsy in XML, either as attribute soup or as a wrapper element per field; it
runs 2–3× the size on a corpus of roughly 6,000 cards; and loading it into
pandas or R for the analysis the client actually wants is a conversion step JSON
does not need. Left available — the envelope maps to XML mechanically if the
Archives ever ask.

**One flat record per card.** What the existing transcriber's spreadsheet does,
and what the IT-37 benchmark reads. Simple, and it round-trips to CSV. Rejected
because it cannot express the dwelling level: a dwelling with three families
becomes three rows whose shared house fields are duplicated three times and can
disagree after correction. The spreadsheet gets away with it by widening into
"Family 2 / Family 3 / Family 4" columns, which caps families at four and leaves
most columns empty on the common one-household dwelling.

**A bare value with a parallel confidence map** (`{"fields": {...}, "confidence":
{...}}`). Half the nesting depth and lighter to read. Rejected: the two maps
drift the moment anything writes to one and not the other, and every consumer
has to remember to check both. Status and correction provenance would need a
third and fourth map.

**Per-field provenance.** Already settled against in D006 — source-card
references on traceability-relevant values, not coordinates on every field.
The `source` key here is that decision, not a reopening of it.

**Finalising the field set now.** Tempting, since IT-79 has already typed 60
fields from the benchmark sample. Rejected: the client explicitly asked for the
schema to follow a review of the 1980s transcription, and those 60 fields come
from a *different* batch layout than the fixture cards — the benchmark sheet has
per-family columns the `00049` fixture cards do not. Locking a field list across
two layouts we have not reconciled would be redone twice.

**A JSON Schema for the envelope, versus prose only.** The schema file is a
dependency (`jsonschema`, dev group only) and a file to keep in step with this
record. Taken anyway: prose cannot fail, and the invariant worth protecting —
that no leaf is ever a bare value — is the one a hurried extractor will break
first. One test now fails if the envelope drifts.

This does **not** satisfy FR-15. That requirement's verification line is "output
validates against agreed schema", and the agreed schema it means is the final
one, which FR-15 itself gates on reviewing the 1980s transcription. FR-15 stays
open until IT-38 unblocks. What the schema file makes checkable today is FR-10 —
a confidence score on every extracted field.

## Consequences

- IT-70, IT-72 and IT-74 can proceed against a fixed structure while the field
  list is still moving.
- `schema_version` starts at `0.1.0` and is in every record. The field set will
  change; consumers need to know which envelope they are reading.
- Every leaf costs six keys instead of one. On roughly 6,000 dwellings this is
  tens of megabytes of JSON rather than a few — irrelevant at this scale, and
  the alternative was losing FR-08, FR-09, FR-10 and NFR-05.
- Anything that writes a bare value fails the schema test. That is the point,
  but it means extractors cannot emit plain dicts of strings; there is a
  conversion step between the `Extractor` interface and the output.
- Two artifacts now carry the word "schema": `src/extraction/field_schema.py`
  (IT-79 — the coding card's input fields, for prompting a VLM) and
  `docs/schema/` (this — the output envelope). They are not the same thing and
  the names should be disambiguated when IT-79 lands.
- `jsonschema` is added to the dev group only, consistent with D001 keeping
  runtime dependencies out until code needs them.

## Open questions

Recorded rather than guessed:

- **Crossed-out versus corrected.** FR-06 reads crossed-out as implicit
  negation, but the red pencil on `r01` and `r03` strikes a value and writes a
  replacement beside it — that is a correction by the original coder, not a
  negation. Both may exist on the same corpus and they need different handling.
  Needs a ruling before FR-06 is implemented.
- **Slashed-out columns** map to `no_data` per the client, "pending final
  confirmation" (FR-09).
- **Nobody has inventoried the survey front's fields.** IT-79 and IT-70 are both
  coding-card only, yet the front is the sole source of person-level records
  that this schema nests. US-03 (IT-54) has no task ticket under it.

## Revisit if

The 1980s transcription becomes available (IT-38) — the client asked for the
schema to follow its structure, and this record was written without it.

Also revisit when IT-46 picks an extraction engine: if the chosen engine cannot
produce a per-field score, FR-10 is unsatisfiable as written and either the
requirement or the nullable `confidence` here has to give.

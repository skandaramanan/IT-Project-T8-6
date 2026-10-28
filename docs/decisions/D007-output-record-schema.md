# D007 — Output record schema

**Status:** Accepted, provisional — the envelope is settled, the field set is not; amended by [D026](D026-rerun-merge-key.md) (reruns merge by coding card)
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

Rendered as `record_id`, zero-padded: `27-0006-01`. A lettered dwelling keeps
its letter, and an identity that can't be trusted is null (0.5.0, below).

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
mid-batch resumability cheap; how a rerun merges with the previous file is
D026.

### The field set is out of scope here

This record does not enumerate the card's fields. That work is already split
across IT-79 (the coding card's 60 fields, typed against the code book), IT-70
(the extraction-level contract) and IT-66 / IT-67 (export and Archives
alignment). What is fixed here is that whatever those tickets produce is
expressed as field objects at one of the three levels.

`schema/record-envelope.schema.json` encodes the envelope. It accepts any
field *names* and enforces that every one of them is a field object — which
makes FR-10 checkable today without pretending the field list is settled.

The dwelling has two field maps for the building: `house`, the coding card's
coded values, and `handwritten`, the survey front's dwelling fields as written.

### Interview notes sit on the dwelling (0.3.0, IT-89)

FR-05's notes are written on the back of the survey front, and the front is one
per dwelling. So `dwelling.notes` is a list with one entry per front's back.
Each entry has the text as a field object, the PDF `page` of the back, the
PDF `front_page` of its front, and a `household_id`.

- `household_id` is the household's `record_id` only when the dwelling has
  exactly one household. When there are several, nothing on the card says
  whose note it is, so it is null and the entry is flagged
  `household_ambiguous`. This is the same call the person grid makes.
- No note is linked to an individual. The back has no columns to link by.
- Two overflow fronts give two entries, in card order, never one joined text.
  `page` tells them apart, since both backs share the `survey-back` role.
- A blank back is `no_data`, the explicit empty FR-05 asks for. A back that
  was not read, or not found, is `omitted`, with `flags` saying why. A
  missing reading must never pass for a blank card.
- No `notes` key at all means the backs were never read: reading them is
  opt-in (`survey extract --notes`), at one Gemini request per back. A run
  without `--notes` keeps the notes an earlier run wrote, and a back that
  fails or is not found on a rerun keeps the text read before.
- A rerun pairs each note with the one before by `front_page`, not `page`:
  every note has a front, but its back can go unfound. A corrected note
  follows its front, and is refused only when that front left the dwelling.

This replaces `household.notes`. That slot held a bare string, which could not
tell a blank back from an unread one, and it sat at the wrong level.

### Every card read is written (0.5.0, IT-123)

A coding card used to be dropped when it had no usable identity. In the
IT-123 run that was 1,595 of the 5,313 cards with any value. Now each is
written, so a reviewer can fix it rather than lose it.

- `record_id` is null when the identity can't be trusted: a part is blank, a
  part is malformed (a struck number read with its replacement, such as
  `276303`), or another household in the batch has the same one. A household
  placed with its front by number keeps a record_id that only cards placed by
  position, or not placed at all, share; they are the likelier misreads.
- A coding card that gives no usable record_id has its identity block read
  again from a crop. That reading may only fill what the first left blank or
  malformed, and must agree with every part the first read has. The
  household is then flagged `identity_reread`: a second machine read can
  still be wrong, and it isn't a correction (NFR-05).
- `dwelling.flags` says why: `identity_reread`, `paired_by_position` (a
  coding card whose number fits no front, paired with the front at the
  batch's usual page offset), `unplaced` (a coding card that still fits no
  front, written as a dwelling of its own), `missing_record_id`,
  `duplicate_record_id` or `municipality_mismatch`, along with the grouping
  flags association already raised, which were only logged before. Absent
  when there is nothing to check.
- A dwelling number can end in a letter, which names another dwelling: 487A
  is `21-0487A-01`, not 487.
- A corrected identity rebuilds `record_id` on the next run. (Superseded by
  0.7.0: `record_id` is never nulled to dedupe; see "Per-card ownership" below.)
- A coding card with no value at all is still skipped: it is a blank page or
  a reverse taken for a card.

This is the fallback IT-75 asked for when the number is missing or illegible.
Anything keyed on `record_id` must expect null.

### Household municipality is retained (0.6.0, IT-123 review)

> Updated by 0.7.0 (below): the `dwelling.municipality` alias and shared
> first-card ownership described here no longer apply.

Every household now carries its own `municipality` field object, including a
blank or malformed reading. `dwelling.municipality` remains the first coding
household's shared alias for compatibility; correcting it changes that
household only. Correct a later household at its own municipality path.
Review history stays on the field that was reviewed, never duplicated onto
the alias. This avoids duplicate audit IDs.

Identity settlement uses each household's actual reading instead of guessing
municipalities or blocking unrelated identities in a region. Versions through
0.5.0 remain readable. A rewrite encountering a legacy null identity whose
municipality was discarded refuses to guess and requests a cache rebuild.
The IT-123 results are rebuilt from cached readings into 0.6.0.

Positional pairing requires usable dwelling numbers within one insertion,
deletion or substitution. Lettered dwellings must agree exactly. Otherwise
the coding card stays `unplaced`, retaining its coding fields and source page.
Empty crop values have no opinion about a valid first reading; explicit
disagreements and incomplete identities still fail the fill.

Automatic front recovery requires no meaningful front fields or persons.
Explicit classifications verified against the original scans can override a
segmentation error using `--verified-coding`; those decisions are auditable
region/PDF/page metadata, not an inference from a plausible record ID.

### Per-card ownership (0.7.0, IT-153)

0.7.0 is the schema everywhere: extraction (`build_record`), association,
merge scoring, published results and the reviewer. The pipeline runs
`relinking.finish_records` on each region before writing (provisional relink for
frontless cards, `household_card_id` on notes, identity flags) and refuses
previous results that are not 0.7.0, telling the operator to run
`scripts/prepare_review_dataset.py` first. Published results are still 0.6.0
today; whoever holds the Gemini cache converts them once with that script (no
model calls). Three cards have no cache (216428 p49, 216460 p378, 216463 p279)
and stay `missing_card_reading`. Every card scores its own
dwelling/house/municipality confidence.

Every household owns its `municipality`, `dwelling_no` and `house` fields,
read from its own physical coding card. The dwelling-level aliases are removed.
A later card's readings come from its own retained primary artifact. If none
exists, they are omitted with null confidence and a `missing_card_reading`
flag, and never copied from another card. Physical identity is the coding
card's region, PDF and page. `record_id` is derived, nullable when incomplete
and nonunique: association no longer nulls a `record_id` that two cards share, and
a repeated identity sets the `duplicate_record_id` household flag on every peer
(matched within the same region and PDF) instead of being rejected. Identity
corrections apply to their own card only and do not "settle" a duplicate; a
blanked household number gives a null `record_id` plus `incomplete_identity`.

Households may also carry `flags`, a `relink` state, `link_history` and
`retained_supplements`. A retained bundle holds the read-only front, notes,
address and person rows of a dwelling whose last coding card moved away.
Notes gain an optional `household_card_id` physical owner. Review events gain
the structural effect and guards Undo checks. See
[review-relinking.md](../review-relinking.md).

A dataset is all 0.6.0 or all 0.7.0. During the transition the reviewer still
serves a fully 0.6.0 dataset and refuses a mixed one.

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
dependency (`jsonschema`, a runtime one since IT-66) and a file to keep in step
with this record. Taken anyway: prose cannot fail, and the invariant worth
protecting — that no leaf is ever a bare value — is the one a hurried extractor
will break first. One test now fails if the envelope drifts.

This does **not** satisfy FR-15. That requirement's verification line is "output
validates against agreed schema", and the agreed schema it means is the final
one, which FR-15 itself gates on reviewing the 1980s transcription. FR-15 stays
open until IT-38 unblocks. What the schema file makes checkable today is FR-10 —
a confidence score on every extracted field. Since IT-66 the pipeline also
validates every record against the envelope before writing it.

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
  the names should be disambiguated when IT-79 lands. *Done in IT-126 (D024):*
  the input fields are now `backend/survey/extraction/card_fields.py` and the
  envelope is `schema/`.
- `jsonschema` was added to the dev group only, consistent with D001 keeping
  runtime dependencies out until code needs them. IT-66 moved it to runtime:
  the pipeline validates each record before it is written.
- Every note routes to review under D022, because its `confidence` is null
  until an engine can score free text. Blank backs (`no_data`) route too.

## Open questions

Recorded rather than guessed:

- **Crossed-out versus corrected**, absent a client ruling, is resolved
  operationally in D023.
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


## Review continuation compatibility (14 October 2026)

The IT-113 validator reconciles review metadata with the inspected IT-123 0.5.0
corpus envelope: nullable/lettered household IDs, corresponding note household IDs
and optional dwelling flags. These shapes apply to 0.5.0 and 0.6.0; older schemas
retain their ID rules. Saves preserve 0.5.0 without down-conversion. Other versions,
including 0.4.0, are upgraded to 0.6.0 on save, retaining each household's municipality.
Current extraction builders use 0.7.0 (per-card ownership, above).
Established survey-front definitions and IT-89 note ownership supply bounded text
review. Text corrections are limited to 10,000 characters and reject NUL;
the same rules validate saved correction history. No person column/page structure or coding-back fields are invented.

Review compatibility check (19 October 2026): the fetched `review-data` head
`752b8093f3c7afc250be93bef39ad62940b75d2c` contains four records across
`results/216418.jsonl`, `results/demo-a.jsonl` and `results/demo-b.jsonl`.
All four are 0.6.0 and pass the envelope validator; no 0.1–0.4 records
carrying dwelling flags were present. This checks the current shared branch,
not any operator's unpushed checkout. The legacy ID constraints remain in place.

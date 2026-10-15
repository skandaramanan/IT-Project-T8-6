# D011 — Card to record: cleaning, status, and field placement

**Status:** Accepted
**Date:** 2026-09-03
**Decided by:** Skanda Ramanan (Design Lead)
**Linear issue:** IT-70

## Context

D007 (IT-39) fixed the output envelope. D008 (IT-79) fixed the extractor
interface. Neither says how you get from one to the other.

An `ExtractionResult` is `fields: dict[str, str]` — card labels against
whatever the model said, uncleaned. A D007 record is nested dwelling →
household with every leaf a field object carrying value, code, label, status
and confidence. `backend/survey/extraction/record.py` is that step, and building it forces
three choices that follow from neither record.

## Decision

### 1. Values are cleaned on the way in, and the cleaned value is what is stored

The rules are the ones already in `benchmark/scoring.py`, moved onto the extraction
path:

- Strip whitespace and `.:;,` — fields are joined to their values by a row of
  leader dots and OCR reads some of them as part of the number (`1.` for 1,
  `1.5.` for 15).
- A value made entirely of void marks (`-`, `--`, `B`, `BB`) becomes empty. The
  transcriber wrote `-`; the 1940s coder voided cells with one `B` per column.
- Fold digit lookalikes: `O`, `o`, `Q` → `0`; `I`, `l`, `L`, `!`, `|` → `1`.
  Handwritten 0 and 1 come back as letters.
- The word `null`, in any case, is empty (added 2026-10-13, IT-123). The prompt
  asks for every value as a JSON string and for null on a blank cell, so
  Flash-Lite sometimes quotes it: 319 of 5,771 coding cards in the full run.
  Folded as a code it became `nu11`, written as `ok`. Handwritten fields get
  the same rule.
- **Leading zeros are kept.** `04` and `4` are two different codes in a
  fixed-width scheme.

Both substitutions are safe because every value on this card is a number (bar
a dwelling number's letter, 487A, which in the corpus is A to E, none of them
a lookalike) — the code book defines no code containing a letter or a period —
so neither can turn one valid code into another.

The record stores the cleaned value. The literal string the model returned is
not persisted anywhere.

### 2. Status distinguishes returned data from omitted extractor output

When the extractor returns a field, empty after cleaning → `no_data`, value
null. Anything else → `ok`. When it does not return an expected field at all,
the record still emits that field with `omitted`, value null. This preserves the
distinction between no information in a field and an incomplete extraction.

A value the code book cannot explain keeps `ok` **and keeps its value**; its
`label` stays null. On a `categorical` field, where every valid code has a
meaning, that null label is the FR-09 / FR-11 signal that a human should look.

The signal is kind-dependent, not universal. On a `numeric_sentinel` field most
values are ordinary amounts and carry no label by design — Weekly Rent `04` is
four shillings, not an unknown code. A consumer has to read `FieldSpec.kind`,
not just the label.

### 3. The 62 fields are placed by what they describe, not by card order

The card is one flat grid; nothing on it says which level a field belongs to.

| Group | Holds |
| -- | -- |
| `dwelling` | Municipality, Number of Dwelling |
| `household` | Number of Household |
| `house` | The building — structure, age, garden, repair, rooms, facilities, sharing |
| `head` | The head of household — age, sex, occupation, earnings, unearned income |
| `counts` | Demographic aggregates — residents, age bands, breadwinners, children |
| `coding` | The rest of this household — type of family, income, rent, tenure, residence |

Sharing (`Rooms Shared`, `Persons Sharing`) sits under `house` because it
describes the building's arrangement. Tenure and Length of Residence sit under
`coding` because they describe this household's hold on it, not the building.

Address, families-in-dwelling and the person grid are absent: they are on the
survey front, not this card.

## Alternatives considered

**Leave cleaning in the scorer only.** This was the status quo. Rejected once
measured: on the 2026-09-01 Azure run the two rules accounted for 305 of 731
apparent mismatches — about 25 accuracy points of pure scoring artefact. A
clean-up that runs only at scoring time makes the benchmark look right while
the dataset carries `1.` and `O` into the Archives' hands.

**Strip leading zeros as well.** Rejected. It reads `4` off a cell that says
`04` and silently rewrites the card.

**Store the model's literal string alongside the cleaned one.** Considered, and
the traceability argument for it is real. Rejected for now because the
envelope's `original_value` is spoken for by NFR-05 — it means "the machine
value a human replaced" — and reusing it would make an automatic clean-up
indistinguishable from a reviewer's correction, which is the one thing NFR-05
exists to prevent. Adding a second field is a D007 change, not an IT-70 one.

**Map an unexplained code to `no_data`.** Rejected. `no_data` says the cell was
empty. An unreadable or out-of-range code is a different claim, and treating it
as missing throws away the value the reviewer needs to make the call.

**Add an `invalid` status to the envelope.** This is the cleaner answer and it
is rejected only on scope: it changes D007's schema, and one ticket should not
widen another's contract unilaterally. See "Revisit if".

**Emit only the fields the model returned.** Rejected. A card is 62 fields
whether the model found them or not, and a field that silently stops existing
is indistinguishable from a field the card never had.

## Consequences

- Stored values differ from what the model literally emitted, and the literal
  is not recoverable from the record — only by re-running the extraction.
- A null `label` carries two meanings depending on the field's kind. Anything
  routing a review queue has to check the kind.
- Every card produces 62 fields regardless of what came back. A field missing
  from extractor output is represented as `omitted`; a returned empty or
  voided field is `no_data`.
- `confidence` is null on every field. No engine benchmarked under IT-46
  produces a per-field score, and writing a number would breach NFR-01.
- `negated` resolution is decided in D023, not here.
- C3 records are not built. `C3_FIELD_SCHEMA` types that card, but nothing maps
  it into a record — C3 is 4 pages in one unit (D009), and it needs either its
  own mapping or an explicit non-goal in the requirements.

## Revisit if

**FR-11's threshold work needs a stronger signal than a null label.** Then add
`invalid` to the envelope's status enum and set it here — that is a D007
amendment and should be recorded as one.

**Superseded by D023** for the crossed-out negation/correction question.

**An engine lands that produces per-field confidence.** `ExtractionResult`
already carries it (D008); this step just stops passing null.

**Reviewers ask what the model actually said.** That is the trigger to take the
raw-value question back to D007 rather than improvise a field here.

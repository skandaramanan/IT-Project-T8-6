# D017 — Validating supplementary handwritten fields against the 1980s transcription

**Status:** Accepted
**Date:** 2026-09-10
**Decided by:** Elliot Guo (US-12 / FR-14 owner)
**Linear issue:** IT-63 (also IT-102, IT-103; supersedes IT-38)

## Context

FR-14 (US-12) asked for extractions to be validated against the 1980s manual
transcription. Two things then changed what that can mean.

**Client Meeting 3 (08/09/2026).** The dataset was received via the Australian
Data Archive and the client reclassified it: directional/test data, not ground
truth. The original transcription was done to a specific scope under hand-entry
constraints, is not a complete record, and the client has not reviewed it.
NFR-03 was decoupled at the same meeting — its accuracy/confidence threshold is
calibrated against source images and never depended on this dataset.

**Engineering assessment (10/09/2026).** The file (`Prest Survey (work) STATA
Heidelberg & Melbourne.dta` / `.xls`) is the coded form of the handwritten
survey front's per-person grid:

- One row per person, ~16,800 rows, keyed on the 1980s household id
  (`CASECODE2`) plus a family-group number (`GROUPNO`).
- Person attributes only: relationship, age, sex, marital status, earning
  status, regularity of work, occupation, industry, current and unearned
  income, pre-war occupation/earnings/unemployment, workplace, travel, military
  service, children.
- No residential address, no dwelling number, no dwelling-level grouping.

The numeric coding card — the FR-01 extraction target, whose output schema is
fixed by D007 and D010/D011 — is at a different level: one record per dwelling,
with per-family blocks and a physical-house block. The 1980s data has **no
counterpart** for its rent, rooms, tenure, overcrowding, poverty or
physical-house fields (roughly 37 of the ~60 fields), and **no key** to align a
1980s household to a coding-card dwelling.

It does line up with the **FR-03 supplementary handwritten-front fields**
(US-03): same grain, same source section, matching field concepts. Address is
the exception — it is not in the 1980s file.

## Decision

**The 1980s transcription is used as a directional accuracy check on the FR-03
supplementary handwritten-front fields, and nothing else.**

1. **Scope: FR-03 fields only.** Not the FR-01 coding-card output. The coding
   card and the 1980s dataset share no fields, no grain and no key.

2. **Directional, not certifying.** The comparison confirms or flags; it does
   not certify accuracy. It does not gate NFR-03 (source-image calibration) and
   does not recalibrate the dual-extractor findings (IT-84, IT-100), which keep
   their own provisional-pending-calibration status.

3. **Field-level agreement over the mappable subset.** Fields with no 1980s
   counterpart are listed in the report, not silently skipped. Coded 1980s
   values that need a crosswalk to compare (occupation title, industry) are
   compared at the coded level or excluded — never force-matched to raw text.

4. **Aggregate until record linkage exists.** The 1980s file has no address or
   dwelling number, so a row cannot be tied to the scanned survey it came from.
   Until IT-103 establishes a linkage method (candidate: matching on household
   composition), the comparison is aggregate/distributional, not row-for-row.

5. **Tracked under IT-102**, which depends on FR-03 extraction (US-03) existing.
   IT-38 (re-validate the coding-card spike against the 1980s data) is
   superseded — that re-validation is not possible.

## Alternatives considered

**Use it as ground-truth accuracy for the FR-01 coding-card output.** Rejected.
Different grain (person vs dwelling), no overlapping fields, no join key — and
the client has explicitly declined to treat it as ground truth.

**Gate the output schema on reviewing the 1980s transcription's schema** (the
old FR-15 clause). Dropped. The client has not reviewed the dataset and it is
not ground truth; the schema is set from the card and the client's encoding
references (D007, D010/D011).

**Feed the comparison into NFR-03's threshold.** Rejected. NFR-03 is calibrated
against source images and was explicitly decoupled from this dataset at Client
Meeting 3.

**Skip the 1980s data entirely.** Rejected. For the person-level fields it is a
genuine independent signal, and US-12 still wants an external cross-check.
Downgrading to directional keeps the value without overclaiming.

**Force a row-level comparison now by matching on best-effort heuristics.**
Rejected as premature. The linkage question is real research with its own
false-match risk (IT-103); a comparison built on an unvalidated match would
report noise as signal.

## Consequences

- FR-14's verification is a directional comparison report, not a pass/fail
  gate. US-12's **Must** rating rests on NFR-01 and NFR-03, neither of which
  depends on this dataset.
- Nothing dataset-dependent blocks the coding-card pipeline.
- IT-102 stays in the backlog until FR-03 / US-03 extraction lands.
- Row-level accuracy on the FR-03 fields is contingent on IT-103.
- Coverage is limited to the regions the transcription actually spans (the file
  is labelled Heidelberg and Melbourne); the comparison only runs where both
  sides exist.

## Revisit if

**The client reviews the 1980s dataset and revises its status.** Then FR-14 and
this record are reopened.

**IT-103 finds a reliable record linkage.** Then FR-14 can report row-level
accuracy on the FR-03 fields, and scope 4 above is lifted.

**FR-03 extraction captures verbatim values needing the 1980s occupation /
industry dictionary to compare.** Decide crosswalk versus exclude for those
fields at that point.

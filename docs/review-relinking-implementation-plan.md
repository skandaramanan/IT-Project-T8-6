# Dwelling relinking: decision record

Status: implemented with schema `0.7.0` per-card ownership. How it works now, the
operator steps and the validation run are in [the reference](review-relinking.md);
this page records why it was built that way. Production data adoption remains a
separate decision.

## Problem

Before 0.7.0, the first coding card of a dwelling owned its municipality,
dwelling number and building fields; later cards lost their own readings in
grouped exports. A correction updated IDs without regrouping, and a new duplicate
identity was rejected outright. Reviewers could therefore not fix a card that was
attached to the wrong dwelling, nor save a correct reading that happened to collide
with another card. Corpus checks at the time found 246 duplicate identity
combinations (545 cards) under shared readings, 978 unplaced coding-only records
and 23 unplaced records with more than one candidate group; none was a verified link.

## Decisions

| Decision | Why |
| --- | --- |
| Each physical coding card owns its identity and building readings, keyed by `physical_card_id(region, PDF, page)`. | Record IDs, array positions and dwelling IDs change on regrouping and repeat across cards; the physical source does not. |
| Relinking stays within one region and PDF. Municipality is never inferred from the PDF. | Every populated region has one PDF and no dwelling spans PDFs, but that is a corpus fact, not evidence for a card. |
| Membership and duplicate identity are evaluated independently. | A duplicate `(region, PDF, municipality, dwelling, household)` says nothing about which dwelling a card belongs to. |
| A duplicate-producing correction is confirmed (**Save anyway**, **Compare**, **Go back**), then saved with `duplicate_record_id` on every peer. It does not block assigned completion. | A correct reading must stay saveable; there is no identity-winner policy. |
| Household-number edits never change membership. | Household number alone is not dwelling evidence. |
| Automatic moves need one homogeneous destination with a readable matching front number and no competitor. Mixed, coding-only, unknown-front and "partly fits" cases are manual. | Avoids an edited card manufacturing its own corroboration, and avoids automatic splits. |
| Moving a dwelling's last coding card keeps its former evidence as a read-only `retained_supplements` bundle on the moved card. | A primary record must have a coding card, but fronts, notes and people must not be lost or silently attached to the destination. |
| Undo checks the operation's own dependencies (affected membership, link-relevant identity, evidence ownership, superseding field decisions), not whether the region changed. | Unrelated later work, including later building corrections on the moved card, must survive and must not veto Undo. |
| Structural saves reuse the existing regional atomic replace, `expected_version`, `request_id` receipts, writer lock and Git conflict stops. | No sidecar transaction log or new database was needed. |
| The seed is converted once, representation only, by `scripts/prepare_review_dataset.py`. | Rebuilding associations or rescoring would change published results that reviewers already trust. |
| Pipeline reruns keep reviewer link state and refuse to regroup reviewed records. | A rebuild cannot rederive a reviewer's relink; see the reference. |

## Rejected

- **Blocking last-card moves indefinitely** (handoff proposal): left wrong links
  uncorrectable. Replaced by retained bundles.
- **Region-wide Undo guard** (a stored post-operation hash): any unrelated save
  would have cancelled Undo.
- **Rejecting duplicate identities**: forced reviewers to enter wrong readings.
- **A reciprocal stored conflict graph**: peers are derived from the regional index
  instead, so flags cannot drift out of step.
- **Running `scripts/rebuild_cached_results.py` to prepare the seed**: it rebuilds
  associations and calls scoring.
- **Borrowing another card's building readings or confidence** for missing
  later-card evidence: such fields are omitted with null confidence and a visible
  issue.
- **Runtime fallback between ownership models**: a dataset is all `0.6.0` or all
  `0.7.0`; mixed data is refused.

## Out of scope

Front-only primary records, persistent dwelling UUIDs, cross-region/PDF moves,
arbitrary front splitting, individual person reassignment and a database
migration. General reattachment of a retained bundle to another dwelling is
deferred: it is a future association workflow, not part of Undo.

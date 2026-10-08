# D026 — Reruns merge by coding card, not record_id (amends D007)

**Status:** Accepted
**Date:** 2026-10-06
**Decided by:** Skanda Ramanan (IT-121 assignee)
**Linear issue:** IT-121

## Context

IT-121 asks reruns to merge output "by `record_id` (D007)". But `record_id`
is read by the model: re-extracting a card can change it, and two cards can
read the same one. Reruns without a reading cache are normal, not rare,
because `results/` is committed (D025) and `data/runs/` is not, and the
full-corpus run is split across five machines (IT-123).

## Decision

A record is matched to its previous version by the set of coding cards it was
read from, `(PDF name, PDF page)`. A rebuilt record replaces a previous record
only when the run rebuilt all of that record's coding cards. A previous record
the run rebuilt only in part (a household unread, unplaced or with no
record_id) is kept, and the rebuilt records sharing its cards are dropped. A
previous record sharing no card with the run is kept. A field with `origin: "corrected"` is copied onto the rebuilt record
at the same path, and only when the rebuilt record has the same households,
in the same order, with the same cards; otherwise the run stops and writes
nothing.

## Alternatives

- **`record_id`:** a misread on rerun duplicates the household, or orphans its
  corrections.
- **The first household's card only:** once records are dwellings (IT-105), a
  card moving into another dwelling leaves a stale duplicate.

## Consequences

- No duplicates by construction, and a capped or failed run never truncates
  the file.
- A household that drops out of its dwelling on a rerun (amended with IT-66,
  once records became dwellings) never takes the whole line with it; the
  previous line stays until a run rebuilds every household on it.
- A record whose scan is removed from the folder stays until deleted by hand.
- Without the reading cache (a rerun on another machine, or `--fresh`, which
  sets it aside) every card is read again, so uncorrected values may change;
  corrected fields, and the record_id they imply, are kept. A front read
  before but unusable now keeps its previous reading rather than blanking the
  address and persons, as long as the dwelling has the same fronts.
- PDF names must be unique within a region: two scans with the same name
  would share a merge key and a cache entry.
- Card `image` and `page` must stay the PDF name and PDF page number when
  association is wired in.

## Revisit if

Records gain a stable identifier that isn't model-read.

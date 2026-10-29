# Per-card review and dwelling relinking

In schema `0.7.0` data, each physical coding card owns its municipality,
dwelling number and building readings. Extraction, association, merge scoring
and the pipeline all write 0.7.0 (the pipeline calls `finish_records` on each
region before writing, and refuses previous results that are not 0.7.0). Nothing
is transformed at startup. Published results are still `0.6.0` today; until they
are converted once with `scripts/prepare_review_dataset.py` (needs the Gemini
cache; no model calls), the reviewer keeps serving a fully `0.6.0` dataset with
shared first-card ownership and without relinking. It refuses a dataset that mixes
the two. Cards with no cache (216428 p49, 216460 p378, 216463 p279) stay
`missing_card_reading`.

Planner rule: when a card no longer fully fits its group but a sibling or the
front still reads its dwelling ("partly fits", e.g. a `fronts_disagree` group),
the outcome is `ambiguous` (manual), never an automatic split. Structural Undo is
refused if any member of an affected dwelling changed its municipality/dwelling
since the move; frames record each member's dwelling key.

## Prepare and adopt separately

Use pinned published inputs and retained primary artifacts with a fresh staging
directory outside the input tree:

```sh
uv run python scripts/prepare_review_dataset.py \
  --previous results --cache /path/to/retained/data/runs \
  --output /path/to/new-review-staging
uv run survey validate-results /path/to/new-review-staging
uv run survey flags /path/to/new-review-staging > /path/to/new-review-flags.jsonl
```

The tool does not extract, call models, rebuild associations or rescore fields.
It preserves published confidence, card scores and protected payloads. Omit
`--cache` for a conservative inspection: missing later-card readings become
omitted/null-confidence fields with a visible issue, never copies of another card.

Optional `--field-evidence /path/to/evidence.json` accepts a JSON array of existing
measurements: each row has `region`, `pdf`, `page`, and `fields` mapping printed
field labels to `{ "value": "7", "confidence": 0.75 }`. These example numbers
are illustrative, not a calibration claim. Measurements must match the recovered
primary source, field and value. The report pins input/cache/evidence hashes and
records recovery gaps, queue size, protected mappings and field-payload hashes.
Municipality aliases can map to one canonical per-card field; each original
mapping is retained. Published files and their merge manifest remain untouched.

Before adoption, resolve reported recovery gaps or explicitly accept them, check
preservation receipts, and inspect the live data branch and actual reviewer
workspaces for newer decisions. Reconcile reviewed work rather than replacing it
with a fresh seed. Preserve the old seed in normal Git history and deploy matching
code, data and regenerated flags together. Keep extraction/rerun tools away from
review data. If a rerun does meet reviewed records, it refuses when a corrected or
relinked record would be regrouped, and otherwise copies each household's `relink`,
`link_history` and `retained_supplements`. Production adoption remains a separate
operator decision.

Build React before distribution (`npm run build` in `frontend/`). The source-only
integration page does not provide the new confirmation/link UI.
`scripts/review_demo.py` creates prepared synthetic practice data with a local bare
Git remote. Sample and benchmark tools use disposable copies and preserve sources.

## Correct, compare, link and Undo

- Municipality/dwelling-number corrections evaluate membership within the same
  region/PDF. Household-number edits update identity/duplicates only.
- A card keeps its current dwelling unless that dwelling's other evidence (another
  card's known reading or a readable front number) contradicts the correction.
  Unknown readings do not contradict. A sole coding-only card does not corroborate
  itself. If another compatible dwelling also exists, the link stays manual.
- A unique homogeneous destination corroborated by front number can receive the
  complete coding household automatically, preserving its own readings/history.
  Mixed readings, missing front numbers, coding-only candidates and competing
  destinations require manual selection. Municipality is never inferred from PDF.
- A duplicate-producing correction first offers **Compare**, **Go back** and
  **Save anyway**. Saving preserves all physical cards and flags all peers.
  Duplicate flags do not block assigned transcription completion.
- The banner persists after automatic advance and on reopening. Compare shows
  saved readings, source scans and associated fronts. **Fix identity** opens an
  unqueued peer identity; this voluntary correction does not add assigned work.
- **Link to dwelling** chooses a compatible current group or a provisional
  coding-only group. It never edits numbers or merges card payloads.
- A last-card move requires explicit retention of its former evidence. Its
  number correction can save first. Multi-card person ownership or a note
  explicitly owned by the departing card stays pending rather than being split
  or reassigned automatically.

Retained bundles keep the former scans, address, handwriting, notes, people and
histories read-only inside the same regional file. They are accessible from the
moved card and are not associated with its destination, counted as its fronts,
or queued for review. Queue details show retained-bundle and pending/provisional
counts separately from transcription completion. General reattachment elsewhere
is deferred; no automatic later attachment is scheduled.

Undo of a combined correction/automatic move reverses both. Undo of a separately
saved manual link keeps the earlier correction. **Undo last link** and link
history remain available after later ordinary saves. Reversal checks physical
membership, municipality/dwelling dependencies, relevant field history and evidence
ownership. Unrelated regional changes and later building corrections on the moved
card do not block Undo; those corrections survive. Independent household-number
edits survive where link dependencies remain valid; IDs/duplicates are recomputed.

Changed affected membership, altered front/back ownership, a changed retained
bundle or a superseding target-field decision can block reversal. The response
identifies the dependency. Undoing a dependent move can make an earlier Undo
eligible again. Stale requests reload and reevaluate. A retained supplementary
field must be restored before its individual field decision can be undone.
Otherwise its complete retained data remains available for operator reconciliation;
there is no general reattachment editor in v1.

## Persistence and API

Each mutation uses `expected_version` and `request_id`. Retry an uncertain request
with its exact original ID/body: a lost response may follow a successful commit.
Durable receipts replay after restart without another move, bundle or audit event.
Changed ID reuse is rejected. Local save and upload remain separate states, with
existing writer locks and same-region Git conflict stops.

Structural effects, current peer flags, retained data and audit commit through one
validated atomic regional replacement. The transaction checks conservation of
physical sources and person rows. Undo carries current household objects and
histories; inverse snapshots contain topology/envelope metadata, not recursive
copies of histories. Changed-region assignments/progress are rebound while
unaffected regions keep their caches. Suspended retained-front assignments return
when the evidence is restored. Full regional validation/writing still contributes
to latency, separately from the dependency checks.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/review-items/{item_id}/preview` | Read-only correction planning at `expected_version`; returns conflict signature and membership outcome. |
| `POST /api/review-items/{item_id}/decisions` | Existing mutation plus optional `duplicate_confirmation` matching the current preview. |
| `GET /api/cards/{card_id}` | Card/identity context, registered scans, retained data and link history, including unqueued cards. |
| `GET /api/cards/{card_id}/link-candidates` | Current compatible candidates, version and retention requirement. |
| `POST /api/cards/{card_id}/link` | Versioned link using a physical `target_card_id` anchor (null for provisional) and `retain_supplements`. |
| `POST /api/decisions/{decision_id}/undo` | Existing reversal boundary, including standalone links. |

Preview and commit evaluate the same planner independently; confirmation expires
when the regional version changes. Scan access accepts only registered active or
retained physical sources. Ownership is chosen per dataset, never per record:
a mixed published/prepared dataset is refused at startup.

## Implementation validation (29 October 2026)

- Backend suite: 1,021 passed, 19 skipped under existing test conditions. Model
  API credentials were removed from the test process.
- React suite: 100 passed; TypeScript and production build passed.
- Browser suite: 16 passed against disposable synthetic data and local remotes,
  including confirmation before a duplicate save, unqueued peer repair, retained
  scans/notes, and link Undo preserving a later building correction.
- Ruff lint/format and Git whitespace checks passed. Published `results/` and
  the schema example have no changes.
- Corpus regressions check pages 175/179's distinct seven/six-room readings and
  preservation mappings for all 34 corrected occurrences. Synthetic regressions
  cover ambiguous-plus-duplicate outcomes, failures/retries/restarts, stale writes,
  retained field history, changed ownership dependencies, and reinstated Undo.
- A 20-run synthetic benchmark sized to the largest published region's 270
  dwellings measured the automatic-move dependency check plus inverse at
  0.653 ms median / 0.821 ms maximum on this host. It had no large retained bundle
  and excluded candidate copying, regional validation/writing, scans, UI and Git.
  It is not a production end-to-end latency claim.

Native Windows/operator acceptance and complete staged recovery/adoption remain
separate. The Windows CI selection includes the new relinking regressions.
No extraction, model calls, rescoring or production seed replacement was run.

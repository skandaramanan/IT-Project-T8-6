# Decision summary and audit

**Audited:** 2026-10-08. **Scope:** all 20 decision records committed in this directory, checked against the current README, schema, configuration and relevant implementation. External Linear documents, meeting notes, Drive data and live GitHub rulesets were not inspected; their contents and current status are not independently verified here. Numbering gaps are not assumed to be canceled decisions.

This index distinguishes accepted policy, current implementation and unresolved choices. Audit notes in the affected records point here without rewriting the historical rationale. Findings below remain open unless marked as a documented amendment; an audit is not approval of a new policy.

## Key points across all decisions

| Record | Current decision and qualifications |
| --- | --- |
| [D001](D001-dependency-manager.md) | Use uv, Python 3.12 and the committed lockfile. Runtime dependencies arrive with their code. The promised locked optional local-model extra is not implemented (A10). |
| [D002](D002-engineering-standards.md) | Use Linear-generated issue branches, scoped issue-linked commits, PRs and another person's approval. Main is intended to be protected with no bypass. The six-item Definition of Done lives externally. |
| [D003](D003-automated-checks.md) | One required `check` job runs locked dependency installation, Ruff lint/format and pytest; D004 adds history-based secret scanning in that job. Workflow matches locally; live required-check enforcement was not verified. |
| [D004](D004-data-storage-and-secret-scanning.md) | Store scans and large derived artifacts in Drive/local ignored data; commit small fixtures. Scan history with pinned gitleaks and redact findings. D025 explicitly permits committed scored results. Rotate any pushed secret. |
| [D006](D006-source-provenance.md) | Resolve field card roles through scoped dwelling/household card lists carrying image and page. Coding branches imply their source. Multiple same-role cards and path stability remain limitations (A08). |
| [D007](D007-output-record-schema.md) | JSONL per region, dwelling → household → person, field objects with status, nullable confidence and correction provenance. Household `record_id` is the municipality/dwelling/household composite; D026 supplies the rerun key. D017 removes the 1980s-data schema gate (A01). Envelope validation still does not prove a final agreed field inventory. |
| [D008](D008-extraction-interface-contract.md) | All extractors use one Protocol and `ExtractionResult`; empty fields represent failed/empty output, raw text is diagnostic, confidence is optional. Current result also has cost and strike detection (A11). |
| [D011](D011-card-to-record-mapping.md) | Normalize numeric coding values while preserving leading zeros and sentinel meanings; distinguish blank from omitted. Place 62 C1/C2 fields by semantic level. Unknown categorical codes keep their value and a null label. C3 mapping remains unimplemented. Later pipeline scoring and caching qualify older claims (A02, A06). |
| [D016](D016-agreement-to-confidence.md) | Score the selected primary reading using agreement class: agree 0.97, disagree 0.75, one-blank 0.74; both-blank inherits 0.97 without adequate measurement. Standalone scores depend on surviving model; optional band tables require sufficient support. These are provisional estimates from 30 development cards, without held-out validation. |
| [D017](D017-validating-supplementary-fields-against-1980s-transcription.md) | Use the 1980s person data only as a directional handwritten-front comparison, aggregate until linkage is validated. It neither certifies coding-card accuracy nor gates NFR-03 or the output schema. |
| [D018](D018-card-level-confidence.md) | Card confidence is the mean of the lowest `ceil(n/4)` field scores, rounded to two decimals. It is a triage measure for the weakest fields, not whole-card correctness. Aggregation and calibration remain provisional. |
| [D019](D019-dual-extractor-go-no-go.md) | Conditional go for both arms, using the first viable Spartan/OpenRouter/Kaggle route, with a benchmark before scale-up and recalibration where needed. Single Gemini plus band is the fallback. The shipped CLI currently uses one arm; banding policy conflicts with D022 (A03–A04). Recorded cost/quota estimates are historical, not refreshed here. |
| [D020](D020-noise-vs-meaningful-annotations.md) | Extract requirement-defined marks targeting a specific field; ignore unknown annotations, stamps and multi-field marks. Distinguish negation, corrections, printed alternatives and deliberate blanks. Some fixture marks remain unclassified; survey-front semantics exceed D023's resolver (A07). |
| [D021](D021-disagreement-resolution-policy.md) | Gemini Flash-Lite wins field disagreements, including a primary blank. Use Qwen only when the primary card arm fails. Preserve agreement evidence. The implementation moved under D024 (A11). |
| [D022](D022-review-routing-rule.md) | Implemented rule: review unless status is `ok` and confidence is at least the current agree constant (0.97). Blanks always review. Assumes banding off. The client-confirmation wording is broader than this rule; unknown categorical codes lack the D011 review safeguard (A04–A05). |
| [D023](D023-resolving-struck-options.md) | On numeric coding fields, a detected strike clears value/code/label, sets no-data and negated; identity fields are exempt. No detector means no negated key. Replacement/option-level cases are not representable and remain unresolved. |
| [D024](D024-repository-layout.md) | Install `backend/survey` as the survey package; benchmark may import production, never the reverse. Keep schema and committed results at root; frontend is reserved. Supersedes earlier src/spike paths. |
| [D025](D025-committed-results.md) | Commit scored `results/<region>.jsonl`; keep raw responses and spike output ignored. Reviewers change records, not schema. How review-tool writes reach protected main remains an explicit open choice (A09). |
| [D026](D026-rerun-merge-key.md) | Merge by coding-card `(PDF name, PDF page)` sets, not model-read record_id. Preserve untouched records and human corrections; refuse unsafe reviewed regrouping. PDF names must be unique per region. Association must retain that provenance (A08). |
| [D027](D027-region-is-an-archive-unit.md) | One scan folder/UMA Node ID is one region, not one archive unit or suburb. Validate region names and refuse mixed-region result files. Parts stay separate; renaming or processing the same folder under different names risks duplicates. The filename retains the superseded terminology. |

## Discrepancies and contradictions

### A01 — High: obsolete schema gate (D007 versus D017)

D007 still says FR-15 and final fields wait for IT-38/1980s access, including its status, context, alternatives and revisit triggers. D017 says the dataset arrived, IT-38 is superseded and that gate was dropped. The schema's top-level description repeats the obsolete IT-38 gate. D007 also says no front inventory/task exists, while `survey_front.py`, association code and README's IT-117 reference now exist.

**Update required:** amend D007's current status and open questions, plus the schema description, to cite D017 and identify whatever client field-set agreement is still outstanding. Do not infer that FR-15 is complete merely because its old dependency disappeared.

### A02 — High: production confidence is described as absent, but is populated

D016 and D018 say scores cannot enter real records until `source_agreement` is added; D022 says every field currently has null confidence. D011 also claims confidence is always null. `build_record()` still emits nulls, but `pipeline._score()` then fills field and card confidence using D016's standalone rule; omitted fields receive 0.0. The schema permits numeric confidence without `source_agreement` and still rejects that additional key.

**Update required:** distinguish converter defaults, the single-arm CLI scoring step and paired benchmark output. Numeric confidence does not require a schema extension; persisting agreement evidence does. Default Flash-Lite scores 0.91, so its fields still all route to review under D022, for a different reason than the records state. Association output still has null confidence, so integration is path-dependent.

### A03 — High: accepted dual-run plan differs from the shipped CLI

D019 calls for both arms over the full corpus. README and `pipeline.py` currently describe/implement a coding-card, single-extractor run; the dual harness is separate. This does not prove the conditional go was abandoned, and no route outcome or fallback activation is documented in the local decisions.

**Update required:** record the selected route and pre-run benchmark result, or explicitly record the fallback and how paired outputs become the committed dataset. Restore or link the referenced D012 variant-selection decision; D019 itself identifies that approval gap.

### A04 — High: banding and review-policy conflicts

D019 rejects dropping the band and says it remains part of the chosen formula/fallback. D022 later assumes banding off for dual extraction, and `.env.example` defaults it off. D022's client-confirmation wording says agreeing fields need no review and everything else queues, but the written/implemented rule also queues both-blank agreement and banded agree/medium fields. Confidence alone is a proxy for agreement, not an explicit agreement check.

**Update required:** explicitly state whether D022 amends D019 for dual runs, separately decide the single-arm fallback setting, and clarify whether agreement exemptions apply only to usable nonblank values. Keep routing and persisted evidence consistent; do not silently choose between those interpretations.

### A05 — High: unknown categorical codes can escape the promised review safeguard

D011 retains unknown categorical values with status ok and null label and calls that an FR-11 review signal. D022 explicitly defers that condition. `review/routing.py` checks only status and confidence, so a hypothetical agreeing unknown code scored 0.97 clears. This is currently masked in default standalone CLI output by its lower scores, not resolved.

**Update required:** settle the exception before paired data is used for routing. Check categorical kind/code validity rather than treating every null label as invalid: ordinary numeric values legitimately have no label.

### A06 — Medium: raw-output recoverability claims are obsolete

D011 says the literal model string is never persisted and is recoverable only by rerunning. D008 already defines diagnostic raw text, and D025/README specify raw-response storage. `pipeline.py` caches the serialized `ExtractionResult`, including raw text when available, under ignored run data. The literal is absent from the exported field object but can be recoverable from a retained local cache.

**Update required:** document that distinction and the cache's availability limits across machines; preserve `original_value` exclusively for human correction provenance.

### A07 — High: strike semantics cover different scopes

D020 distinguishes corrections and printed alternatives from a simple handwritten-value strike. D023's single boolean always nulls a struck nonidentity numeric field, cannot distinguish replacements or options, and deliberately discards identity strikes. Applying it generally to survey fronts would lose the unstruck alternative or replacement. D023 already acknowledges its signal limits; these are unresolved coverage gaps, not permission to treat every mark identically.

**Update required:** state the numeric-coding scope explicitly and track richer detection/resolution for survey fronts and corrected/voided identities. Do not claim full FR-06 coverage from this resolver alone.

### A08 — High: future association can break stable merge provenance

D026 requires card image/page to remain original PDF name/page for rerun matching. CLI construction does this; `association/records.py` currently uses `str(card.image_path)` for coding cards, which refers to the extracted image path. D006 additionally acknowledges that a role does not uniquely identify a card in multi-household dwellings. Card extraction confidence in D018 also does not measure segmentation correctness, despite D006 placing segmentation doubt in that slot.

**Update required:** retain original PDF identity through association before wiring it into the CLI merge; define exact-card provenance where roles are ambiguous. Distinguish extraction confidence from segmentation/association flags or confidence.

### A09 — Medium: review-tool write workflow is still undecided

D025 leaves protected-main integration open and recommends a review branch; it does not accept that branch design. D002's PR/review protection still governs. README says commit corrections and rerun on the reviewed branch without specifying how that branch is created or merged.

**Update required:** record the workflow in the review-tool decision before external writes are built. Keep the recommended option labeled as a recommendation until chosen.

### A10 — Medium: local-model reproducibility deviates from D001

D001 promises heavy local-model dependencies as an optional extra once the model choice resolves. `pyproject.toml` instead explicitly excludes and leaves torch/transformers/qwen dependencies manually installed and unlocked. D019 depends on reproducing a calibrated quantized Qwen setup.

**Update required:** either provide a pinned optional/GPU environment or formally amend D001 with the chosen separate reproducibility mechanism. A matching GPU alone does not specify the software environment.

### A11 — Low: incomplete record links, contract and terminology drift

D009, D010 and D012 are cited but absent from the local decision directory; D005 and D013–D015 are also absent, without enough evidence to classify those gaps. D021's `spike.confidence.resolve_primary_value` moved to `survey.confidence.field.resolve_primary_value`. D008's result example lacks the current `cost_usd` and `struck` additions. Older D007 passages say 60 fields while D011/D016 specify 62 C1/C2 fields (C3 has 60). D017's claim that the datasets share “no fields” is too absolute: its own context lists person/head concepts they share; the real obstacle is grain, coverage and reliable linkage. D027's filename still says archive unit although its amended text correctly says UMA item.

**Update required:** restore/link missing referenced decisions, refresh API examples and path references, qualify field counts by card type and narrow D017's overlap wording. Preserve D027's existing inbound links if its filename is changed.

### A12 — Low: confidence documentation overstates measurement support

D016's consequences describe seven of nine class/band cells as thin or zero-support, but its table includes seven cells meeting its adopted n≥10 threshold and two falling below it. Its n=1 both-blank result is reasoned, not measured. D018's probability wording inherits those estimates and their development-set limitations; the bottom-quartile aggregate has not itself been independently calibrated.

**Update required:** separate measured cells, sparse measured estimates and reasoned fallbacks; describe the card score as an aggregate of estimated field reliability. Do not present either as independently validated probabilities.

## Documented amendments that are consistent

- D004 adds secret scanning to D003's existing job; the local workflow matches.
- D025 explicitly overrides D004 only for committed scored results.
- D026 explicitly replaces record_id as D007's rerun merge key; household identity remains intact.
- D024 supersedes historical src/spike layout and resolves D007's schema naming issue.
- D027's amended body correctly distinguishes UMA items from archive units; only its filename remains historical.

## Recommended update order

1. Reconcile model variant, dual-run route/fallback, band setting and review exceptions together (A03–A05).
2. Correct schema-gate and confidence integration claims (A01–A02); preserve the distinction between envelope validation and final client agreement.
3. Align association provenance with safe reruns and scope strike resolution (A07–A08).
4. Decide review writes and local-model reproducibility (A09–A10).
5. Refresh cached-raw-output wording, links, contract examples and measurement qualifiers (A06, A11–A12).

Only the audit/index and linked audit notices were added in this pass. Policy choices, schema validation behavior, code and external systems were not changed.

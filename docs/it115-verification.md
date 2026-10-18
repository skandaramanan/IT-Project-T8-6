# IT-115 PR 4 verification — 19 October 2026

Local uncommitted diff on base `9cf8a35c3883f8ff75113d7d4d23760c4a73de05`.
Primary checkout used at the user's revised instruction, on branch
`skandar/it-115-reviewer-screen-a-queue-to-browse-and-a-screen-to-review-pr-4`.
The exact Linear branch already contains older PR1 work, so it was preserved.
No code/data commits, pushes or remote changes were made to this repository.
Test-only seed/share commits and pushes used newly created local disposable
checkouts and bare remotes. Original results/scans/review-data were not written.

## Results

| Check | Observed result |
| --- | --- |
| Full `uv run pytest --cov=survey --cov-branch --cov-report=term-missing` | **779 passed, 13 skipped, 2 xfailed, 1 failed**, 340.70s; coverage 93% |
| Final `uv run pytest tests/test_review_acceptance.py tests/test_review_api.py -q` | **20 passed**, 16.35s; independently repeated with 20 passed |
| Independent acceptance/API/sync run before final race regression | **47 passed**, 114.50s; final acceptance helper rechecked separately, **4 passed** |
| `npm --prefix frontend test` | **51 passed** |
| `npm --prefix frontend run e2e` with production sample environment | **9 passed**, 35.5s; includes TypeScript check and Vite build |
| Ruff check / format / `git diff --check` | Passed |
| Root results and `results/qwen2.5-vl-server-2000000px` validation | Both passed, all 44 region files in each |
| Moved source-plus-built-assets package | Locked installation, React root and production API passed from temporary relocated folder |
| Existing remote CI for base `9cf8a35…` | frontend, e2e, check, review-windows all success |
| CI for this local diff / physical Windows desktop / human TC-M07 | **Not run** |

The full run collected 795 tests before the final source-race regression was
added; final focused and independent checks cover that added regression and
helper changes. The single full-suite failure is
`tests/test_216436_additions.py::test_complete_local_rebuild_keeps_all_sources_and_resolves_verified_gaps`:
available local IT-123 inputs enable a test whose `isolated()` guard refuses
this IT-115 branch with `RuntimeError: not the isolated additions branch`.
It fails before rebuilding or writing outputs. The test and additions builder
are unchanged against main. Reproduction is retained separately; do not weaken
the guard or rebuild original results to obtain a green number. This is an
unresolved local test-environment limitation, not a successful full suite.
Skipped/xfail fixture/calibration checks remain reported as such. A pre-existing
Starlette/httpx deprecation warning was emitted.

## Production compatibility and end-to-end evidence

Independent read-only audit of committed root results found 44 regions, 5,375
dwellings, 5,430 households and 335,487 generated flags, with no skipped sources
or unresolved references. All referenced PDF files exist. There are 460 nullable
household display IDs. This proves structural compatibility, not visual approval
of every scan or correctness of all machine transcriptions.

The actual producer and matching copied original PDF were exercised on region
216412: 75 dwellings and 4,650 flags. Every queue entry had a unique ID,
value/status/confidence, declared decision actions and a scan URL; no diagnostics.
The generated synthetic contract test additionally opens every detailed item and
asserts its supplied ID occurs in actionable card context. Real browser execution
used the built React application, a physical archive PDF page, generated flags,
correction `009`, local sharing and reload/reopen. The source scan is loaded
before decision controls enable. The production assertion budget is 30 seconds
for image decoding; the bounded test budget is 120 seconds.

Independent production-copy HTTP verification corrected one field to `009`,
accepted another, repeated the exact request, rejected a stale version with 409,
shared to its new local bare remote, restarted and read the persisted JSONL.
Machine original, attribution/time/history and exact string survived. Deep
comparison showed only those fields and the required schema upgrade changed.
Regenerated flags changed **4,650 → 4,648 → 4,649** after Undo. Both original
JSONL and original PDF hashes matched before/after. Separate browser source-hash
verification also passed after its correction/share/reopen journey.

Existing meaningful regression suites cover multiple households, nullable display
identities, blocked/missing scans, diagnostic scope, stale input, lost responses,
Undo and failed sharing. Real-browser tests cover response-loss idempotency,
competing reviewers, missing scan, failed remote recovery and lost session.
Two-clone backend Git tests cover disjoint-region sharing, same-region manual
reconciliation stops, rejected pushes and concurrent save/reconciliation behavior.
They use only disposable local remotes. No live sharing permission was exercised.

## Independent review loop

Separate agents audited requirements/dependencies, reviewed implementation and
verified fixes/integration. Reproduced findings and resolutions:

1. Browser opener timed out at 30s while production readiness was documented at
   33.862s. Default is now bounded at 300s; deterministic tests verify readiness
   at 34s, explicit short timeout and startup failure. Another agent reproduced
   baseline failure and fixed success.
2. A fully reviewed, regenerated empty assignment prevented startup. Removal of
   that rejection preserves missing-file diagnostics; baseline/fix independently
   reproduced. This overlaps the corresponding small open #68 change explicitly.
3. Helper parsed-source/copy race: retain the parser's raw-byte SHA, compare
   before destination creation, compare copied record bytes and recheck originals.
   Mutation-after-parse regression and independent stale-source reproduction pass.
4. Browser preflight could miss alternate Git push URLs. Resolve sample paths
   and require all effective fetch and push URLs to be exactly the disposable
   local remote. Alternate-push regression and independent reproduction pass.
   `/tmp` aliases are accepted after canonicalization.

Final independent implementation review found no remaining actionable blockers
in this scope. That review is not human TC-M07 or physical Windows acceptance.

## Evidence retained locally

Raw local evidence is retained under `/tmp/it115-final-evidence/` with a manifest
of final changed-file hashes and copied logs. Additional read-only retrievals:
`/tmp/it115-github/` (PR bodies, actual diffs, reviews, threads and CI),
`/tmp/it115-audit/` (issues, dependencies, comments, Product documents/designs).
Disposable samples: `/tmp/it115-production-browser` and
`/tmp/it115-independent-acceptance`. Moved package: `/tmp/it115-package-proof`.
These are local evidence paths, not published artifacts or permanent URLs.

Base CI: [GitHub Actions](https://github.com/skandaramanan/IT-Project-T8-6/actions/runs/39173833351).
Existing review-data tip observed read-only: `752b8093f3c7afc250be93bef39ad62940b75d2c`,
with review-save commits. Neither proves intended desktop credentials or final
local-diff CI. No final pushed SHA exists under the local-only restriction.

See [acceptance handoff](it115-acceptance.md) for exact remaining closure gates
and [proposed updates](it115-proposed-updates.md) for changes not applied remotely.

## Changed files

- `.github/workflows/ci.yml`: include copied-production acceptance contract in
  the Windows verification job.
- `backend/survey/review/api.py`: permit valid empty assignment startup.
- `backend/survey/review/launch.py`: bounded production readiness wait.
- `scripts/review_acceptance.py`: safe real-producer record/scan preparation.
- `tests/test_review_acceptance.py`: contract, persistence, regeneration, source
  isolation/race and empty/missing assignment regressions.
- `tests/test_review_api.py`: slow readiness and bounded timeout regression.
- `frontend/e2e/review.e2e.ts`: generated queue, matching production journey and
  effective push-destination preflight regression.
- `README.md`, `docs/reviewer-ui.md`, `docs/review-backend.md`: current handoff links
  and historical-evidence clarification.
- `docs/decisions/D022-review-routing-rule.md`: client-meeting date reconciliation.
- `docs/it115-acceptance.md`: setup/package/launch, scope, human and rollout gates.
- `docs/it115-verification.md`: this dated result/limitation record.
- `docs/it115-proposed-updates.md`: exact unapplied ticket/Product updates.
- `docs/it115-pr4-proposal.md`: proposed PR title and body, not published.

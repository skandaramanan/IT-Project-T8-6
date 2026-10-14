# IT-113 continuation verification — 14 October 2026

## Implementation and base

Local follow-up branch: `eric/it-113-build-the-review-queue-data-store-follow-up`.
Base: `3a52f5c`, the locally available IT-115 PR 3 stack, containing `0eaea42`,
`cdd9c08` and merged backend `3481738`. Original branches and backup refs were
preserved. This is local integration evidence, not verified live PR status.

Git SSH lookup failed to resolve github.com. GitHub connector GETs for #59 and
#53 returned 404. `gh` is unavailable. Linear was read: IT-113/115 In Progress,
IT-109 In Review with #53; IT-111/112 Todo and still carry obsolete wording.
No external messages, issue edits, remote pushes, branch-rule changes, production
provisioning or model/extraction spending were performed. Prepared issue wording
is in `review-linear-wording.md`.

Implemented: descriptors from existing coding and front definitions; unique-front
dwelling review; physically verified IT-89 note review; Unicode/multiline text;
existing damaged status plus explicit illegible action; stable note IDs across
fresh reordered flags; stale pointer/source refusal; restart/replay/undo; rerun
ownership protection; existing frontend metadata/navigation/text controls; narrow
0.5.0 review compatibility; a five-flag synthetic demo; source/built-asset package
helper and Windows operator runbook. Original machine payload, confidence, sources,
JSONL atomic saves, region versions and append-only history are retained.

Unsupported: person columns lose physical column/page identity, multi-front
merged dwelling fields lack exact source ownership, coding-back structured fields
have no established contract. Identity/negated fields stay accept-only. Legacy
household notes need explicit verified migration; none are silently moved/deleted.

## Automated developer checks

Commands use the installed editable source. `uv sync --locked --offline` succeeded
against the existing cache. Under the restricted sandbox, `UV_CACHE_DIR=/tmp/it113-uv-cache
uv run --no-sync ...` avoids the otherwise blocked default-cache access. Full tests
were rerun with loopback access because the sandbox refuses listener.bind.

Fresh pre-edit baseline: **607 passed, 14 skipped, 3 failed**. Two failures were
`test_confidence.py::test_constants_still_match_the_benchmark` (no paired agreement
observations, division by zero) and `::test_both_blank_is_still_too_thin_to_measure`
(1,860 NO_SECOND_OPINION observations). The third was the POSIX occupied-port
regression denied socket access by the sandbox. It passes with loopback access.
These failures were observed before implementation; none were hidden or silenced.

Targeted numeric/notes/rerun/schema/Git verification: **176 passed** at the first
broad integration pass. Final targeted record/text/dwelling suite: **82 passed**,
including invalid text audit/request, source ownership, missing source, note reorder,
all actions, damaged compatibility, exact Unicode, idempotency, stale versions,
latest undo and byte-retention tests. Windows CI coverage now includes new text and
dwelling regressions, but no remote CI result is available.

Frontend baseline: **43 passed**. Final integrated frontend: **45 passed**,
TypeScript and Vite production build pass. Added text tests exercise actual save
submission, uncertain-response exact retries, retained multiline drafts, stale
reload and scan gating. Built assets stayed stable during final backend checks.
Ruff lint/format and git diff whitespace checks pass.

Final full backend result: **636 passed, 14 skipped, 2 failed** in 130.62 seconds.
Only the two confidence-benchmark failures reproduced from the fresh baseline remain.
The POSIX socket test passes with loopback access. Final log: `/tmp/it113-final-pytest.log`.

## Copied records and original scans

Inspected local corpus snapshot `6407ae75724c394f94dd696c6f3218dc06f0b85e` on
`skandar/it-123-full-corpus-results`. Only the 0.5.0 envelope differences were
reconciled; corpus extraction/builders/data were not imported. Saved 0.5 records
keep their version, nullable/lettered IDs and dwelling flags. Older versions keep
numeric/non-null IDs; 0.3+ rejects legacy household notes.

A copy of `results/216418.jsonl` validates **116 dwellings**. Two copied dwellings
in `/tmp/it113-real-review-small/data checkout` used two manual address flags,
real original front scans, acceptance, restart and undo. Both PDF hashes and the
source copy remained unchanged. This selected region contains no dwelling notes.
Evidence: `/tmp/it113-real-review-small/verification.json`. No transcription accuracy
or production-queue correctness is claimed from accepting copied stored answers.

The illustrative r01 fixture was separately verified against original PDF pages
1–4 by committed JPEG-stream hashes. Its copied role/page metadata populates the
established dwelling front/back card slots; source example/scans remain unchanged.
On copied front/address and IT-89 note text, eight decisions (each of Accept,
correction, no-data, illegible) survived restart and undo. Correction used Unicode
and multiline input. Sharing succeeded to that copy's local bare remote only.
Evidence: `/tmp/it113-notes-fixture/review/notes-verification.json`. This is an
illustrative excerpt with unknown confidence, not fresh corpus extraction.

The final browser check used `/tmp/it113-final-synthetic`, a local bare remote and
four explicitly synthetic pages. It opened note navigation, saved exact Unicode/
multiline input, reloaded, displayed retained progress/text and audit history, and
showed local-save versus uploaded status. Screenshot: `/tmp/it113-text-review.jpg`.
This developer check does not establish native Windows or unaided usability.

An initially overlarge disposable corpus check was interrupted and replaced with
the two-dwelling sample. The partial checkout `/tmp/it113-real-review-copy` is not
acceptance evidence; original data/scans were never its write targets.

## Remaining delivery evidence

Production IT-109 queue integration stays gated on a verified merge and inspection
of its actual output. Live IT-115 bases/heads must be reconciled before a PR is
based/published. Current implementation is local and is not pushed or merged.
The 0.5.0 review envelope is compatible with the inspected sample; the full live
corpus and upstream extraction stack are not certified here.

Windows source/built-asset package and precise operator steps are prepared in
`review-windows-acceptance.md`. Operator results remain Pending. Package creation
and a macOS source smoke test do not count as Windows acceptance. Provisioning the
review-data branch, production flags/records, credentials/rules and an authorized
production sharing check are also outstanding. IT-116 still requires unaided
nontechnical participant evidence. Delivery is not complete merely because local
code/tests work.

## Prepared package smoke evidence

Local development package: `/tmp/it113-windows-ready.zip`.
SHA-256: `1482fea9cefeeab37d18e50de0351488beb4e2bd587bbf8ad289e5910fc41f29`.
Every manifest file hash was verified against the ZIP. The manifest records base
`3a52f5c` and `working_tree_dirty: true`; this is an uncommitted development package.

The archive was extracted under `/tmp/it113 packaged source/survey-review`.
`uv sync --locked --offline` installed its editable source from that path with
spaces. Invoking its Python from `/tmp` verified packaged schema lookup, same-origin
built frontend assets, five synthetic flags, exact note scan/save, valid persisted
JSONL and upload to a disposable local bare remote. Node was not used for this
packaged-runtime check. Evidence setup: `/tmp/it113 package smoke complete`.
This is a macOS source-install smoke check, not Windows evidence.

The temporary browser tab and loopback developer server were stopped. No production
service, data or remote was touched. Branch changes remain local and uncommitted.

# Reviewer computer-use walkthrough — 19 October 2026

Execution type: **automated computer-use technical verification**. This report
does not claim execution by another person or a human TC-M07 pass. Human executor,
date and observed-result fields remain blank in the acceptance sheet.

Code exercised: pushed revision `d28624f`; subsequent follow-ups change tests/docs.
Application backend/frontend behavior is unchanged from that revision.
Platform: macOS, built React application in the in-app browser. This is not
physical Windows acceptance or IT-116's unaided Archives participant test.

## Observed steps and evidence

Prepared `/tmp/it115-tcm07-walkthrough` using `scripts/review_acceptance.py` from
`results/216412.jsonl` and its matching original PDF. The helper copied 75 records,
4,650 real-producer flags and the referenced PDF; sharing points only to that
sample's `remote.git`. No original records/scans or live review-data were written.

1. Opened the built reviewer at `http://127.0.0.1:8877`, entered
   `Integration walkthrough (automated)`, dismissed the welcome dialog and opened
   the first queue dwelling `09-0077-01`. The queue showed 75 dwellings and 4,650
   flags, with 62 pending fields on that card.
2. Opened **Weekly Rent**. The source was
   `423444_1973-0002-00001-00001.pdf`, original page **197**. Before deciding, the
   UI showed extracted **10**, **Readable**, confidence **0.91**, the middle-column
   textual locator, the original scan and active decision controls after loading.
   The scan's printed Weekly Rent cell also displays 10.
3. Entered **009** and saved. This was a deliberate exact-digit test edit in the
   disposable copy, **not** a claim that 009 is the source-correct transcription.
   The UI confirmed local save and marked the field CORRECTED. History retained
   machine 10, confidence 0.91 and the actual automated reviewer attribution.
4. Stopped the backend process and started a new process on the same disposable
   data checkout. Reloaded, signed in, selected Continue and reopened Weekly Rent.
   The screen retained 009, CORRECTED, machine original 10 and the correction
   history. The queue showed one decided field and 4,649 still to review.
5. Read the disposable JSONL export. It contains exact string `"009"`,
   `origin: "corrected"`, `original_value: "10"`, confidence 0.91, review state,
   timestamp and append-only before/after history. After restoring the selected
   field and its required schema upgrade in a comparison copy, the entire region
   equals the original. Original JSONL/PDF SHA256 hashes still match the manifest.

Evidence is local under `/tmp/it115-tcm07-walkthrough/evidence/`.

A retained local copy, including a provenance record with blank human-result
fields and evidence hashes, is at `data/it115-acceptance-evidence-20261019/` in
the code checkout. It is ignored local evidence, not committed archive imagery.

| Artifact | What it establishes |
| --- | --- |
| `01-queue.jpg` | Real generated queue and dwelling counts |
| `03-before-decision-details.jpg` | Machine value/status/confidence and decision controls |
| `03-before-decision-source-scan.jpg` | Matching original page/card |
| `03-before-decision-full-page.jpg` | Additional full-page context |
| `04-correction-input.jpg` | Exact typed digits in correction input |
| `04-saved.jpg`, `04-saved-field.jpg`, `04-saved-history.jpg` | Saved state, original and audit |
| `05-reopened-after-restart.jpg`, `05-reopened-history.jpg`, `05-history-audit.jpg` | Screen and audit after a real process restart |
| `05-export.json` | Exported field, actual attribution and unchanged-source/other-record checks |

These screenshots are technical evidence from this automated run. A human may
use the sample and instructions to repeat the test, but must record their own
execution rather than attribute these actions to themselves.

## Where and what to write after a human run

In the Product [Test Cases](https://linear.app/um-it-project/document/test-cases-648649f503b7) document, fill TC-M07's actual executor/date/result
and attach evidence for steps 3, 4 and 5. Add a dated result to the [Test Report](https://linear.app/um-it-project/document/test-report-08102026-81352fbbbe45)
and link it from IT-115. The corresponding local draft is the **Proposed dated
Test Report addendum** in [proposed updates](it115-proposed-updates.md).

Use this template only after that person actually performs the check:

> TC-M07 — [PASS/FAIL]. Executed by [actual name, not the code author] on
> [date/time] using [commit and any working-diff identifier], [OS/browser] and
> [disposable sample/manifest]. Opened [region/record/field, original PDF/page].
> Before deciding, verified the source scan, extracted [value], status [status]
> and confidence [score]. Saved [test edit or source-verified correction], then
> reopened/re-exported and observed [actual result]. Evidence: [step-3 screenshot],
> [step-4 screenshot], [step-5 screenshot and export]. Failures/follow-ups: [actual
> observations, or none].

Until that execution, write: **“Automated computer-use walkthrough passed;
human TC-M07 execution pending.”** Do not fill in a human name or pass result
from this run. Jacob's physical Windows check is the final separate handoff in
the acceptance document, with his actual results to be recorded afterward.

A fillable local copy of the human result template is at
`data/it115-acceptance-evidence-20261019/human-result-template.md`. A fresh unedited
sample is prepared at `/tmp/it115-human-ready-20261019` and open at the sign-in
screen. Use that new sample for the actual human run; the walkthrough sample
above intentionally contains the `009` test edit.

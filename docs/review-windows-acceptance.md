# Windows review installation and operator acceptance

Status: installation/runbook prepared; native Windows and unaided nontechnical
usability acceptance have **not** been performed. Developer tests, local macOS
checks and Windows CI are separate evidence. Record actual results below.

## Build and deliver (developer)

From the IT-113 follow-up source with the IT-115 stack integrated:

```sh
uv sync --locked
cd frontend
npm ci
npm test
npm run build
cd ..
uv run python scripts/prepare_review_release.py /tmp/survey-review-windows.zip
```

Keep frontend/dist stable during backend tests. Deliver the ZIP privately to the
operator. It contains an editable source installation, schema, locked Python
dependencies, built frontend, launcher, synthetic helper and this runbook. It
excludes scans, extracted results, `.env`, `.git`, credentials, Node dependencies
and Python virtual environments. RELEASE-MANIFEST.json hashes source and assets;
`base_revision` and `working_tree_dirty` distinguish a developer working copy
from a committed release. The builder must rebuild frontend immediately before
packaging. This is a local package, not a published release or deployment approval.

## Install (operator, Command Prompt)

Install Git and uv from their approved installers. Extract the package to
`C:\Survey Review\survey-review`. Node is not required on the reviewer's machine.
In Command Prompt:

```bat
cd /d "C:\Survey Review\survey-review"
uv sync --locked
uv run survey review --help
uv run python scripts\review_demo.py "C:\Survey Review Test\acceptance"
```

The last command creates a new disposable synthetic data checkout and local bare
remote and prints a launch command. Use that command first. Do not reuse an
existing directory. No Gemini key is needed. Initial dependency installation
needs network/cache access; ordinary launch uses the installed virtual environment.

For approved real review, configure an independently provisioned data checkout
on `review-data`, validated extracted JSONL, verified supplied flags and scans.
Until IT-109's merge is verified, use manual flags only. In the same console:

```bat
set "SURVEY_REVIEW_SCAN_ROOT=C:\Survey Scans"
set "SURVEY_REVIEW_DATA_CHECKOUT=C:\Survey Review Data"
set "SURVEY_REVIEW_FLAGS=C:\Survey Review Data\manual-flags.jsonl"
set "SURVEY_REVIEW_CACHE=C:\Survey Review Cache"
set "SURVEY_REVIEW_PORT=8765"
uv run survey validate-results "C:\Survey Review Data\results"
scripts\review.cmd
```

Use actual paths. These session variables are not permanent. For a shortcut,
put the same values in the source root's `.env` as `NAME="C:\path with spaces"`,
then create a shortcut to the absolute `scripts\review.cmd` path. Keep cache
outside both code and data roots. The data checkout must be a real Git checkout
on the expected data branch, with commit identity and an authorized remote.
A production remote requires separately provisioned credentials and branch rules.

## Acceptance on disposable data

Record Windows version, package hash, manifest revision/dirty state, browser,
operator, date, commands, results and any error text. Never test failure scenarios
on the production data checkout. Stop with Ctrl+C and wait for the backend to exit
before changing fixture paths or permissions.

1. **Paths/configuration:** install and create the synthetic demo in the paths with
   spaces above. Launch through `review.cmd` with the demo's printed arguments.
   Confirm browser opens only after readiness at `http://127.0.0.1:8765` (or the
   printed port), sign in, and record `/api/health` readiness. Recheck after
   changing the shortcut's working directory; the launcher sets the source root.
2. **Scans and navigation:** open each supplied coding/front/back flag and compare
   the PDF basename and original one-based page with the source PDF. Verify zoom,
   pan, magnifier and every queued card tab. A missing/failed scan must disable
   decisions and remain visible as unresolved. Restore the file and reload.
3. **Actions/undo:** on numeric fields correct to `009`; on supported text fields
   correct to `Café — 王` plus a second line. Use Accept, correction, Nothing written,
   and Cannot read, each followed by history inspection and undo. Accept must retain
   a stored `damaged` status; Cannot read explicitly produces `illegible`. No
   Damaged action exists. Identity/negated fields permit Accept only. The synthetic demo supplies both coding and text flags.
4. **Restart:** save numeric and text decisions, stop, relaunch, re-enter name.
   Confirm exact values, history, reviewer, time and undo survive. Validate the
   copied results again. Closing the browser does not stop the backend.
5. **Permissions/lock/port:** on disposable data deny write permission to the
   results directory, attempt a save, and confirm the old bytes and draft remain;
   restore permission. Start a second backend on the same checkout and confirm a
   writer-lock error. Start another checkout on the occupied port and confirm a
   clear port error. Stop/restart the first backend to confirm lock release.
6. **Offline sharing:** stop, rename the demo's `remote.git`, relaunch, save,
   request Share now, and confirm local retention plus upload failure. Restore the
   remote while stopped, relaunch and share; confirm Uploaded. Check restart also
   retains any unpushed commit. Save & Exit must distinguish local save from upload.
7. **Same-region conflict:** clone the disposable remote twice on `review-data`.
   Make different commits to the same region in both copies (even on different
   fields), share A then B. B must report manual reconciliation and retain its
   local data/commit. Disjoint-region sharing is tested separately by CI.
8. **Human usability:** let an unfamiliar operator complete the steps without
   coaching; record misunderstandings and IT-116 findings separately. A developer
   passing the technical checklist does not establish unaided usability.

The synthetic demo supplies five manual flags, including its single survey front
on page 3 and interview notes on page 4. Its two households do not claim individual
ownership of the dwelling note. The printed scan text is explicitly synthetic.

Front values require exactly one verified front. Notes require unique front/back
ownership; no household attribution is guessed for a multi-household dwelling.
Person fields, ambiguous fronts and coding-back fields cannot be edited.

## Operator evidence (fill after performing)

| Evidence | Actual result |
| --- | --- |
| Operator/date/Windows/browser | Pending |
| Package hash/manifest revision/dirty state | Pending |
| Installation and paths with spaces | Pending |
| Launch, scan comparison and missing scan | Pending |
| All actions, exact Unicode/multiline/zeros, undo | Pending |
| Stop/restart and JSONL validation | Pending |
| Permission, lock and port failures | Pending |
| Offline recovery and sharing | Pending |
| Same-region conflict retains data | Pending |
| Unaided usability/IT-116 findings | Pending |

Attach actual observations, error messages and evidence paths. Mark a check failed
or not performed when appropriate. Do not turn unperformed steps into a pass.

### Exact disposable conflict setup

Before the competing saves, clone B from the demo's local remote:

```bat
git clone --branch review-data "C:\Survey Review Test\acceptance\remote.git" "C:\Survey Review Test\data B"
git -C "C:\Survey Review Test\data B" config user.name "Windows acceptance B"
git -C "C:\Survey Review Test\data B" config user.email "acceptance-b@example.invalid"
```

Open two Command Prompt windows in `C:\Survey Review\survey-review`. In A run:

```bat
scripts\review.cmd --scan-root "C:\Survey Review Test\acceptance\scans" --data-checkout "C:\Survey Review Test\acceptance\data checkout" --flags "C:\Survey Review Test\acceptance\flags.jsonl" --cache "C:\Survey Review Test\cache A" --port 8765 --sync-interval 3600
```

In B run the same command with data checkout `C:\Survey Review Test\data B`,
cache `C:\Survey Review Test\cache B`, and port `8766`. Sign into both. In A
correct household 1 rent; in B correct household 2 rent **before sharing A**.
Both changes are in `results/demo.jsonl`. Share A, then Share B. Record B's
same-region conflict and preserved local field/history. Stop both. Inspect:

```bat
git -C "C:\Survey Review Test\data B" status --short
git -C "C:\Survey Review Test\data B" log --oneline -3
```

Do not resolve this test using force-push/reset. Preserve both disposable copies
as evidence; manual reconciliation tooling is outside this implementation.

The release helper refuses a dirty working tree by default. Commit the source
before packaging; for a deliberate development bundle, pass `--allow-dirty`.
The manifest records the base revision and whether uncommitted changes were included.

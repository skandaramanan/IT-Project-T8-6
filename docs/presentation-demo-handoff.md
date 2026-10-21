# Portable full-corpus reviewer demo: MacBook handoff

## Purpose and reset contract

Use branch `presentation-demo-review-tool`, based on
`skandar/it-115-reviewer-screen-usability-fixes` at `fd5523d`.
The launcher runs the reviewer locally against **copies of the full top-level
regional dataset**, with sharing directed exclusively to a newly created local
bare Git remote. It does not require Gemini, Drive API or GitHub sharing credentials.
GitHub access is needed to obtain this private repository.

**Every launch starts fresh.** It creates a unique `run-*` directory, copies the
source records and scans, regenerates flags, creates a new one-commit
`review-data` branch and local `remote.git`, and uses a new cache. Previous demo
decisions, commits, cookies/sessions and remote history are not reused. Baseline
review decisions already present in the source records remain part of the seed;
this tool does not strip or fabricate extraction/review evidence.

Previous runs remain on disk for inspection; they do not affect later launches.
Stop a running demo with Ctrl+C before launching again. The launcher holds a
per-sandbox-root lock and checks the port before preparing data. No automatic
process killing or deletion of user directories is performed.

## First setup on another Mac

Install Git (Apple Command Line Tools are sufficient), uv, and Node.js
**22.12+ within 22.x, or 24+**, including npm. Use official installers or your
normal package manager. `uv sync --locked` provisions the project's Python 3.12
environment. Both Intel and Apple Silicon Macs should create their own dependencies;
do not transfer `.venv`, `node_modules`, generated caches or old sandbox Git folders.

Clone the repository into a normal persistent folder, checking out this branch:

```bash
mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
git clone --branch presentation-demo-review-tool --single-branch \
  https://github.com/skandaramanan/IT-Project-T8-6.git
cd IT-Project-T8-6
bash scripts/setup_presentation_demo.sh
```

The branch must first be pushed to GitHub, or transferred as a Git bundle,
before the clone command can retrieve it. Setup installs locked Python and npm
dependencies and builds `frontend/dist` from this checkout. Rerun setup after
changing revisions or frontend dependencies. Setup itself does not reset data;
**the launch command resets the demo on every invocation**.

Separately obtain the survey scans from the team's authorised source. They are
not in Git. Keep the downloaded layout, including `metadata.csv`:

```text
Wilfred_Prest_Survey_Data/
  metadata.csv
  216412/
    423444_1973-0002-00001-00001.pdf
  216413/
    ...
```

The folder IDs, PDF basenames and JSONL region IDs must agree. Region display
names come from metadata's `Node ID` → `Node Title` (or `Title`) mapping.
Missing metadata leaves numeric IDs visible. Missing PDFs are listed in each
run's `manifest.json`; the affected cards show unavailable evidence.

## Start a fresh demo

From the code checkout, adjusting the scan path for this Mac:

```bash
bash scripts/launch_presentation_demo.sh \
  --scan-root "$HOME/Downloads/Wilfred_Prest_Survey_Data"
```

The default sandbox parent is `~/SurveyReviewDemoSandboxes`, outside the code
checkout. To choose another persistent location or port:

```bash
bash scripts/launch_presentation_demo.sh \
  --scan-root "/Volumes/Survey Scans/Wilfred_Prest_Survey_Data" \
  --sandbox-root "$HOME/Reviewer Demo Runs" \
  --port 8877
```

All paths support spaces. Optional switches:

- `--source-results /path/to/results`: seed from a different matching dataset.
  Default: this checkout's `results/`.
- `--prepare-only`: create a new sandbox without starting HTTP.
- `--no-browser`: leave browser opening to the presenter.

Allow several minutes for full-corpus copying, validation, flag generation and
backend startup. The console prints each stage and the sandbox directory.
The browser opener waits up to ten minutes for `/api/health` to report ready,
avoiding the review CLI's normal 30-second browser timeout. Open the printed
loopback URL manually if the browser does not open. Keep Terminal open.

The backend binds only to `127.0.0.1`; open it on the same MacBook. Enter a
reviewer name each run. Ctrl+C stops the server. Launch the same command again
to return to the baseline, with a new checkout and remote.

## Files and isolation

```text
~/SurveyReviewDemoSandboxes/
  .launch.lock
  latest-run.txt
  run-<unique>/
    data/             # standalone Git checkout, results/*.jsonl
    remote.git/       # local-only sharing destination
    scans/            # independent PDF copies plus metadata.csv
    flags.jsonl       # freshly generated assignment
    cache/            # created by the backend as needed
    manifest.json     # source paths, code revision, exclusions, missing PDFs
```

On macOS the script first attempts APFS copy-on-write PDF copies (`cp -c`).
Other volumes fall back to ordinary copies, which take longer and require space
for the corpus on every run. Copies remain independent: importing/downloading
scans or editing records in the app does not modify source files. Old run
directories can be removed manually after stopping the server if space is needed.
`latest-run.txt` identifies the most recently prepared run; it is not a resume pointer.

Only populated top-level `results/*.jsonl` files are seeded. Empty files are
reported and excluded from copies because the backend rejects them. Nested
alternative extractor datasets are not merged into the demo. Source files
remain unchanged. The generated assignment uses the existing coding-field
routing rules; survey-front/notes context is not claimed as an additional
generated assignment.

The launcher ignores inherited `GIT_*` and `SURVEY_REVIEW_*` overrides and global/system Git config
for demo operations, supplies local author details, disables commit signing
and hooks, and starts the backend from the new run directory rather than
loading the code checkout's `.env`. GitHub remotes, credentials and prior Git
history are not copied into the data checkout. The code checkout retains its
ordinary origin and history.

## Agent instructions and verification

1. Read this handoff and confirm the requested branch/revision. Keep unrelated
   user changes intact; do not switch branches over tracked local edits.
2. Ask only for paths/access that cannot be discovered locally. Never copy API
   keys or another Mac's environment folders. Use setup, then the launcher.
3. Verify `/api/health` reports `ready: true`, a region queue opens and an original
   scan loads. Inspect `data`'s origin to confirm it points to this run's local
   `remote.git`. Start with region `216412` for a demo smoke check.
4. Save a demo decision and optionally Share now. Stop with Ctrl+C, relaunch,
   and confirm the new run uses baseline records and exactly one seed commit.
5. Do not claim real participant usability acceptance from automated checks.
   Report missing/unreadable scan files rather than inventing evidence.

Useful checks from the code checkout:

```bash
uv run pytest tests/test_presentation_demo.py
uv run ruff check scripts/review_presentation_demo.py tests/test_presentation_demo.py
npm --prefix frontend test
```

The earlier full-corpus preview reported 44 populated regions and 78,444 flags;
these are observations, not hard-coded requirements. Counts change with seed
data. A previous download of region `216436` contained a truncated PDF; check
the copy on the new Mac rather than assuming its validity. The launcher copies
files and validates records, but does not pre-render every PDF page.

If launch reports an occupied port, stop the existing server or select another
port. If validation/flag generation fails, retain the printed error and failed
run directory; repair or choose the source dataset, then launch again. Never
repair original results automatically as part of a presentation setup.

This handoff describes Mac execution. The Python launcher uses POSIX file
locking and the shell entrypoints require Bash; Windows requires a separate port.

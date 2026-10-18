# Provisional GitHub review acceptance

This is an explicitly invoked integration test that writes review decisions to
`skandaramanan/IT-Project-T8-6:review-data`. It is not part of ordinary pytest or
CI. Keep this branch provisional and retain its history and failed checkouts.
Never use this tool against a production data branch: reruns undo active decisions
in its test fixtures through the application before exercising them again.

## Install and prepare

Run from the code checkout on `eric-zhang/review-github-acceptance`:

```sh
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend exec -- playwright install chromium
npm --prefix frontend run build
```

Commit the tooling first. Live preparation requires a clean working tree and pins
its HEAD; the application is run from that exact code checkout, independently of
the data branch. Ordinary Git/SSH authentication must already permit cloning and
direct pushes. No Gemini, OpenAI or Google Drive API key is required.

To automate Actions checks, add a token to the code checkout's gitignored `.env`:

```dotenv
GITHUB_TOKEN=your_token_here
```

An exported `GITHUB_TOKEN` or `GH_TOKEN` also works; existing environment values win.
Fine-grained tokens need access to this repository and Actions/Contents read.
GitHub currently restricts fine-grained tokens for repository collaborators; a
classic `repo` token can be necessary for a private repository owned by another
personal account, but grants broader access. See
[GitHub's token guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).
The token is only used for read-only REST calls, not Git pushes. Do not put it in
the data checkout, command arguments, reports or chat. Use a short expiry.

First test locally (loopback sockets and local subprocesses must be permitted):

```sh
uv run python scripts/review_github_test.py prepare /tmp/review-github-local --local
uv run python scripts/review_github_test.py run /tmp/review-github-local
```

The default real-scan root is
`/Users/ericzhang/Downloads/Wilfred_Prest_Survey_Data`; override with
`--scan-root /path/to/original/scans` during preparation. `--synthetic-only`
omits the real-data phase and cannot establish real-data acceptance.
Local preparation permits a dirty development tree; that is development evidence,
not evidence for a clean release revision.

For the live run, choose a new external workspace:

```sh
uv run python scripts/review_github_test.py prepare /tmp/review-github-live
uv run python scripts/review_github_test.py run /tmp/review-github-live
```

Preparation refuses an existing workspace or existing remote `review-data` branch.
It creates a separate provisioning clone based on the pinned code revision,
replaces its inherited `results/` tree with two synthetic regions and two complete
216418 dwellings, validates, commits and pushes once. It copies the original PDF
locally and hashes the source records/PDF. Scans, flags and evidence stay outside
the data checkout. It does not change main, branch protection, original scans or
original results. The synthetic queue is explicit, not confidence generated.

Do not delete/recreate a live branch to rerun. Reuse its workspace. The runner
checks repository identity and seed ancestry before using any clone. If code HEAD
changes after integration or a fix, commit a clean revision, then explicitly
revalidate and repin the existing workspace:

```sh
uv run python scripts/review_github_test.py repin /tmp/review-github-live
uv run python scripts/review_github_test.py run /tmp/review-github-live
```

Repinning validates current remote records with the new code and checks original
hashes before updating the local manifest. It records both code revisions and the
validated data SHA. It does not push, reset checkouts, change seed ancestry or
remove previous evidence. Do not edit the manifest to bypass these checks.

## Automated scenarios and reports

The API runner uses actual backend subprocesses and HTTP sessions. It verifies:

1. Exact numeric/text decisions, all actions, restart, progress, undo and no-op sharing.
2. Failed-push retention, restart with an unpushed commit and recovery.
3. Two independent reviewers saving/sharing concurrently in different regions,
   including both values and reviewer histories in a fresh clone and convergence.
4. Completion-triggered sharing and five-second periodic sharing.
5. Same-region conflict refusal and retained bytes/history after restart.
6. Original scan rendering, correction, restart, sharing and undo for the real sample.

Four Chromium tests then cover correction/upload, restart/undo, Save and Exit
with failed-upload recovery, and concurrent reviewers in different regions. Each
gets separate backend/data clones. Browser mutations use the UI; read-only API
and fresh-clone checks verify persistence. Private stdio control restarts processes
and injects failure; the application has no new test endpoints.

Default periodic sync is 3,600 seconds for controlled scenarios. Completion can
still trigger a push. The periodic scenario uses five seconds. Startup and
periodic checks allow 60 seconds; HTTP calls allow 120 seconds. Actions checks
allow ten minutes per checkpoint and verify exact SHAs, not merely the newest run.
Automatic test retries are disabled. A simultaneous test need not produce an
actual rejected push on every run; controlled Git regressions cover that path.

The printed `run-*/report.json` and `report.md` record pass/fail/blocked/not-run,
durations, commit SHAs, hashes and Actions URLs. Backend logs and preserved clones
are beside them. Browser screenshots/traces and JSON results are under
`frontend/test-results/` (ignored). Copy that directory beside the report if keeping
multiple browser runs. Open a failed trace with:

```sh
cd frontend
npx playwright show-trace test-results/CASE/trace.zip
```

`--skip-browser` runs only API scenarios. `--skip-ci` allows testing while CI
credentials are unavailable, but records GitHub validation as blocked and returns
nonzero. Local bare-remote runs record CI as not run. A passing local run does not
establish GitHub acceptance. Remote CI failure never triggers an automatic rollback.

The runner preserves work, restores its temporary push configuration and stops
child backends. Do not reset or force-push a failed clone. Uploaded and CI-passed
are separate assertions. Missing browser binaries, credentials, branch access or
required scans are blockers, not passes.

## Manual browser playbook

Create independent manual clones of the current test branch and print commands:

```sh
uv run python scripts/review_github_test.py manual /tmp/review-github-live
```

Run the two printed commands in separate terminals from the code checkout. They
use ports 8765/8766, separate caches and separate data checkouts. Use two browser
profiles or private windows, and names `Manual A` and `Manual B`. Each sign-in is
an unverified reviewer name, separate from Git commit identity. Dismiss first-use
help. Pick a different correction if a field already contains the proposed value.
The workspace `flags.jsonl` lists exact region/PDF/one-based page/field pointers.

| Check | Steps and expected observation |
| --- | --- |
| Scan and save | Select demo-a; Review/Reopen its dwelling. Compare synthetic scan/page. Correct Weekly Rent to `009`; verify Saved here and history. Leave other fields pending. |
| Text/actions | Use the survey back tab; correct notes to `Café — 王` followed by a second line. Exercise Accept, Nothing written and Cannot read on supported fields; inspect and undo each. |
| Restart | Stop A with Ctrl+C; relaunch the same command and re-enter the same name. Values, progress and history must survive. Closing a browser does not stop the backend. |
| Share/no-op | Share now. Record uploaded SHA and inspect a fresh clone. Share again without edits; no new commit should appear. |
| Undo | Reopen the edited field, choose Undo latest decision on this field, share and verify restored value plus append-only undo event in a fresh clone. |
| Failed upload | Stop A. Set its push URL to a nonexistent LOCAL path using the commands below. Restart, make a distinct correction, Save and Exit. The dialog must say decisions remain on this computer and sharing is unconfirmed. |
| Recovery | Stop A, remove the temporary push URL and restart. Share; the retained correction must reach GitHub. Save and Exit now confirms sharing. |
| Different regions | Start A/B from the same current tip. A edits demo-a and B edits demo-b before either shares; leave other fields pending. Share both near-simultaneously. A fresh clone must contain both values/histories. Share both again to receive the combined state. |
| Completion | In demo-b, decide every pending flag; completion should share without Share now. Confirm the remote SHA changes and its values match. |
| Periodic | Stop a backend, relaunch with `--sync-interval 5`, save while leaving its batch incomplete, and wait up to 60 seconds. Verify upload without Share now; restore 3600 afterward. |
| Same region | Use two NEW clones from the same tip. A changes one demo-a rent; B changes the other before either shares. Share A then B. B must require reconciliation and keep its values/history. Stop both and retain B as evidence. |
| Real sample | Use fresh clones; select 216418 and compare the exact original PDF/page. Correct a flagged rent, restart, share, verify remotely, undo and share again. No transcription-accuracy claim follows from this test. |

Failure injection changes ONLY A's printed disposable checkout. Substitute its
actual absolute path. Record any pre-existing push URL before changing it:

```sh
git -C "/path/to/manual-A-checkout" config remote.origin.pushurl /tmp/review-test-remote-that-does-not-exist.git
# After stopping A again, restore ordinary origin-based push behavior:
git -C "/path/to/manual-A-checkout" config --unset-all remote.origin.pushurl
```

Verify GitHub independently, keeping this inspection clone separate from A/B:

```sh
git clone --branch review-data git@github.com:skandaramanan/IT-Project-T8-6.git /tmp/review-inspection
git -C /tmp/review-inspection log --oneline -5
uv run survey validate-results /tmp/review-inspection/results
```

For each checkpoint, record the SHA, expected/actual values and reviewer history,
and the matching **Validate review data** Actions URL/conclusion. Test changes
must be limited to `results/<region>.jsonl` after provisioning. Treat network,
permission or branch-rule failures as blockers; do not change shared protection
rules as part of a test. Record screenshots of status/dialog failures without keys.

## Completion and boundaries

Full acceptance requires API scenarios, all four browser cases, unchanged original
source hashes and successful GitHub validation at the tested checkpoint SHAs.
Mark manual usability and scan-readability observations separately. Two local
processes simulate reviewer machines but do not establish Windows installation,
cross-browser compatibility, two-human usability, Drive download behavior,
full-corpus performance or production queue correctness. Retain the provisional
branch; production promotion and main integration are separate work. Rerun after
the underlying application branches integrate, recording the new application SHA.

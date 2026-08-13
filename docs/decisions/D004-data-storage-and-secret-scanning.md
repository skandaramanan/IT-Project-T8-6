# D004 — Data storage and secret scanning

**Status:** Accepted
**Date:** 2026-08-13
**Decided by:** Skanda Ramanan (P1 Foundations lead)
**Linear issue:** IT-36

## Context

Two questions had to be settled before extraction work starts, and they are the
same problem from two ends: what must never enter git, and what catches it when
someone puts it there anyway.

The scans are 6.4 GiB of region-batched PDFs, delivered by the Archives team
over AARNet FileSender on a transfer that expired on 27 August 2026. They need a
permanent home that all five of us can reach. Separately, if the extraction
spike (IT-37) lands on a hosted model, API keys appear in this project shortly
afterwards, and a key committed to a student repo is a bad afternoon.

## Decision

**Storage.** The scans live in a Google Drive folder shared with the five team
accounts, linked from the README. `data/` stays gitignored, including anything
derived from the scans. A five-record sample (20 images, 7.2 MB) is committed to
`tests/fixtures/` so tests have real input; the larger benchmark set stays in
Drive.

**Secret scanning.** gitleaks runs on every pull request, pinned to 8.30.1, as
the first step of the existing `check` job. It scans commit history rather than
the working tree, with `--redact` so a finding never lands in the build log.

## Alternatives considered

### Storage

**University OneDrive** — the obvious first choice, rejected on arithmetic: the
student allocation is 5 GB and the archive is 6.4 GiB.

**Leaving it on FileSender** — it is a transfer service, not storage. The link
expired 14 days after we received it, it is one-way, and it is bound to the
recipient's email, so the other four could not have used it.

**Git LFS** — versioning an immutable archive that will never change, and paying
bandwidth for it on every clone. Nothing about the corpus benefits from being in
the repo.

### Secret scanning

**GitHub's own secret scanning and push protection** — not available to us. It
is free on public repositories, but on private ones it requires GitHub Secret
Protection, a paid add-on on Team and Enterprise; user-owned private repos only
get it under Enterprise Managed Users. Confirmed against the API, which reports
scanning disabled on this repository.

**Making the repo public to get it free** — a real option rather than a silly
one. The source records are 1941–43 archival material that the client confirmed
is public with open access, so there is no data reason to stay private. Rejected
for now because it is a team and subject decision rather than a P1 tooling one,
and gitleaks costs less than that conversation. Left open below.

**`gitleaks-action`** — one YAML block, but it requires a licence key for
organisations. It works today on a personal repo and breaks the day this moves
under a University organisation.

**The gitleaks Docker image** — a `docker pull` on every run, and the convenient
tag is `latest`, which is not reproducible.

**`detect-secrets` as a uv dev dependency** — appealing, because it needs no
download and uv.lock would pin it alongside everything else. Rejected for the
`.secrets.baseline` file it requires, which has to be regenerated whenever
tracked files change. Recurring friction is worse than an occasional manual
version bump.

**A separate CI job** — would mean adding a second required status check to the
`main` ruleset. Keeping the scan inside `check` leaves branch protection exactly
as D002 set it up.

## Consequences

- No secret reaches `main` without CI going red, and because the scan is the
  first step it fails before we pay for dependency installation.
- History scanning needs `fetch-depth: 0`, so checkout is no longer shallow.
  Negligible here, and it stays negligible as the fixtures grow: gitleaks skips
  binary files, so what it actually reads is tens of kilobytes of text and the
  whole history scans in well under a second.
- The scanner is fetched at run time from a pinned GitHub release over HTTPS,
  with no checksum verification. That trusts the release artifact. Pinning the
  version at least means it cannot change under us silently, and adding a hash
  is cheap if this ever guards something more valuable than a student repo.
- The gitleaks version is pinned and bumps by hand. A scanner that never updates
  slowly stops recognising new credential formats.
- **This is detection, not prevention.** GitHub's push protection blocks a
  secret before it is pushed; gitleaks catches one at pull-request time, when it
  is already sitting in a branch on GitHub. Any key that reaches a branch should
  be treated as compromised and rotated, not merely deleted in a follow-up
  commit.
- The Drive folder is now the only copy of the scans, and its redundancy is
  whatever Google provides. If the Archives team can host a durable copy, ask.

## Revisit if

The repo moves under a University GitHub organisation with Secret Protection
licensed, or the team decides to make it public. Either would give us GitHub's
native scanning with push protection, which prevents the leak rather than
reporting it after the fact, and would make the gitleaks step redundant.

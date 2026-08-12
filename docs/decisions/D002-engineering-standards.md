# D002 — Engineering standards: branching, review, done

**Status:** Accepted
**Date:** 2026-08-11
**Decided by:** Team, at the standup of 11/08/2026
**Linear issues:** IT-29, IT-43

## Context

Roles and Responsibilities already promised branch-per-issue and no self-merges,
and pointed at a Definition of Done that did not exist. Nothing was enforced, so
the process was whatever each person remembered.

## Decision

- `main` is protected by a repository ruleset: pull request required, one
  approving review, no bypass actors, force pushes and deletions blocked.
- Branches use the name Linear generates, so branch, PR and issue link
  themselves together.
- Commits are `<scope>: IT-<number>: <description>`, imperative, one logical
  change each.
- A six-item Definition of Done applies to every ticket, on top of that ticket's
  own acceptance criteria.
- Merging a PR closes its Linear issue automatically, so whoever merges is the
  one closing it. Tickets without a PR are moved by their assignee.

## Alternatives considered

**Convention without enforcement** — what we had. It relies on five people
remembering, and the first missed review is invisible.

**Requiring two approvals** — too heavy for a team of five where everyone is
also writing their own tickets. One reviewer catches the mistakes that matter.

**Letting admins bypass the ruleset** — GitHub offers this by default. Rejected:
the repo owner is the person most likely to push to `main` out of habit, so an
exemption would defeat the rule for exactly the wrong person.

## Consequences

- No work reaches `main` without another pair of eyes.
- The Linear ↔ GitHub trail becomes the evidence for individual contribution,
  which is assessed.
- Small extra friction per change: a branch and a PR even for a one-line fix.

## Revisit if

Review latency starts blocking people — a teammate waiting a day for approval on
a typo is a worse outcome than the typo.

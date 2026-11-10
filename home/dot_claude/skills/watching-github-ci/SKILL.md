---
name: watching-github-ci
description: Use when waiting on GitHub Actions or pull request checks to finish, babysitting CI, polling a workflow run or deployment, or after a "403 API rate limit exceeded for user ID" error from gh.
---

# Watching GitHub CI

## Overview

Every token acting as this user (gh, Coder Agents, editors, other sessions) shares one REST budget of 5,000 requests an hour.
`gh run watch` polls REST every 3 seconds by default, with several requests per poll, so one watcher can spend 60–100 requests a minute and a few of them exhaust the budget for everything else.
GraphQL has its own separate budget, and plain `git` uses neither.

## How to wait on CI

Wait on a pull request's checks with GraphQL, every 60 seconds:

```bash
gh pr checks <pr> --repo <owner>/<repo> --watch --interval 60 > /dev/null 2>&1; gh pr checks <pr> --repo <owner>/<repo>
```

Wait on one workflow run with REST only when no pull request covers it, and always pass the interval:

```bash
gh run watch <run-id> --repo <owner>/<repo> --interval 60 --exit-status > /dev/null 2>&1
```

Read state once, rather than in a loop, with the GraphQL-backed commands: `gh pr view <pr> --json statusCheckRollup,mergeStateStatus,reviewDecision`.

Before a long wait, check the budget (this call is free): `gh api rate_limit --jq '.resources.core | {remaining, reset: (.reset | todate)}'`.

## Quick reference

| Command | Budget | Default poll |
| --- | --- | --- |
| `gh pr checks --watch` | GraphQL | 10 s, use `--interval 60` |
| `gh pr view --json …` | GraphQL | one call |
| `gh run watch` | REST | 3 s, use `--interval 60` |
| `gh run view`, `gh run list`, `gh api repos/…` | REST | one call each |
| `git fetch`, `git push`, `gh repo clone` | neither | — |

## When the budget is gone

A `403 API rate limit exceeded for user ID` error means REST is exhausted until the reset time that `gh api rate_limit` prints.
Stop REST calls, switch to GraphQL (`gh pr view`, `gh pr checks`, `gh api graphql`), and schedule a single re-check after the reset instead of retrying.
A `gh auth status` that says the keyring token is invalid during an outage is the same 403, not a bad token.

## Common mistakes

- `gh run watch` or `gh pr checks --watch` with no `--interval`.
- A shell loop around `gh run view` or `gh api` with a short `sleep`.
- Several agents each watching the same run; one watcher is enough.

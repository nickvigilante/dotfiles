---
name: triaging-inbox
description: Use when the user asks to triage, clean up, or summarize their email, shrink their unread count, get a view of their day, or decide which GitHub pull request notification emails need review, were merged, or can be marked read.
---

# Triaging the inbox

## Overview

Scripts do the data work and Claude does the judgment.
`triage.py` reads the unread Gmail threads, asks the GitHub API about every pull request in them, applies the user's rules, and prints one line per item plus a plan.
Claude presents the brief, handles the few items that need thought, and marks threads read only after the user confirms.

## Workflow

1. **Fetch unread threads.**
   Call Gmail `search_threads` with query `is:unread in:inbox`, `pageSize` 50, and view `THREAD_VIEW_MINIMAL`.
   If the result is saved to a file because it is large, use that path.
   Otherwise write the JSON to the scratchpad.
   If `resultCountEstimate` exceeds what came back, page with `pageToken` and combine the pages.
2. **Run the triage.**
   `triage-inbox inbox --threads FILE --format both`
   It prints the brief and a final `PLAN` line with the thread ids to act on.
   It is read-only and takes about 20 seconds for 25 pull requests.
   For one-off questions about a PR, run `triage-inbox pr owner/repo#N` instead of making several API calls by hand.
   Always use the `triage-inbox` command, never `python3` on the scripts, because only the command is on the permissions allowlist.
3. **Present the brief verbatim.**
   Add today's calendar from Google Calendar `list_events` above it, one line per event.
   Do not expand the lines or re-list what the script already printed.
   Non-PR mail stays unread, but tell the user what is in it: read each id in `non_pr_thread_ids` with Gmail `get_thread` (`PLAIN_TEXT`) and add a one-line gist under its line.
   Read them in parallel, with subagents when there are more than about five, and name any sender that recurs, since the user may filter or unsubscribe those in Gmail.
4. **Handle P1 and P2 with judgment.**
   For a P1 docs-only PR, read the docs diff and report findings.
   For P2 drift, say what could not be verified (the unchecked item, or the failed or missing doc-check run) and offer a Documentation-team Linear ticket.
   Create nothing without asking.
5. **Apply after confirmation.**
   Ask once for `mark_read_thread_ids`, then separately for `collapse_read_thread_ids` and `suggested_read_thread_ids`.
   A go-ahead the user already gave, such as "just do it", counts as confirmation for what they covered.
   Mark read by removing the `UNREAD` label with `unlabel_thread`, one call per thread, in parallel.
   Retry a failed call once and report any that still fail.
   For PRs in `unsubscribe_candidates` that the user approves, run the GraphQL `updateSubscription` mutation with state `UNSUBSCRIBED`.
   It needs the `notifications` token scope; if it is missing, tell the user to run `! gh auth refresh -h github.com -s notifications`.
   Unsubscribing still lets direct mentions and review requests through, and it is not part of the `triage-inbox` command, which stays read-only.
6. **Report the result** as counts plus any thread ids left unchanged.

## The rules

First match wins for each thread.

| Order | Condition                                                                               | Action                                |
|-------|-----------------------------------------------------------------------------------------|---------------------------------------|
| 1     | Every unread message only announces new commits, even if a commit title names the user  | Read, always                          |
| 2     | A message names the user (`@nickvigilante`, `Nick`, mention)                            | Keep unread                           |
| 3     | A message is a doc-check update                                                         | Keep unread                           |
| 4     | GitHub facts are missing or were only partly fetched                                    | Keep unread; never guess              |
| 5     | PR is merged and its docs could not be verified as complete (drift)                     | Keep unread, rank P2                  |
| 6     | The only unread messages are `Docs preview` checklists                                  | Read                                  |
| 7     | Message is "merged" or "closed", or the PR is already one                               | Read; notify (all merges, own closes) |
| 8     | Anything else on an open PR                                                             | Keep unread, rank by bucket           |

On the user's own PRs:
approvals are read once the PR is merged or closed, but a human comment on the same PR stays unread, and every approval is listed in the **Your PRs were approved** section.

Several threads about one PR collapse to the newest; the rest are proposed as read.
Every unread thread ends up in exactly one of keep, read, or folded, and the brief ends with a check line that proves it.

## Never

- Mark anything read before the user confirms the plan or has told you to go ahead.
- Treat a doc-check run that failed or never ran as "nothing flagged"; on a merged PR that is drift.
- Edit `settings.json` to allow the script; permission changes go through `permissions.toml`.

See `reference.md` for the buckets, the fields `gh_pr.py` returns, known limits, and open questions.

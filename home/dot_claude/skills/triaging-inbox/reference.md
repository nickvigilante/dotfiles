# triaging-inbox reference

## Buckets

Kept items are ranked in this order.
Within a bucket, PRs with hand-written docs come first, then newest activity.

| Bucket | Meaning                                                                                       |
|--------|-----------------------------------------------------------------------------------------------|
| P1     | Open, every changed file is under `docs/`, and the user is the only pending reviewer          |
| P2     | Merged, and the docs could not be verified as complete: unchecked doc-check items, or a doc-check that failed, never ran, was skipped, or was still running (`DRIFT`) |
| AP     | PRs the user authored that were approved; merged ones are shown with `[marked read]`          |
| P3     | Open PR whose doc-check comment has unchecked items                                           |
| P4     | The user's own PRs                                                                            |
| P5     | A message names the user                                                                      |
| P6     | Review requested of the user and not yet done, or re-requested after the user's review        |
| GEN    | Open, only generated docs changed, doc-check passed: suggested read, never automatic          |
| P7     | PRs the user already reviewed that have new activity                                          |
| P8     | External contributors                                                                         |
| P9     | Everything else, including PRs whose GitHub facts could not be fetched                        |
| NP     | Not pull requests: people first, then calendar, Linear, shares, automated mail                |

## Brief line legend

`ref title | author (ext) | state [stacked] | docs tag | dc:status(open items) | role; reviewed; draft-review | DRIFT | N threads->1`

- **Docs tag:** `DOCS-ONLY/hand`, `code+docs/gene`, `code+docs/both`, or `code`.
- **dc:** `passed`, `flagged`, `resolved`, `failed`, `never_ran`, `skipped`, `running`, or `n/a` outside `coder/coder`.
- **role:** `codeowner(requested)`, `codeowner(files)`, `codeowner(email)`, `requested`, `author`, `mentioned`, `participant`, or `subscribed`.
- **ext:** the author is not an owner, member, or collaborator of the org.
- `coder/coder` is shortened to `coder`; other repos keep their full name.

## What counts as generated docs

The patterns live in `scripts/triage_config.json`.
They mirror the generated targets in the `coder/coder` Makefile: `docs/reference/api/`, `docs/reference/cli/`, `docs/manifest.json`, `docs/manifest/generated/`, `audit-logs.md`, and `api-key-scopes.md`.
When the Makefile gains a new generated docs target, add its pattern there.
`test_triage.py` fails if `audit-logs.md` stops being treated as generated.

## Codeowner status

- `codeowner(requested)`: GitHub's own `reviewRequests.asCodeOwner` flag is true for the user or one of their teams.
  The API only reports it while the request is pending, so it disappears once the user reviews.
- `codeowner(files)`: the repo's root `CODEOWNERS` assigns at least one changed file to the user or one of their teams (last matching rule wins).
- `codeowner(email)`: only the email text said "as a code owner"; used when neither of the above applies.
- In `coder/coder` the user owns `docs/`, so any PR that touches docs, even only generated docs, requests them.
  `codeowner_only_via_docs` in the facts says when that is the only reason.

## Known limits

- **Names are matched in snippets**, not full bodies.
  A name past the snippet cut-off is missed unless GitHub's reason address is `mention` or `team_mention`.
- **Manual doc-check runs do not attach to the PR.**
  After a `workflow_dispatch` run, the PR still shows the old failed check; a flagged result still appears as a comment.
  Re-run the failed job from the PR's original run to clear it.
- **Stacked PRs** are marked `stacked`; their "merged" state means merged into the base branch, not `main`.
- **Unsubscribe is a candidate list only.**
  The `gh` token has no `notifications` scope, and both the REST subscription endpoint and the GraphQL `updateSubscription` mutation require it.
  Granting it is `gh auth refresh -h github.com -s notifications`, which needs a browser, so the user runs it.
- **Read-only by design.**
  The scripts write no files and only issue GET requests and one GraphQL query through `gh api`, so the command is safe to allow without prompting.
- **Allowlist.**
  `triage-inbox inbox *` and `triage-inbox pr *` are on the generated allowlist.
  They take effect after the change merges and `chezmoi apply` runs; until then each run prompts.
  The wrapper (`~/.local/bin/triage-inbox`) pins the interpreter and script path and refuses every option except its own, so `python3` itself stays unapproved.

## Settled decisions

- A "new commits" email is always read, even when a commit title names the user.
  Every other message that names the user stays unread.
- Docs preview checklists are read.
- Approvals of the user's own PRs are read once the PR is merged or closed, a human comment on the same PR stays unread, and every approval appears in the approved section.
- Drift is any merged PR whose docs could not be verified as complete.

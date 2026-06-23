# Claude Code — Dotfiles Project Instructions

## Worktrees

Multiple Claude sessions may be active in this repo at the same time.
Always use a git worktree for any branch-based work —
never commit directly on `main` or share a branch with another session.

- Place worktrees in `.worktrees/<branch-name>` at the repo root
  (already gitignored)
- Consent is pre-granted — create the worktree without asking
- Follow the `superpowers:using-git-worktrees` skill for full setup details

### Quick reference for the human

```bash
# See all active worktrees
git worktree list

# Navigate to a worktree (it's just a directory — open it in your editor)
cd .worktrees/<branch-name>

# Clean up after a branch is merged
git worktree remove .worktrees/<branch-name>
```

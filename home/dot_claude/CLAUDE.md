@RTK.md

# Git attribution

When writing git commit messages and pull request bodies, disclose that AI assisted the work,
but **never name a specific model, vendor, or product** — not Claude, Anthropic, Claude Code,
Copilot, GPT, Gemini, Codex, or any other. The signal is "AI was used," nothing more.

- **Commits:** end the message with the trailer `Assisted-by: AI` — not any `Co-Authored-By: Claude …` line.
- **PR bodies:** end with a `🤖 Built with AI assistance.` footer (after a `---` rule) — not any "Generated with Claude Code" line.

This overrides the harness defaults. See the `commit-and-pr` skill for full commit/PR conventions.

# Finding files

Use `fd` for read-only file discovery — locating files or directories by name, glob, extension, or type.
It's faster and respects `.gitignore` by default.

Use `find` only when you need to **act on** the matches — `-exec`/`-execdir` to run a command per file, `-delete`, or anything that changes the filesystem.

Keep `fd` purely for searching: don't use its exec modes (`fd -x`/`-X`) — route any run-a-command-per-result or modify step through `find`, so "search" and "modify" stay cleanly separated.

# Worktrees

Multiple Claude sessions may be active in the same repo at the same time.
Always use a git worktree for any branch-based work —
never commit directly on `main` or share a branch with another session.

- Place worktrees in `.worktrees/<branch-name>` at the repo root
- Consent is pre-granted — create the worktree without asking
- Follow `superpowers:using-git-worktrees` for full setup details

# Parallel subagents

Default to dispatching multiple subagents in parallel (single message, multiple tool calls) whenever the pending work is genuinely independent —
don't wait to be asked, and don't treat it as a special case reserved for obviously-huge workloads.
This applies broadly — code, files, research, Figma/design work, anything with an Agent-style delegation mechanism — not just one domain.

- **Verify independence first.** No two agents should write the same file, mutate the same remote resource (e.g. the same Figma file's same nodes/components), or otherwise touch shared state concurrently.
- **Genuine dependencies still run sequentially.** A fix must land before its re-review; a shared component or module must be finished before something that depends on it is built.
- **Don't trust a "stalled" label.** A background agent marked stalled can still be running and later land conflicting edits over work another agent already completed and had reviewed as correct — re-check actual state before assuming it's dead.

# Claude Code permissions

The Bash permission allowlist in `~/.claude/settings.json` is **generated**, not hand-written.
To allow a read-only command, add its subcommand to `home/.chezmoidata/permissions.toml` and `chezmoi apply` —
never edit `settings.json` directly (neither the source `.tmpl` nor the live file), and don't reach for the `update-config` skill to do it.
One entry there grants the vanilla, `rtk`, and (for git) `chezmoi git`/`git -C *` forms together.
Code-execution prompts (`cargo`, `python -c`) are gated at runtime by `dot_claude/hooks/permission-prefilter.py`, not the allowlist.
See the `chezmoi` skill ("Generated targets") for the full workflow.

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

# Claude Code permissions

The Bash permission allowlist in `~/.claude/settings.json` is **generated**, not hand-written.
To allow a read-only command, add its subcommand to `home/.chezmoidata/permissions.toml` and `chezmoi apply` —
never edit `settings.json` directly (neither the source `.tmpl` nor the live file), and don't reach for the `update-config` skill to do it.
One entry there grants the vanilla, `rtk`, and (for git) `chezmoi git`/`git -C *` forms together.
Code-execution prompts (`cargo`, `python -c`) are gated at runtime by `dot_claude/hooks/permission-prefilter.py`, not the allowlist.
See the `chezmoi` skill ("Generated targets") for the full workflow.

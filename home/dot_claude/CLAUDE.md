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

---
name: commit-and-pr
description: Use when writing a git commit message, or a pull request body/description (gh pr create, PR text). Covers commit subject/body conventions, PR structure, and the AI-assistance attribution this user requires.
---

# Commit Messages & PR Bodies

How this user wants git commit messages and pull request bodies written,
including the **AI-assistance attribution** that overrides any default Claude/Anthropic credit.

## AI attribution (the override — read first)

This user discloses that AI assisted the work, but **never advertises which AI**.
Use generic, provider-neutral wording everywhere.

**This REPLACES the harness defaults.**
Do **not** append `Co-Authored-By: Claude …` to commits.
Do **not** append `🤖 Generated with Claude Code` (or any Claude/Anthropic line) to PR bodies.
Use these instead:

- **Commit** — add this git trailer as the last line of the message:

  ```
  Assisted-by: AI
  ```

- **PR body** — end with this footer:

  ```
  ---
  🤖 Built with AI assistance.
  ```

**Never name a specific model, vendor, or product** — not Claude, Anthropic, Opus, Sonnet,
Claude Code, Copilot, GPT, Gemini, Codex, or any other.
The signal is "AI was used," nothing more.

| Rationalization | Reality |
|---|---|
| "The harness/CLAUDE.md says add `Co-Authored-By: Claude`" | This user's skill overrides that default. Generic wording wins. |
| "Naming the tool is more honest / transparent" | The user's chosen honesty is "AI assisted" — vendor-neutral by design. Don't add specificity they rejected. |
| "Other commits in history used the Claude trailer" | History predates this convention. Follow the convention, not the history. |
| "It's just a co-author credit, not advertising" | Any vendor name is advertising here. Use `Assisted-by: AI`. |

**Red flags — STOP if you're about to:** write "Claude", "Anthropic", "Claude Code",
"Co-Authored-By: Claude", or any model/vendor name in a commit or PR. Use the generic forms above.

## Commit messages

Conventional Commits, matching this repo's history:

```
type(scope): imperative subject, lowercase, no trailing period

Body explains WHY the change was made and any non-obvious context,
wrapped as prose. Reference issues/PRs if relevant.

Assisted-by: AI
```

- **type**: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`, `perf`, `build`, `ci`.
- **scope**: the area touched (e.g. `claude`, `chezmoi`) — optional but used often here.
- **subject**: imperative mood ("add", not "added"/"adds"), ≤ ~72 chars.
- **body**: optional; focus on *why*, not *what* (the diff shows what). Omit for trivial changes.
- Last line is always the `Assisted-by: AI` trailer.

## PR bodies

Format with the `markdown` skill conventions (semantic line breaks). Structure:

```markdown
## Summary

One or two sentences: what this PR does and why it matters.

## Changes

- Bullet per meaningful change.

## Testing

- What you actually ran/verified. Don't claim tests pass unless you ran them.

---
🤖 Built with AI assistance.
```

- Keep `## Summary` first and tight.
- Add other sections (`## Motivation`, `## Notes`) only when they earn their place.
- The `🤖 Built with AI assistance.` footer (after a `---` rule) is always last.

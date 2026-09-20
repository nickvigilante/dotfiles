---
name: markdown
description: "Use whenever writing or editing ANY Markdown — READMEs, docs/, PR descriptions, notes, SKILL.md files, GitHub issues/comments. Enforces this user's conventions: one sentence per line (never column-wrapped, never clause-split) and clean CommonMark/GFM syntax."
---

# Writing Markdown (this user's conventions)

## One sentence per line (the important one)

Exactly one full sentence per line — NOT SemBr: never split a sentence at clause boundaries, however long it runs.
Let the renderer soft-wrap; never hard-wrap prose at 80/100 columns.

Why: prose changes then produce **one-line diffs** at the sentence that changed, instead of reflowing a whole paragraph.
Reviews, `git blame`, and Vale-style OneSentencePerLine linting all assume it.

```markdown
<!-- yes: one sentence per line -->
The proxy compresses each request before it reaches Anthropic.
On a long session this barely helps, because cost is dominated by cached context.

<!-- no: clause-split (SemBr) — one sentence scattered over lines -->
On a long session this barely helps,
because cost is dominated by cached context.

<!-- no: column-wrapped (a one-word edit reflows the block) -->
The proxy compresses each request before it reaches Anthropic. On a long
session this barely helps, because cost is dominated by cached context.
```

Rules of thumb:

- Break after each sentence terminator (period/question/exclamation) and nowhere else.
- Compound sentences stay on one line, conjunctions and relative clauses included.
- List items and table rows are already their own lines — leave them.

## Syntax conventions (CommonMark / GitHub-flavored)

- **Headings:** ATX (`#`, `##`), one space after `#`, one blank line above and below. One `#` H1 per document.
- **Emphasis:** `**bold**` and `_italic_` (asterisks for bold, underscores for italic — pick and stay consistent).
- **Lists:** `-` for unordered (not `*`/`+`); `1.` for ordered (let the renderer number — `1.` on every item is fine and diff-friendly). Indent nested items 2 spaces.
- **Code:** always fence with a language tag (```` ```bash ````, ```` ```ruby ````); inline code in backticks. Use `~~~` only when the block itself contains triple backticks.
- **Links:** inline `[text](url)` for one-offs; reference style `[text][ref]` when a URL repeats or the line gets long.
- **Tables:** GFM pipes; header separator `---`; pad columns so the pipes align — formatted tables read cleanly in source.
- **Blank lines:** exactly one between blocks; none trailing at EOF +1 newline.
- **Line length:** no max (the one-sentence-per-line rule governs), but never put multiple sentences on one line.

## Gotchas

- A list/table/code block needs a blank line before it or it won't render.
- Hard tabs break nested lists — use spaces.
- In `SKILL.md`/frontmatter files, keep the YAML frontmatter intact; these conventions apply to the body.

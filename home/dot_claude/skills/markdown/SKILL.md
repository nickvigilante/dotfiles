---
name: markdown
description: Use whenever writing or editing ANY Markdown — READMEs, docs/, PR descriptions, notes, SKILL.md files, GitHub issues/comments. Enforces this user's conventions: semantic line breaks (one clause/sentence per line, never column-wrapped) and clean CommonMark/GFM syntax.
---

# Writing Markdown (this user's conventions)

## Semantic line breaks (the important one)

Break lines at **semantic boundaries**, not at a fixed column width.
One sentence — or one independent clause — per line.
Let the renderer soft-wrap; never hard-wrap prose at 80/100 columns.

Why: prose changes then produce **one-line diffs** at the clause that changed, instead of reflowing a whole paragraph.
Reviews and `git blame` stay legible.

```markdown
<!-- yes: semantic line breaks -->
The proxy compresses each request before it reaches Anthropic.
On a long session this barely helps,
because cost is dominated by cached context.

<!-- no: column-wrapped (a one-word edit reflows the block) -->
The proxy compresses each request before it reaches Anthropic. On a long
session this barely helps, because cost is dominated by cached context.
```

Rules of thumb:
- Break after each sentence (period/question/exclamation).
- For long sentences, also break before coordinating conjunctions (and/but/or/so), before relative clauses (which/that/who), and before a subordinate clause.
- Don't break mid-noun-phrase or before a comma that's just listing.
- List items and table rows are already their own lines — leave them.

## Syntax conventions (CommonMark / GitHub-flavored)

- **Headings:** ATX (`#`, `##`), one space after `#`, one blank line above and below. One `#` H1 per document.
- **Emphasis:** `**bold**` and `_italic_` (asterisks for bold, underscores for italic — pick and stay consistent).
- **Lists:** `-` for unordered (not `*`/`+`); `1.` for ordered (let the renderer number — `1.` on every item is fine and diff-friendly). Indent nested items 2 spaces.
- **Code:** always fence with a language tag (```` ```bash ````, ```` ```ruby ````); inline code in backticks. Use `~~~` only when the block itself contains triple backticks.
- **Links:** inline `[text](url)` for one-offs; reference style `[text][ref]` when a URL repeats or the line gets long.
- **Tables:** GFM pipes; header separator `---`; don't pad columns to align (alignment padding makes noisy diffs — the renderer aligns).
- **Blank lines:** exactly one between blocks; none trailing at EOF +1 newline.
- **Line length:** no max (semantic breaks govern), but don't put multiple sentences on one line.

## Gotchas
- A list/table/code block needs a blank line before it or it won't render.
- Hard tabs break nested lists — use spaces.
- In `SKILL.md`/frontmatter files, keep the YAML frontmatter intact; these conventions apply to the body.

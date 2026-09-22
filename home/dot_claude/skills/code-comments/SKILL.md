---
name: code-comments
description: Use before writing any code comment, and as a final pass after writing or editing code, whenever a comment might restate what the code already says. Also use when a reviewer flags a comment or PR as having unnecessary, obvious, or overly verbose comments.
---

# Code Comments

## Overview

A comment earns its place only by telling the reader something the code cannot.
Default is **no comment**.
Add one only when deleting it would lose real information.

## The test

Before writing a comment, ask: "If I delete this, does a reader lose information?"

- Comment restates what the next line does, just in English → delete it, or rename something so the code says it.
- Comment explains WHY (a constraint, invariant, workaround, non-obvious consequence) → keep it.

Apply the same test to comments already in a file you're editing.
Deleting a stale or restating comment is part of the edit, not a separate cleanup task.

## Before / after

```python
# BAD — restates the code
# increment counter by 1
counter += 1

# BAD — restates the code, just in English
# loop through users and check if active
for user in users:
    if user.active:
        ...

# GOOD — explains a non-obvious WHY
# Retry once: this upstream API returns a spurious 503 on cold start.
response = call_api_with_retry(url, retries=1)

# GOOD — flags a subtle invariant the signature can't show
# Must run before normalize() — it mutates `raw` in place.
validate(raw)
```

## Quick reference: keep or cut

| Comment says...                                              | Keep or cut                              |
| -------------------------------------------------------------| ----------------------------------------- |
| What the next line does, in English                          | Cut — rename variables/functions instead |
| Why this approach, when it's not the obvious one             | Keep                                     |
| A constraint, edge case, or gotcha invisible in the code      | Keep                                     |
| A workaround for a specific bug/limitation (link it if you can) | Keep                                  |
| A block above a function that just repeats its signature     | Cut                                      |
| A bare "TODO" with no owner or ticket                         | Cut, or add the ticket                   |

## Trim pass

After writing or editing code, read every comment you touched or added, one at a time, and delete any that fail the test above.
This step is not optional — comments accumulate by default, and default is wrong here.

## Common mistakes

- Commenting every function with "what it does" — the name and types already say that.
- Narrating a loop or conditional in prose instead of naming things well.
- Leaving a comment that explained the old version of the code — stale comments mislead more than no comment.
- Adding a comment because the code "looks complex" instead of simplifying the code; comment only if the complexity is irreducible.

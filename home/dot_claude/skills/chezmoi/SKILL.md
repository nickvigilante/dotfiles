---
name: chezmoi
description: Use when adding, editing, moving, or applying any dotfile managed by chezmoi in this user's setup — anything under ~/.claude, ~/.config, ~/.zshrc, etc. Encodes THIS user's specific chezmoi layout (source location, .chezmoiroot, naming, PR workflow) so changes land in the right place and survive across machines.z
---

# chezmoi (this user's setup)

This user's dotfiles are managed by **chezmoi** (`chezmoi --version` → v2.70.x).
Edits to a managed file are pointless if you only touch the live target — they get overwritten on the next `chezmoi apply` and never sync to other machines.
Always go through the **source**.

## The layout (verified)

- **chezmoi source dir:** `~/.local/share/chezmoi` — which is a **symlink to the git repo** `~/git/nickvigilante/dotfiles`. They are the same directory; edit either path.
- **`.chezmoiroot` = `home`**, so the actual source root is `~/git/nickvigilante/dotfiles/home/` (chezmoi resolves `chezmoi source-path` to `.../dotfiles/home`).
- **Remote:** `github.com/nickvigilante/dotfiles`. Changes land via **branch + PR** (see merged PRs #12/#13), not direct commits to `main`.
- Live targets map from the source by stripping the `home/` root and decoding the name prefixes below. Example: `home/dot_claude/settings.json` → `~/.claude/settings.json`.

## Name decoding (source → target)

| Source prefix/suffix                  | Meaning                                                    |
| ------------------------------------- | ---------------------------------------------------------- |
| `dot_foo`                             | `.foo`                                                     |
| `private_foo`                         | chmod 600                                                  |
| `executable_foo`                      | +x                                                         |
| `exact_dir/`                          | dir whose contents chezmoi fully controls (removes extras) |
| `symlink_foo`                         | a symlink                                                  |
| `foo.tmpl`                            | Go-templated (per-host/per-OS values)                      |
| `run_once_` / `run_onchange_` scripts | run on apply                                               |
| `.chezmoiignore`                      | targets to skip (supports per-host templating)             |

## Safe edit workflow (do this FIRST, before touching any managed file)

1. **Sync the source.** Run `chezmoi git pull` (pulls the source repo) before editing — otherwise you branch off stale `main` and collide with merged PRs.
   If the user merges a PR partway through your task, **repeat** `chezmoi git pull` before continuing.
2. **Drift-check before applying.** Run `chezmoi apply --dry-run` (or `chezmoi diff`) and read the diff.
   The point is to catch a live target that was **manually modified out-of-band** — a `chezmoi apply` replaces the whole target file, so any such drift is silently overwritten.
   Concretely compare the live file against the rendered source and list what apply would **lose** vs **add**.
3. **Reconcile drift, don't clobber it.** If the live file holds something not in the source that should survive (a tool that writes straight to the live file is the usual cause — e.g. `rtk hook claude` installs its hook into `~/.claude/settings.json`), capture it into the source first (`chezmoi add`, or add the block to the source by hand) so apply preserves it and it reproduces on other machines.
   Only discard live drift once you've confirmed it's unwanted (0 entries lost).
4. **Apply only what changed.** If `chezmoi git pull` brought in nothing and you made no source edits, there's nothing to apply.
5. **If `chezmoi apply` aborts** with "has changed since chezmoi last wrote it", that's the drift guard refusing to overwrite a manually-edited target.
   Resolve the drift per step 3, then re-run; use `chezmoi apply --force` **only** after the dry-run confirms zero unintended loss.

## Workflows

**Add a new dotfile to management** (capture an existing live file into the source):

```bash
chezmoi add ~/.claude/agents/foo.md        # -> home/dot_claude/agents/foo.md (untracked)
```

**Edit a managed file** — two equivalent paths:

- Edit the **source** directly: `~/git/nickvigilante/dotfiles/home/dot_claude/<file>`, then `chezmoi apply` to push it to the live target.
- Or `chezmoi edit ~/.claude/<file>` (opens the source), then `chezmoi apply`.
- If you edited the **live target** by mistake, re-capture with `chezmoi add ~/.claude/<file>`.

**Inspect before applying:** `chezmoi diff` (source vs live), `chezmoi status`, `chezmoi managed | grep claude`.

**Land the change (PR workflow):**

```bash
cd ~/git/nickvigilante/dotfiles
git checkout -b <topic>
git add home/dot_claude/...
git commit -m "feat(claude): ..."     # conventional commits; end body with Co-Authored-By trailer
git push -u origin <topic>
gh pr create --fill
```

**Pull changes made on another machine:**

```bash
cd ~/git/nickvigilante/dotfiles && git pull --ff-only && chezmoi apply
# (or: chezmoi update  — git-pulls the source and applies in one step)
```

## Per-host scoping (important for skills/agents)

Skill _descriptions_ load into every session on every machine.
To keep a machine-specific skill (e.g. a 3D-printing skill) off the work machine, either keep it in a project's `.claude/skills/` instead of global `dot_claude/skills/`, or gate it with a templated `.chezmoiignore`:

```
{{ if ne .chezmoi.hostname "personal-box" }}
.claude/skills/3d-printing
{{ end }}
```

## Gotchas

- Never edit `~/.claude/...` expecting it to persist — it's a chezmoi target. Source-first, then `apply`.
- `chezmoi cd` drops you into the source root (`.../dotfiles/home`).
- Other top-level dirs in the repo (`bootstrap/`, `os/`, `docs/`) are not chezmoi-managed dotfiles — don't `chezmoi add` into them.

---
description: Reconcile drift between local dotfile targets and the chezmoi source — bidirectional, per-element, human-gated — then land captured changes as one branch/PR.
argument-hint: "[path-prefix] (default: all managed targets; e.g. ~/.claude to scope)"
---

Reconcile drift between my local dotfile targets and the chezmoi source.
Bidirectional and **human-gated**: show me each drifted element and let me choose, then land accepted captures as one branch/PR.
**DO NOT commit, push, or `chezmoi apply` anything until I approve it.**

## Scope

- Default: all chezmoi-managed targets. If `$1` is given, scope to that path prefix (e.g. `~/.claude`).
- Layout and source of truth: see the `chezmoi` skill. Source is `~/.local/share/chezmoi` (→ `~/git/nickvigilante/dotfiles`, `.chezmoiroot=home`); changes land via branch + PR.

## Procedure

1. **Sync the source first.** `chezmoi git pull` so you compare against current `main` and don't branch off stale source. Note anything it brought in.

2. **Enumerate drift robustly — per path, not in one shot.** Get the managed list (`chezmoi managed`, filtered to the scope) and run `chezmoi diff <path>` for each, so one failing template can't abort the scan.
   - **Template-render failures are expected** for Bitwarden-templated targets (e.g. `~/.kube/homelab.yaml`). On error, report that path as "unresolvable (templated secret) — skipped". Never guess at its contents.

3. **Classify each drifted path BEFORE proposing an action:**
   - **Ignored / machine-local state** (matches `.chezmoiignore` — e.g. `~/.claude.json`, `~/.claude/settings.local.json`, `~/.claude/*cache*.json`) → **never touch.** These are per-machine by design.
   - **Generated target** (source is a `.tmpl` fed by `home/.chezmoidata/` — notably `~/.claude/settings.json`) → **never `chezmoi add`** (it would overwrite the template with rendered output). Reconcile at the source of truth instead (see the `chezmoi` skill, "Generated targets"):
     - permission-allowlist drift → `home/.chezmoidata/permissions.toml`
     - `enabledPlugins` / other static settings → the `.tmpl` static block
     then `chezmoi apply <path>` to regenerate, verifying with `chezmoi execute-template < <src>.tmpl | jq .`.
   - **Normal managed file:**
     - **live newer** (target edited out-of-band) → propose `chezmoi add <path>` (capture up into source).
     - **source newer** (the pull brought changes) → propose `chezmoi apply <path>` (push down to live).

4. **Present, don't act.** Show a numbered table — `# | path | direction | classification | proposed action | 1-line diff summary` — then STOP and ask which to accept (per element: accept / skip).

5. **On my approval only:**
   - *push-down* applies → `chezmoi apply <path>` per accepted path (these just sync live from already-merged source; no commit).
   - *capture-up* and *generated-target source edits* → stage in the source repo, create **one** descriptively-named branch for the batch (e.g. `chore/<machine>-config-sync-<topic>`), commit per the `commit-and-pr` skill (`Assisted-by: AI`, no `Co-Authored-By`), push, and open a PR with `gh pr create`. **Do not merge** unless I say so.

6. **Report** what was captured up, pushed down, and skipped/unresolvable, plus the PR link.

## Safety

- Never `chezmoi add` an ignored/state file or a generated target.
- Never commit a secret. betterleaks pre-commit is a backstop, not a guarantee — if a diff looks like it holds a credential, stop and flag it.
- **One batch = one branch = one PR**, so every machine converges on merge via `chezmoi update`. Never a PR per element.
- This is per-machine; run it once a session (the `SessionStart` drift check will remind you).

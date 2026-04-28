# Dotfiles Cross-Platform Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the dotfiles repo to (a) work on a fresh work Mac, (b) support ephemeral Ubuntu cloud VMs with a full dev toolkit, (c) track Warp + Ghostty configs with a shared color palette, (d) replace chezmoi prompts with Gum.

**Architecture:** chezmoi remains the source-of-truth tool. Add new data-model fields (`display`, `secrets`, `arch`, `machine=ephemeral`). Replace per-OS Brewfiles with one unified, chezmoi-templated Brewfile gated on (OS × profile × display × secrets) axes. Bootstrap downloads Gum once, auto-detects what it can, prompts for the rest, and pre-installs secret CLIs before `chezmoi init`. Always-run `run_after_install-packages.sh.tmpl` invokes `brew bundle check` (fast, self-healing) for non-Pi machines and apt for Pis.

**Tech Stack:** chezmoi (Go templates), bash 5.x, Gum 0.14+, Homebrew/Linuxbrew, apt/dnf, 1Password CLI (with service account token for ephemeral), Bitwarden CLI.

**Spec reference:** `docs/superpowers/specs/2026-04-27-dotfiles-cross-platform-refactor-design.md`

**Execution preference (from spec):** Subagent-driven, three PRs (A: cleanup; B: foundation+Brewfile+bootstrap; C: ephemeral+terminals+polish).

---

## Conventions

- All paths are repo-relative unless prefixed with `~/` or `/`.
- chezmoi source root is `home/`. The `dot_` prefix → `.` in `$HOME` (e.g. `home/dot_zshrc.tmpl` → `~/.zshrc`).
- Verify-style steps say what to *run* and what to *expect* — if the actual differs, stop and report; do not auto-fix.
- "Commit" steps use Conventional Commits and avoid co-author trailers (per user preference 2026-04-27).
- All shell scripts must `set -euo pipefail` and run `shellcheck` clean.

## Subagent dispatch hints

Tasks marked **[parallel-safe]** can be dispatched concurrently in the same dispatch wave. Tasks marked **[sequential]** must complete before downstream tasks start. Each PR ends with a single integration commit + push.

---

# PR A — Cleanup (Phase 0)

Goal: salvage real edits in working tree, delete junk artifacts, archive WIP files, ship a clean baseline before new work.

## Task A1: Inspect existing diffs and capture salvage decisions

**Files (read-only):**
- Read: `os/macos/Brewfile` (compare to HEAD)
- Read: `home/.chezmoi.toml.tmpl` (compare to HEAD)
- Read: `home/run_once_04-install-packages.sh.tmpl` (compare to HEAD)
- Read: `home/run_onchange_install-packages.sh.tmpl` (compare to HEAD)
- Read: `home/dot_gitconfig.tmpl` (compare to HEAD — change is in working tree, no longer staged)

- [ ] **Step 1: Capture each diff explicitly**

```bash
git diff HEAD -- os/macos/Brewfile
git diff HEAD -- home/.chezmoi.toml.tmpl
git diff HEAD -- home/run_once_04-install-packages.sh.tmpl
git diff HEAD -- home/run_onchange_install-packages.sh.tmpl
git diff HEAD -- home/dot_gitconfig.tmpl
```

Expected (per spec, Phase 0):
- **Brewfile**: drop `# sldkfmldksfdml` stray line, change `age` → `rage`, drop deprecated `homebrew/cask-fonts` tap line — KEEP
- **chezmoi.toml.tmpl**: alignment cleanup + add `[diff] pager = "delta"` — KEEP
- **gitconfig.tmpl**: add `pager = delta`, change `diff3` → `zdiff3`, add `[interactive]` and `[delta]` sections — KEEP
- **run_once_04 / run_onchange**: TBD — inspect and decide; if anything is real, keep; if nothing real, the soon-to-delete state means we can drop without applying

- [ ] **Step 2: For run_once_04 + run_onchange — if there are real edits, note them; if not, plan to discard since the files are deleted in Phase 2 anyway**

These two files are deleted in Phase 2. Any salvage value depends on whether the diff contains real changes vs. whitespace/cruft. **If real**: apply now and commit so the deletion in Phase 2 still removes the (improved) file. **If not real**: skip; just `git restore` them.

- [ ] **Step 3: No commit for this task — it's a research step. Carry decisions into A2-A5.**

## Task A2: Apply Brewfile salvage

**Files:**
- Modify: `os/macos/Brewfile`

- [ ] **Step 1: Verify the working tree state matches expectations**

```bash
git diff HEAD -- os/macos/Brewfile | head -30
```

Expected to show: removal of `tap "homebrew/cask-fonts"`, addition of `# sldkfmldksfdml` stray line that needs removal, `age` → `rage` change.

- [ ] **Step 2: Remove the stray `# sldkfmldksfdml` comment**

Edit `os/macos/Brewfile`. Delete the line `# sldkfmldksfdml` (it's debugging cruft).

- [ ] **Step 3: Verify the diff is clean**

```bash
git diff HEAD -- os/macos/Brewfile
```

Expected: only the deprecated-tap removal and `age` → `rage` change remain.

## Task A3: Apply chezmoi.toml.tmpl salvage

**Files:**
- Modify: `home/.chezmoi.toml.tmpl`

- [ ] **Step 1: Verify the diff matches spec expectations**

```bash
git diff HEAD -- home/.chezmoi.toml.tmpl
```

Expected: alignment normalization + `[diff] pager = "delta"` block. **Keep as-is — no changes needed**.

## Task A4: Apply gitconfig salvage (currently unstaged)

**Files:**
- Modify: `home/dot_gitconfig.tmpl`

- [ ] **Step 1: Verify the diff is the delta/zdiff3 additions**

```bash
git diff HEAD -- home/dot_gitconfig.tmpl
```

Expected:
- `[core] pager = delta` added
- `[merge] conflictstyle = zdiff3` (was `diff3`)
- New `[interactive] diffFilter = delta --color-only`
- New `[delta] navigate = true; dark = true`

- [ ] **Step 2: Keep as-is — no further edits needed**

## Task A5: Inspect & resolve run_once_04 / run_onchange diffs

**Files:**
- Modify or restore: `home/run_once_04-install-packages.sh.tmpl`
- Modify or restore: `home/run_onchange_install-packages.sh.tmpl`

- [ ] **Step 1: Show full diffs**

```bash
git diff HEAD -- home/run_once_04-install-packages.sh.tmpl home/run_onchange_install-packages.sh.tmpl
```

- [ ] **Step 2: Decide per file**

- If diff contains *real* improvements (logic fixes, comment updates worth keeping): leave the working-tree change as-is.
- If diff is whitespace, debugging cruft, or otherwise not worth keeping: `git restore <file>`.

- [ ] **Step 3: Verify final state**

```bash
git diff HEAD -- home/run_once_04-install-packages.sh.tmpl home/run_onchange_install-packages.sh.tmpl
```

Expected: either a clean diff containing only intended changes, or no diff (if restored).

## Task A6: Delete junk artifacts

**Files (delete):**
- Delete: `cask.json` (~23 MB)
- Delete: `formula.json` (~46 MB)
- Delete: `macos-versions.json` (~15 KB)
- Delete: `db.sql.zst` (~2 GB)

- [ ] **Step 1: Verify each is untracked junk before deletion**

```bash
ls -lh cask.json formula.json macos-versions.json db.sql.zst
git ls-files --error-unmatch cask.json formula.json macos-versions.json db.sql.zst 2>&1 || echo "Confirmed: untracked"
```

Expected: `Confirmed: untracked` (the `git ls-files` error means none are tracked).

- [ ] **Step 2: Delete**

```bash
rm cask.json formula.json macos-versions.json db.sql.zst
```

- [ ] **Step 3: Verify**

```bash
ls cask.json formula.json macos-versions.json db.sql.zst 2>&1
```

Expected: 4 × "No such file or directory".

## Task A7: Add .gitignore entries

**Files:**
- Create: `.gitignore` (top-level — does not currently exist)

- [ ] **Step 1: Create `.gitignore` with these entries**

```gitignore
# Build/lock artifacts (none currently, but reserved)

# Debug/research artifacts that should never be tracked
/cask.json
/formula.json
/macos-versions.json
/*.sql
/*.sql.zst

# Personal scratch
/notes.md

# OS junk
.DS_Store
Thumbs.db

# Editor / tooling
.vscode/
.idea/
*.swp
*.swo
```

Note the leading `/` on `cask.json`, `formula.json`, `macos-versions.json` — root-only, so a future legitimately-tracked nested file with the same name isn't ignored.

- [ ] **Step 2: Verify `.gitignore` does what we expect**

```bash
git status --short
# Should still show ?? for .claude/, home/.chezmoidata/, home/Brewfile.tmpl, home/Brewfile.work
# Should NOT show notes.md or any cask.json / formula.json / macos-versions.json (already deleted)
```

## Task A8: Archive WIP design files

**Files:**
- Move: `home/Brewfile.tmpl` → `docs/superpowers/specs/_archive/wip-2026-04-27/Brewfile.tmpl`
- Move: `home/Brewfile.work` → `docs/superpowers/specs/_archive/wip-2026-04-27/Brewfile.work`
- Move: `home/.chezmoidata/package-details.toml` → `docs/superpowers/specs/_archive/wip-2026-04-27/package-details.toml`
- Move: `notes.md` → `docs/superpowers/specs/_archive/wip-2026-04-27/notes.md`

- [ ] **Step 1: Create archive directory**

```bash
mkdir -p docs/superpowers/specs/_archive/wip-2026-04-27
```

- [ ] **Step 2: Move files**

```bash
mv home/Brewfile.tmpl docs/superpowers/specs/_archive/wip-2026-04-27/
mv home/Brewfile.work docs/superpowers/specs/_archive/wip-2026-04-27/
mv home/.chezmoidata/package-details.toml docs/superpowers/specs/_archive/wip-2026-04-27/
mv notes.md docs/superpowers/specs/_archive/wip-2026-04-27/
```

- [ ] **Step 3: Remove the now-empty `home/.chezmoidata/` directory** (it'll be re-created with `palette.toml` in PR B)

```bash
rmdir home/.chezmoidata
```

- [ ] **Step 4: Add a small README in the archive explaining what these are**

Create `docs/superpowers/specs/_archive/wip-2026-04-27/README.md`:

```markdown
# WIP files — 2026-04-27

These files are an in-flight attempt to consolidate Brewfiles and model cross-package-manager mappings. They informed the design captured in [`../../2026-04-27-dotfiles-cross-platform-refactor-design.md`](../../2026-04-27-dotfiles-cross-platform-refactor-design.md) but were not adopted as-is.

Archived for design archaeology; do not reuse without re-reading the spec.
```

## Task A9: Stage and commit Phase 0

- [ ] **Step 1: Stage all Phase 0 changes**

```bash
git add .gitignore
git add os/macos/Brewfile
git add home/.chezmoi.toml.tmpl
git add home/dot_gitconfig.tmpl
# If A5 kept changes:
git add home/run_once_04-install-packages.sh.tmpl 2>/dev/null || true
git add home/run_onchange_install-packages.sh.tmpl 2>/dev/null || true
git add docs/superpowers/specs/_archive/wip-2026-04-27/
# Stage the deletions (junk and the moved-out home/ files)
git add -u home/Brewfile.tmpl home/Brewfile.work home/.chezmoidata
git add -u notes.md cask.json formula.json macos-versions.json db.sql.zst 2>/dev/null || true
```

- [ ] **Step 2: Verify staging**

```bash
git status --short
```

Expected: only the Phase 0 changes staged. No `M` (modified) or `??` (untracked) entries except the explicitly-deferred WIP and the new `.claude/` directory (which we leave alone).

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: cleanup before cross-platform refactor

- Salvage Brewfile (rage, drop deprecated cask-fonts tap)
- Salvage chezmoi.toml.tmpl (delta pager + alignment)
- Salvage gitconfig (delta pager + zdiff3 + interactive section)
- Add .gitignore for debug artifacts and personal scratch
- Archive WIP files to docs/superpowers/specs/_archive/wip-2026-04-27/
- Delete debug artifacts (cask.json, formula.json, macos-versions.json, db.sql.zst)"
```

- [ ] **Step 4: Verify commit landed**

```bash
git log --oneline -2
git show --stat HEAD
```

## Task A10: Push & open PR A

- [ ] **Step 1: Push the feature branch**

```bash
git push -u origin nick/dotfiles-refactor-spec
```

- [ ] **Step 2: Open PR A using gh CLI**

```bash
gh pr create --title "chore: cleanup before cross-platform refactor" --body "$(cat <<'EOF'
## Summary
- Cleanup pass before the larger cross-platform refactor lands
- Salvages real edits in the working tree (Brewfile, chezmoi.toml, gitconfig)
- Deletes debug artifacts (cask.json, formula.json, macos-versions.json, db.sql.zst — total ~2 GB)
- Adds `.gitignore` entries to prevent re-tracking
- Archives WIP design files under `docs/superpowers/specs/_archive/wip-2026-04-27/`

Includes the design spec for the upcoming refactor at `docs/superpowers/specs/2026-04-27-dotfiles-cross-platform-refactor-design.md`.

## Test plan
- [ ] `chezmoi diff` produces no surprising changes after applying
- [ ] `git status` clean after merge

🤖 Plan: docs/superpowers/plans/2026-04-27-dotfiles-cross-platform-refactor.md
EOF
)"
```

- [ ] **Step 3: Capture PR URL for the user.**

---

# PR B — Foundation, Unified Brewfile, Bootstrap (Phases 1+2+3)

This PR is the bulk of the refactor. After PR A merges, branch off `main` for PR B work. **Tasks B1–B4 [parallel-safe]** can be dispatched concurrently. Tasks B5+ depend on B1–B4 and ordered as listed.

## Task B0: Branch off latest main for PR B

- [ ] **Step 1: Sync and branch**

```bash
git checkout main
git pull --ff-only
git checkout -b nick/dotfiles-refactor-foundation
```

## Task B1: [parallel-safe] Update `home/.chezmoi.toml.tmpl` with new data fields + rerun-comment header

**Files:**
- Modify: `home/.chezmoi.toml.tmpl`

- [ ] **Step 1: Replace the file contents with the expanded version**

```go-template
{{- /* Auto-detect helpers — values used as defaults below */ -}}
{{- $isWSL := and (eq .chezmoi.os "linux")
                  (or (env "WSL_DISTRO_NAME" | ne "")
                      (and (stat "/proc/version") (regexMatch "(?i)microsoft|wsl" (include "/proc/version")))) -}}
{{- $hasDisplayLinux := and (eq .chezmoi.os "linux") (not $isWSL)
                            (or (env "DISPLAY" | ne "") (env "WAYLAND_DISPLAY" | ne "")) -}}
{{- $defaultDisplay := or (eq .chezmoi.os "darwin")
                          (eq .chezmoi.os "windows")
                          $hasDisplayLinux -}}

{{- $profile := promptChoiceOnce . "profile" "Profile" (list "work" "personal") -}}
{{- $name := promptStringOnce . "name" "Full name" "Nick" -}}
{{- $email := promptStringOnce . "email" "Email address" "" -}}
{{- $machine := promptChoiceOnce . "machine" "Machine role" (list "laptop" "desktop" "server" "pi" "ephemeral") -}}
{{- $display := promptBoolOnce . "display" "Has graphical display" $defaultDisplay -}}
{{- $defaultSecrets := "none" -}}
{{- if eq $profile "work" }}{{ $defaultSecrets = "1password" }}{{ end -}}
{{- $secrets := promptChoiceOnce . "secrets" "Secret managers" (list "none" "bitwarden" "1password" "both") -}}

# ────────────────────────────────────────────────────────────
# Re-run this exact bootstrap on another machine:
#
#   sh -c "$(curl -fsSL https://raw.githubusercontent.com/nickvigilante/dotfiles/main/bootstrap/install.sh)" -- \
#     --profile {{ $profile }} \
#     --machine {{ $machine }} \
#     --secrets {{ $secrets }} \
#     {{ if $display }}--display{{ else }}--no-display{{ end }} \
#     --non-interactive
# ────────────────────────────────────────────────────────────

[data]
profile = {{ $profile | quote }}
name    = {{ $name | quote }}
email   = {{ $email | quote }}
machine = {{ $machine | quote }}
display = {{ $display }}
secrets = {{ $secrets | quote }}

[diff]
pager = "delta"
```

Notes:
- `$isWSL` / `$hasDisplayLinux` / `$defaultDisplay` are template helpers used to set sensible defaults — they don't appear in `[data]`.
- We keep the `promptChoiceOnce` / `promptStringOnce` / `promptBoolOnce` chezmoi-native prompts here. The new bootstrap script (Task B14) pre-fills them via `--promptString` / `--promptChoice` / `--promptBool` flags so the user actually sees Gum prompts in the bootstrap, not chezmoi's native prompts.
- The rerun-comment header reflects the *current* machine's answers, so copy/paste reproduces this machine's setup elsewhere.

- [ ] **Step 2: Verify the template parses**

```bash
chezmoi execute-template --init --promptChoice profile=work --promptString name=Nick --promptString email=foo@bar --promptChoice machine=laptop --promptBool display=true --promptChoice secrets=1password < home/.chezmoi.toml.tmpl
```

Expected: prints valid TOML to stdout including the rerun-comment header populated with `--profile work --machine laptop --secrets 1password --display`.

- [ ] **Step 3: Commit**

```bash
git add home/.chezmoi.toml.tmpl
git commit -m "feat(chezmoi): add display/secrets/ephemeral data fields and rerun-comment header"
```

## Task B2: [parallel-safe] Add the shared color palette

**Files:**
- Create: `home/.chezmoidata/palette.toml`

- [ ] **Step 1: Create directory and file**

```bash
mkdir -p home/.chezmoidata
```

Create `home/.chezmoidata/palette.toml`:

```toml
# Source-of-truth color palette — Tokyo Night Storm × Material Ocean blend.
# Consumed by Warp theme, Ghostty theme, Gum prompt styling, and bat config.
# Edit values here; run `chezmoi apply` to regenerate all consumer themes.

[palette.bg]
default     = "#0d0e1a"   # deep navy-black — terminal background
panel       = "#15172a"   # slightly lighter — popups, selection
highlight   = "#2a2b45"   # hover/active rows

[palette.fg]
default     = "#c8d1f0"   # cool off-white
dim         = "#6d7396"   # muted (line numbers, comments)
bright      = "#ffffff"

[palette.accent]
green       = "#7df7c1"   # primary — strings, success
blue        = "#82aaff"   # secondary — keywords, info
purple      = "#c792ea"   # tertiary — types, headings
cyan        = "#5ccfe6"   # quaternary — operators
violet      = "#8e7df7"   # for Gum borders / chrome

[palette.semantic]
success     = "#7df7c1"   # → green
info        = "#82aaff"   # → blue
warning     = "#f7c97d"   # amber
error       = "#f78ab1"   # rose

[palette.ansi]
black           = "#1a1b30"
red             = "#f78ab1"
green           = "#7df7c1"
yellow          = "#f7c97d"
blue            = "#82aaff"
magenta         = "#c792ea"
cyan            = "#5ccfe6"
white           = "#c8d1f0"
bright_black    = "#3b3d5e"
bright_red      = "#ff9bbc"
bright_green    = "#9efbd1"
bright_yellow   = "#ffd9a0"
bright_blue     = "#a5c4ff"
bright_magenta  = "#dbafff"
bright_cyan     = "#82e8ff"
bright_white    = "#ffffff"
```

- [ ] **Step 2: Verify chezmoi exposes the data**

```bash
chezmoi data | jq '.palette.accent'
```

Expected:
```json
{
  "blue": "#82aaff",
  "cyan": "#5ccfe6",
  "green": "#7df7c1",
  "purple": "#c792ea",
  "violet": "#8e7df7"
}
```

- [ ] **Step 3: Commit**

```bash
git add home/.chezmoidata/palette.toml
git commit -m "feat(palette): add shared Tokyo Night × Material Ocean palette"
```

## Task B3: [parallel-safe] Run `brew bundle dump` and capture for classification

**Files (no edits — capture only):**
- Create: `/tmp/current.Brewfile` (working dump, not committed)

This task collects the data needed for B5 (writing the unified Brewfile). It must run on Nick's current work Mac to capture installed packages.

- [ ] **Step 1: Run dump**

```bash
brew bundle dump --force --describe --file=/tmp/current.Brewfile
wc -l /tmp/current.Brewfile
head -50 /tmp/current.Brewfile
```

Expected: roughly 50–150 lines of `tap`/`brew`/`cask`/`vscode`/`mas` directives, each with a `# comment` describing the package (the `--describe` flag).

- [ ] **Step 2: Categorize each line into one of: cross-platform, mac-only, work-only, personal-only, display-required, secrets-related**

This is a classification task done collaboratively with Nick. Output: a worksheet listing each entry and its category. Save the worksheet at `/tmp/Brewfile-classified.md` (also not committed).

Format:
```
## Cross-platform CLI
brew "git"           # Distributed revision control
brew "ripgrep"       # Search tool

## macOS-only
brew "mas"           # Mac App Store CLI
cask "rectangle"

## Work-only
brew "awscli"
brew "kubernetes-cli"
cask "slack"

## Personal-only
cask "spotify"
...
```

Ambiguous cases (e.g., `ollama`, `protonvpn`, `bitwarden-cli`) → ask Nick interactively.

- [ ] **Step 3: No commit. Output drives Task B5.**

## Task B4: [parallel-safe] Capture current Warp + Ghostty configs for archival

**Files (no edits in this task — capture only):**
- Create: `/tmp/dotfiles-warp-snapshot.tar.gz`
- Create: `/tmp/dotfiles-ghostty-snapshot.tar.gz`

This task takes a snapshot of current Warp/Ghostty config so we can compare before/after when templatizing in Task C4–C5.

- [ ] **Step 1: Snapshot Warp**

```bash
mkdir -p /tmp/snapshots
tar -czf /tmp/snapshots/warp-2026-04-27.tar.gz -C ~ .warp 2>/dev/null || echo "No ~/.warp dir"
ls -la ~/.warp 2>/dev/null
```

- [ ] **Step 2: Snapshot Ghostty (if present)**

```bash
tar -czf /tmp/snapshots/ghostty-2026-04-27.tar.gz -C ~/.config ghostty 2>/dev/null || echo "No ~/.config/ghostty dir"
```

- [ ] **Step 3: No commit. Snapshots are reference material for Task C4.**

## Task B5: Create unified `home/dot_config/dotfiles/Brewfile.tmpl`

**Depends on:** B1, B2, B3.
**Files:**
- Create: `home/dot_config/dotfiles/Brewfile.tmpl`

- [ ] **Step 1: Create directory and file**

```bash
mkdir -p home/dot_config/dotfiles
```

Create `home/dot_config/dotfiles/Brewfile.tmpl` using the classification from Task B3. Below is the structural skeleton with the axis guards in place — fill the package lists from B3's worksheet:

```ruby
# Unified Brewfile — rendered to ~/.config/dotfiles/Brewfile by chezmoi.
# Source: home/dot_config/dotfiles/Brewfile.tmpl
# Edit this template; run `chezmoi apply` to regenerate.

# ── Taps ─────────────────────────────────────────────────────────────────────
# (Add taps unconditionally; they're per-arch and harmless if unused.)

# ── Cross-platform CLI (every full-toolkit machine) ──────────────────────────
brew "git"           # Distributed revision control
brew "curl"
brew "wget"
brew "jq"            # JSON processor
brew "ripgrep"       # Fast grep (rg)
brew "fd"            # Fast find
brew "fzf"           # Fuzzy finder
brew "eza"           # Better ls
brew "bat"           # Better cat (syntax highlighting)
brew "zoxide"        # Better cd
brew "tldr"          # Simplified man pages
brew "htop"
brew "tree"
brew "tmux"
brew "neovim"
brew "gh"            # GitHub CLI
brew "git-delta"     # Better git diff
brew "lazygit"       # TUI git client
brew "uv"            # Python package manager (Astral)
brew "ruff"          # Python linter
brew "ty"            # Python type checker
brew "gum"           # Charm shell UI
brew "chezmoi"
brew "rage"          # Modern encryption
brew "pre-commit"

# ── macOS-only ───────────────────────────────────────────────────────────────
{{ if eq .chezmoi.os "darwin" -}}
brew "mas"           # Mac App Store CLI
brew "duti"          # Default-app picker
brew "coreutils"     # GNU file/shell utilities
brew "findutils"     # GNU find/xargs
brew "grep"          # GNU grep
brew "gnu-sed"
brew "gnu-tar"
brew "gawk"
{{- end }}

# ── Secrets CLIs ─────────────────────────────────────────────────────────────
{{ if or (eq .secrets "bitwarden") (eq .secrets "both") -}}
brew "bitwarden-cli" # `bw` — personal secrets
{{- end }}
{{ if or (eq .secrets "1password") (eq .secrets "both") -}}
{{- if eq .chezmoi.os "darwin" }}
cask "1password-cli" # `op` — work secrets (mac is cask, linux uses apt repo)
{{- else }}
# 1Password CLI on Linux is installed by bootstrap/lib/secrets.sh from 1Password's apt repo.
{{- end }}
{{- end }}

# ── Work-only formulae ───────────────────────────────────────────────────────
{{ if eq .profile "work" -}}
brew "awscli"
brew "kubernetes-cli"
brew "helm"
brew "minikube"
brew "vale"
brew "htmltest"
brew "node"
brew "wireguard-tools"
brew "cmake"
# (add the rest from the dump classification)
{{- end }}

# ── GUI casks (macOS + display only) ─────────────────────────────────────────
{{ if and .display (eq .chezmoi.os "darwin") -}}
cask "rectangle"
cask "displaylink"
cask "logi-options+"
cask "git-credential-manager"
cask "visual-studio-code"
cask "warp"
cask "ghostty"
cask "font-jetbrains-mono-nerd-font"
cask "font-fira-code-nerd-font"

  {{ if eq .profile "work" -}}
cask "1password"
cask "slack"
cask "notion"
cask "thunderbird"
cask "linear-linear"
cask "claude"
cask "zoom"
  {{- end }}

  {{ if eq .profile "personal" -}}
cask "firefox"
cask "spotify"
cask "signal"
  {{- end }}

# ── VS Code extensions (gated on display + macOS, requires `code` CLI) ──────
vscode "esbenp.prettier-vscode"
vscode "charliermarsh.ruff"
vscode "ms-python.python"
vscode "ms-python.vscode-pylance"
vscode "rust-lang.rust-analyzer"
vscode "redhat.vscode-yaml"
vscode "tamasfe.even-better-toml"
vscode "yzhang.markdown-all-in-one"
vscode "gruntfuggly.todo-tree"
  {{ if eq .profile "work" -}}
vscode "ms-toolsai.jupyter"
vscode "graphql.vscode-graphql"
vscode "tim-koehler.helm-intellisense"
vscode "anthropic.claude-code"
  {{- end }}
{{- end }}
```

The above is structural; **the full package list comes from Task B3's worksheet**. Add every classified line in the appropriate section.

- [ ] **Step 2: Render and inspect**

```bash
chezmoi cat ~/.config/dotfiles/Brewfile | head -100
```

Expected: rendered Brewfile reflects the current machine's data. Verify:
- All cross-platform brew lines present
- macOS-only block appears (since this is a Mac)
- Work block appears (since `.profile == "work"`)
- Display+macOS cask block appears
- VS Code lines appear
- Bitwarden line ABSENT if `.secrets == "1password"`

- [ ] **Step 3: `brew bundle check` against rendered file**

```bash
chezmoi apply ~/.config/dotfiles/Brewfile
brew bundle check --file=~/.config/dotfiles/Brewfile --verbose
```

Expected: most should pass since the dump was just taken. Anything missing → review classification.

- [ ] **Step 4: Commit**

```bash
git add home/dot_config/dotfiles/Brewfile.tmpl
git commit -m "feat(packages): unified Brewfile with OS/profile/display/secrets axes"
```

## Task B6: Create `home/run_after_install-packages.sh.tmpl`

**Files:**
- Create: `home/run_after_install-packages.sh.tmpl`

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# Always-run package installer.
# - Pi: stamp-and-compare against os/raspberry-pi/packages.apt; sudo apt install if changed.
# - All other machines: brew bundle check (fast no-op if satisfied) → install if not.
# Resilient per-line fallback catches single-package failures and reports them.
#
# This script runs AFTER chezmoi file targets are rendered (run_after_*) so
# ~/.config/dotfiles/Brewfile is in place before we run `brew bundle`.

set -euo pipefail

REPO_DIR="{{ .chezmoi.sourceDir }}/.."
GUM="${HOME}/.local/bin/gum"
[[ -x "$GUM" ]] || GUM="$(command -v gum || echo "")"

style_fail() {
    if [[ -n "$GUM" ]]; then
        "$GUM" style --foreground 213 --bold "$@"
    else
        echo "$@" >&2
    fi
}

{{ if eq .machine "pi" -}}
# ── Pi flow: apt only ──────────────────────────────────────────────────────
PKG_FILE="$REPO_DIR/os/raspberry-pi/packages.apt"
STAMP_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/dotfiles"
STAMP_FILE="$STAMP_DIR/pi-packages.stamp"
mkdir -p "$STAMP_DIR"

if [[ -f "$PKG_FILE" ]]; then
    current_hash=$(sha256sum "$PKG_FILE" | awk '{print $1}')
    last_hash=$(cat "$STAMP_FILE" 2>/dev/null || echo "")
    if [[ "$current_hash" != "$last_hash" ]]; then
        echo "==> Pi packages.apt changed — syncing..."
        sudo apt update
        grep -Ev '^#|^$' "$PKG_FILE" | xargs sudo apt install -y
        echo "$current_hash" > "$STAMP_FILE"
        echo "==> Done."
    fi
fi
exit 0
{{- end }}

{{ if and (eq .chezmoi.os "linux") (or (eq .chezmoi.arch "armv6l") (eq .chezmoi.arch "armv7l")) -}}
# 32-bit ARM (non-Pi) — Linuxbrew not supported. No-op.
echo "32-bit ARM detected; Homebrew not supported on this architecture. Skipping."
exit 0
{{- end }}

# ── Brewfile flow (macOS + Linux x86_64/aarch64) ──────────────────────────
BREWFILE="$HOME/.config/dotfiles/Brewfile"

if [[ ! -f "$BREWFILE" ]]; then
    echo "ERROR: $BREWFILE not yet rendered. Run 'chezmoi apply' first."
    exit 1
fi

if ! command -v brew &>/dev/null; then
    echo "ERROR: brew not on PATH. Run 'chezmoi apply' to trigger run_once_00-install-homebrew."
    exit 1
fi

# ── Build dynamic flags ───────────────────────────────────────────────────
bundle_flags=(--file="$BREWFILE")
command -v code &>/dev/null || bundle_flags+=(--no-vscode)
[[ "{{ .chezmoi.os }}" == "darwin" ]] || bundle_flags+=(--no-mas)

# ── Fast path: already satisfied? ─────────────────────────────────────────
if brew bundle check "${bundle_flags[@]}" --quiet; then
    exit 0
fi

# ── Standard install ──────────────────────────────────────────────────────
if brew bundle install "${bundle_flags[@]}"; then
    exit 0
fi

# ── Per-line fallback ─────────────────────────────────────────────────────
echo "==> brew bundle reported errors. Switching to per-package mode..."
failed=()

while IFS= read -r line; do
    case "$line" in
        brew\ *)
            pkg=$(echo "$line" | sed -E 's/^brew "([^"]+)".*/\1/')
            brew install "$pkg" || failed+=("$pkg")
            ;;
        cask\ *)
            pkg=$(echo "$line" | sed -E 's/^cask "([^"]+)".*/\1/')
            brew install --cask "$pkg" || failed+=("cask:$pkg")
            ;;
        vscode\ *)
            if command -v code &>/dev/null; then
                pkg=$(echo "$line" | sed -E 's/^vscode "([^"]+)".*/\1/')
                code --install-extension "$pkg" --force || failed+=("vscode:$pkg")
            fi
            ;;
    esac
done < <(grep -E '^(brew|cask|vscode) ' "$BREWFILE")

if (( ${#failed[@]} > 0 )); then
    style_fail "The following packages failed to install:"
    printf '  • %s\n' "${failed[@]}"
    echo "Re-run 'chezmoi apply' or 'dotfiles update' later to retry."
fi
```

- [ ] **Step 2: Lint with shellcheck (after rendering)**

```bash
chezmoi cat ~/.local/bin/run_after_install-packages.sh > /tmp/render.sh 2>/dev/null || \
chezmoi execute-template --init < home/run_after_install-packages.sh.tmpl > /tmp/render.sh
shellcheck /tmp/render.sh
```

Expected: clean, possibly minor warnings about embedded `{{ }}` if shellcheck saw raw template (in which case re-render via `execute-template`).

- [ ] **Step 3: Commit**

```bash
git add home/run_after_install-packages.sh.tmpl
git commit -m "feat(packages): always-run installer with brew bundle check + per-line fallback"
```

## Task B7: Update `run_once_00-install-homebrew.sh.tmpl` for arch + ephemeral

**Files:**
- Modify: `home/run_once_00-install-homebrew.sh.tmpl`

- [ ] **Step 1: Replace contents**

```bash
#!/usr/bin/env bash
# run_once_00-install-homebrew: install Homebrew if not present.
# Runs once per machine. Skipped on Windows, Pi, and 32-bit ARM (Linuxbrew unsupported).

{{ if or (eq .chezmoi.os "darwin")
        (and (eq .chezmoi.os "linux")
             (ne .machine "pi")
             (or (eq .chezmoi.arch "amd64") (eq .chezmoi.arch "arm64"))) -}}

set -euo pipefail

if command -v brew &>/dev/null; then
    echo "Homebrew already installed: $(brew --version | head -1)"
    exit 0
fi

echo "Installing Homebrew..."
NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo "Homebrew installed."

{{ else -}}
echo "Skipping Homebrew (not supported on os={{ .chezmoi.os }}, arch={{ .chezmoi.arch }}, machine={{ .machine }})."
{{- end }}
```

- [ ] **Step 2: Verify rendering for several scenarios**

```bash
# Mac (should install)
chezmoi execute-template --init --promptChoice profile=work --promptString name=Nick --promptString email=foo --promptChoice machine=laptop --promptBool display=true --promptChoice secrets=1password < home/run_once_00-install-homebrew.sh.tmpl | head -20

# Pi (should skip)
chezmoi execute-template --init --promptChoice profile=personal --promptString name=Nick --promptString email=foo --promptChoice machine=pi --promptBool display=false --promptChoice secrets=none < home/run_once_00-install-homebrew.sh.tmpl | head -20
```

Expected: Mac path enters the install branch; Pi path shows the "Skipping" message.

- [ ] **Step 3: Commit**

```bash
git add home/run_once_00-install-homebrew.sh.tmpl
git commit -m "feat(homebrew): gate install on arch + machine type"
```

## Task B8: Add `home/run_once_01-install-bootstrap-prereqs.sh.tmpl`

**Files:**
- Create: `home/run_once_01-install-bootstrap-prereqs.sh.tmpl`

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# run_once_01-install-bootstrap-prereqs: ensure pre-Homebrew prereqs are installed.
# Defense in depth — bootstrap/install.sh already does this on first run, but a
# user who clones the repo and runs `chezmoi apply` directly should still be safe.

{{ if eq .chezmoi.os "linux" }}{{ if ne .machine "pi" -}}

set -euo pipefail

REPO_DIR="{{ .chezmoi.sourceDir }}/.."

if command -v apt-get &>/dev/null; then
    PKG_FILE="$REPO_DIR/os/linux/bootstrap.apt"
    if [[ -f "$PKG_FILE" ]]; then
        echo "==> Ensuring apt prereqs are installed..."
        sudo apt-get update -qq
        # shellcheck disable=SC2046
        sudo apt-get install -y $(grep -Ev '^#|^$' "$PKG_FILE")
    fi
elif command -v dnf &>/dev/null; then
    PKG_FILE="$REPO_DIR/os/linux/bootstrap.dnf"
    if [[ -f "$PKG_FILE" ]]; then
        echo "==> Ensuring dnf prereqs are installed..."
        # shellcheck disable=SC2046
        sudo dnf install -y $(grep -Ev '^#|^$' "$PKG_FILE")
    fi
fi

{{- end }}{{- end }}
```

- [ ] **Step 2: Render-test**

```bash
chezmoi execute-template --init --promptChoice profile=work --promptString name=Nick --promptString email=foo --promptChoice machine=ephemeral --promptBool display=false --promptChoice secrets=1password < home/run_once_01-install-bootstrap-prereqs.sh.tmpl
```

Expected: full bash script for Linux ephemeral. Mac/Pi cases should render to a near-empty script (just the shebang).

- [ ] **Step 3: Commit**

```bash
git add home/run_once_01-install-bootstrap-prereqs.sh.tmpl
git commit -m "feat(bootstrap): add run_once_01 to ensure apt/dnf prereqs"
```

## Task B9: Update `os/linux/bootstrap.apt` (rename + trim) and add `os/linux/bootstrap.dnf`

**Files:**
- Rename: `os/linux/packages.apt` → `os/linux/bootstrap.apt`
- Modify (after rename): `os/linux/bootstrap.apt`
- Create: `os/linux/bootstrap.dnf`

- [ ] **Step 1: Rename**

```bash
git mv os/linux/packages.apt os/linux/bootstrap.apt
```

- [ ] **Step 2: Replace contents of `os/linux/bootstrap.apt` with the trimmed list**

```
# Pre-Homebrew prerequisites for Ubuntu/Debian.
# Installed by bootstrap/install.sh and as defense-in-depth by run_once_01.
# Keep minimal — heavier tools come via the unified Brewfile after Homebrew is up.

curl
git
zsh
ca-certificates
build-essential
file
procps
gnupg
lsb-release
```

- [ ] **Step 3: Create `os/linux/bootstrap.dnf`**

```
# Pre-Homebrew prerequisites for Fedora.
# Installed by bootstrap/install.sh and as defense-in-depth by run_once_01.

curl
git
zsh
ca-certificates
@development-tools
file
procps-ng
gnupg2
```

- [ ] **Step 4: Verify there's no straggler reference to the old name**

```bash
grep -rn "packages.apt" home/ os/linux/ bootstrap/ 2>/dev/null | grep -v raspberry-pi
```

Expected: no matches (Pi keeps `packages.apt`).

- [ ] **Step 5: Commit**

```bash
git add os/linux/bootstrap.apt os/linux/bootstrap.dnf
git commit -m "feat(linux): rename packages.apt to bootstrap.apt; trim to prereqs only; add bootstrap.dnf"
```

## Task B10: Add `home/run_once_07-set-default-shell.sh.tmpl`

**Files:**
- Create: `home/run_once_07-set-default-shell.sh.tmpl`

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# run_once_07-set-default-shell: ensure zsh is the default login shell.
# macOS already defaults to zsh — no-op.
# Skipped on Pi (current shell is whatever the user wants there) and Windows.

{{ if and (eq .chezmoi.os "linux") (ne .machine "pi") -}}

set -euo pipefail

zsh_path="$(command -v zsh || true)"
if [[ -z "$zsh_path" ]]; then
    echo "WARN: zsh not found on PATH; skipping shell change."
    exit 0
fi

if ! grep -Fqx "$zsh_path" /etc/shells 2>/dev/null; then
    echo "Adding $zsh_path to /etc/shells (requires sudo)..."
    echo "$zsh_path" | sudo tee -a /etc/shells >/dev/null
fi

current_shell="$(getent passwd "$USER" | cut -d: -f7)"
if [[ "$current_shell" != "$zsh_path" ]]; then
    if chsh -s "$zsh_path" "$USER" 2>/dev/null; then
        echo "Default shell changed to $zsh_path. Open a new terminal for it to take effect."
    else
        echo "WARN: chsh failed. Run manually:  chsh -s $zsh_path"
    fi
fi

{{- end }}
```

- [ ] **Step 2: Commit**

```bash
git add home/run_once_07-set-default-shell.sh.tmpl
git commit -m "feat(shell): add run_once_07 to chsh to zsh on Linux"
```

## Task B11: Delete legacy install/onchange scripts

**Files:**
- Delete: `home/run_once_04-install-packages.sh.tmpl`
- Delete: `home/run_onchange_install-packages.sh.tmpl`

- [ ] **Step 1: Delete**

```bash
git rm home/run_once_04-install-packages.sh.tmpl home/run_onchange_install-packages.sh.tmpl
```

- [ ] **Step 2: Delete legacy per-OS Brewfiles**

```bash
git rm os/macos/Brewfile os/macos/Brewfile.work os/linux/Brewfile.linux
```

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor(packages): remove per-OS Brewfiles and legacy install scripts

Replaced by:
- home/dot_config/dotfiles/Brewfile.tmpl (unified, axis-gated)
- home/run_after_install-packages.sh.tmpl (always-run, brew bundle check)
- home/run_once_07-set-default-shell.sh.tmpl"
```

## Task B12: [parallel-safe with B13] Create `bootstrap/lib/detect.sh`

**Files:**
- Create: `bootstrap/lib/detect.sh`

- [ ] **Step 1: Create directory and file**

```bash
mkdir -p bootstrap/lib
```

Create `bootstrap/lib/detect.sh`:

```bash
#!/usr/bin/env bash
# Pure-shell platform detection. Exports DETECTED_* env vars on success.
# Sourced by bootstrap/install.sh.

set -euo pipefail

detect_all() {
    detect_os
    detect_arch
    detect_distro
    detect_wsl
    detect_ephemeral
    detect_display
    detect_pi
}

detect_os() {
    case "$(uname -s)" in
        Darwin)              DETECTED_OS="darwin" ;;
        Linux)               DETECTED_OS="linux" ;;
        CYGWIN*|MINGW*|MSYS*) DETECTED_OS="windows" ;;
        *) echo "Unsupported OS: $(uname -s)"; exit 1 ;;
    esac
    export DETECTED_OS
}

detect_arch() {
    # Map uname -m to chezmoi-style names
    case "$(uname -m)" in
        x86_64|amd64)            DETECTED_ARCH="amd64" ;;
        aarch64|arm64)           DETECTED_ARCH="arm64" ;;
        armv7l|armv7)            DETECTED_ARCH="armv7l" ;;
        armv6l|armv6)            DETECTED_ARCH="armv6l" ;;
        *)                       DETECTED_ARCH="$(uname -m)" ;;
    esac
    export DETECTED_ARCH
}

detect_distro() {
    DETECTED_DISTRO=""
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        DETECTED_DISTRO="$(. /etc/os-release && echo "${ID:-}")"
    fi
    export DETECTED_DISTRO
}

detect_wsl() {
    DETECTED_WSL=0
    if [[ "$DETECTED_OS" == "linux" ]]; then
        if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
            DETECTED_WSL=1
        elif grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
            DETECTED_WSL=1
        fi
    fi
    export DETECTED_WSL
}

detect_ephemeral() {
    DETECTED_EPHEMERAL=0
    if [[ -f /.dockerenv ]] || [[ -n "${CODESPACES:-}" ]] || [[ -n "${AWS_EXECUTION_ENV:-}" ]]; then
        DETECTED_EPHEMERAL=1
    fi
    # EC2 metadata probe (200ms timeout)
    if [[ "$DETECTED_EPHEMERAL" == 0 ]] && command -v curl &>/dev/null; then
        if curl -fsS -m 0.2 http://169.254.169.254/latest/meta-data/ &>/dev/null; then
            DETECTED_EPHEMERAL=1
        fi
    fi
    # GCE metadata
    if [[ "$DETECTED_EPHEMERAL" == 0 ]] && command -v curl &>/dev/null; then
        if curl -fsS -m 0.2 -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/ &>/dev/null; then
            DETECTED_EPHEMERAL=1
        fi
    fi
    export DETECTED_EPHEMERAL
}

detect_display() {
    case "$DETECTED_OS" in
        darwin|windows) DETECTED_DISPLAY=1 ;;
        linux)
            if [[ "$DETECTED_WSL" == 1 ]]; then
                DETECTED_DISPLAY=0
            elif [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
                DETECTED_DISPLAY=1
            else
                DETECTED_DISPLAY=0
            fi
            ;;
    esac
    export DETECTED_DISPLAY
}

detect_pi() {
    DETECTED_IS_PI=0
    if [[ -f /proc/device-tree/model ]]; then
        if grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
            DETECTED_IS_PI=1
        fi
    fi
    export DETECTED_IS_PI
}

# When run directly (not sourced), print results
if [[ "${BASH_SOURCE[0]:-}" == "${0}" ]]; then
    detect_all
    echo "OS:        $DETECTED_OS"
    echo "Arch:      $DETECTED_ARCH"
    echo "Distro:    $DETECTED_DISTRO"
    echo "WSL:       $DETECTED_WSL"
    echo "Ephemeral: $DETECTED_EPHEMERAL"
    echo "Display:   $DETECTED_DISPLAY"
    echo "Pi:        $DETECTED_IS_PI"
fi
```

- [ ] **Step 2: Verify it runs**

```bash
bash bootstrap/lib/detect.sh
```

Expected on a Mac: `OS: darwin`, `Arch: arm64` or `amd64`, `Display: 1`, others `0`.

- [ ] **Step 3: Lint**

```bash
shellcheck bootstrap/lib/detect.sh
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add bootstrap/lib/detect.sh
git commit -m "feat(bootstrap): add platform detection library"
```

## Task B13: [parallel-safe with B12] Create `bootstrap/lib/preflight.sh`

**Files:**
- Create: `bootstrap/lib/preflight.sh`

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# Preflight checks. Sourced by bootstrap/install.sh.
# Requires DETECTED_* env vars from detect.sh to be set.

set -euo pipefail

# Returns 0 if disk space sufficient, 1 if not.
preflight_disk_space() {
    local required_gb
    case "${DETECTED_OS:-unknown}/${DETECTED_DISPLAY:-0}" in
        darwin/*)     required_gb=12 ;;
        linux/1)      required_gb=8  ;;
        linux/0)      required_gb=5  ;;
        windows/*)    required_gb=8  ;;
        *)            required_gb=5  ;;
    esac

    local available_gb
    if command -v df &>/dev/null; then
        # df -BG --output=avail (GNU); fallback to df -k for BSD/macOS
        if df -BG --output=avail "$HOME" &>/dev/null; then
            available_gb=$(df -BG --output=avail "$HOME" | awk 'NR==2 { sub("G",""); print }')
        else
            local kb
            kb=$(df -k "$HOME" | awk 'NR==2 {print $4}')
            available_gb=$((kb / 1024 / 1024))
        fi
    else
        echo "WARN: df not available; skipping disk-space check."
        return 0
    fi

    if (( available_gb < required_gb )); then
        echo "✗ Insufficient disk space."
        echo "  Need at least ${required_gb}G free in $HOME, have ${available_gb}G."
        return 1
    fi
    echo "✓ Disk space OK (${available_gb}G free, ${required_gb}G required)."
}

preflight_network() {
    if ! curl -fsS -m 5 https://github.com >/dev/null 2>&1; then
        echo "✗ No network connectivity to github.com."
        return 1
    fi
    echo "✓ Network OK."
}

preflight_all() {
    preflight_disk_space || return 1
    preflight_network    || return 1
}
```

- [ ] **Step 2: Lint and smoke-test**

```bash
shellcheck bootstrap/lib/preflight.sh

# Smoke test
( source bootstrap/lib/detect.sh && detect_all && source bootstrap/lib/preflight.sh && preflight_all )
```

Expected: ✓ Disk space, ✓ Network.

- [ ] **Step 3: Commit**

```bash
git add bootstrap/lib/preflight.sh
git commit -m "feat(bootstrap): add preflight checks (disk space, network)"
```

## Task B14: Create `bootstrap/lib/gum-bootstrap.sh`

**Files:**
- Create: `bootstrap/lib/gum-bootstrap.sh`

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# Download and install Gum binary to ~/.local/bin/gum.tmp.
# Pinned version with checksum verification.
# After Homebrew installs the "real" gum (via the Brewfile), bootstrap removes
# the .tmp copy.

set -euo pipefail

GUM_VERSION="0.14.5"

gum_install_temp() {
    local os arch
    case "${DETECTED_OS:-}" in
        darwin)  os="Darwin" ;;
        linux)   os="Linux" ;;
        windows) os="Windows" ;;
        *) echo "gum_install_temp: unsupported OS"; return 1 ;;
    esac
    case "${DETECTED_ARCH:-}" in
        amd64)   arch="x86_64" ;;
        arm64)   arch="arm64" ;;
        armv7l)  arch="armv7" ;;
        armv6l)  arch="armv6" ;;
        *) echo "gum_install_temp: unsupported arch"; return 1 ;;
    esac

    local tarball="gum_${GUM_VERSION}_${os}_${arch}.tar.gz"
    local url="https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}/${tarball}"
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    trap "rm -rf '$tmp_dir'" RETURN

    echo "Downloading gum ${GUM_VERSION} (${os}_${arch})..."
    curl -fsSL "$url" -o "$tmp_dir/$tarball"

    # Verify checksum
    local checksum_url="https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}/checksums.txt"
    if curl -fsSL "$checksum_url" -o "$tmp_dir/checksums.txt"; then
        local expected actual
        expected=$(grep "  ${tarball}\$" "$tmp_dir/checksums.txt" | awk '{print $1}')
        if [[ -z "$expected" ]]; then
            echo "WARN: could not find checksum for ${tarball}; proceeding without verification."
        else
            actual=$(shasum -a 256 "$tmp_dir/$tarball" | awk '{print $1}')
            if [[ "$expected" != "$actual" ]]; then
                echo "✗ Checksum mismatch for gum binary." >&2
                echo "  Expected: $expected" >&2
                echo "  Actual:   $actual" >&2
                return 1
            fi
            echo "✓ Checksum verified."
        fi
    else
        echo "WARN: could not fetch checksums; proceeding without verification."
    fi

    tar -xzf "$tmp_dir/$tarball" -C "$tmp_dir"
    mkdir -p "$HOME/.local/bin"
    install -m 0755 "$tmp_dir"/gum*/gum "$HOME/.local/bin/gum.tmp"
    echo "✓ gum installed to $HOME/.local/bin/gum.tmp"
}

# After bootstrap completes, call this to remove the temp gum if brew-gum exists.
gum_cleanup_temp() {
    local brew_gum
    brew_gum="$(command -v gum 2>/dev/null || true)"
    if [[ -n "$brew_gum" ]] && [[ "$brew_gum" != "$HOME/.local/bin/gum.tmp" ]]; then
        rm -f "$HOME/.local/bin/gum.tmp"
        echo "✓ Removed temp gum binary; brew-gum is now active at $brew_gum."
    fi
}
```

- [ ] **Step 2: Lint**

```bash
shellcheck bootstrap/lib/gum-bootstrap.sh
```

- [ ] **Step 3: Commit**

```bash
git add bootstrap/lib/gum-bootstrap.sh
git commit -m "feat(bootstrap): add gum binary downloader with checksum verification"
```

## Task B14b: Create `bootstrap/lib/secrets.sh`

`bootstrap/install.sh` (Task B16) sources this to install `op`/`bw` before `chezmoi init`. Logically belongs to the secrets work in PR C, but install.sh's hard dependency means it must land in the same PR.

**Files:**
- Create: `bootstrap/lib/secrets.sh`

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# Secret-CLI installation helpers. Sourced by bootstrap/install.sh.
# Requires DETECTED_OS, DETECTED_ARCH set by detect.sh.

set -euo pipefail

# ── 1Password CLI install ───────────────────────────────────────────────────
install_op() {
    if command -v op &>/dev/null; then
        echo "✓ 1Password CLI already installed: $(op --version)"
        return 0
    fi
    case "$DETECTED_OS" in
        darwin)
            echo "Installing 1Password CLI via brew (will be re-installed via Brewfile too)..."
            if command -v brew &>/dev/null; then
                brew install --cask 1password-cli
            else
                _install_op_direct
            fi
            ;;
        linux)
            _install_op_apt_repo
            ;;
        *)
            echo "WARN: 1Password CLI auto-install not supported on $DETECTED_OS."
            return 1
            ;;
    esac
}

_install_op_apt_repo() {
    if ! command -v apt-get &>/dev/null; then
        echo "ERROR: 1Password CLI on Linux requires apt; this distro is unsupported."
        return 1
    fi
    echo "Adding 1Password apt repo..."
    curl -fsSL https://downloads.1password.com/linux/keys/1password.asc | \
        sudo gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg
    echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/amd64 stable main" | \
        sudo tee /etc/apt/sources.list.d/1password.list >/dev/null
    sudo mkdir -p /etc/debsig/policies/AC2D62742012EA22/
    curl -fsSL https://downloads.1password.com/linux/debian/debsig/1password.pol | \
        sudo tee /etc/debsig/policies/AC2D62742012EA22/1password.pol >/dev/null
    sudo mkdir -p /usr/share/debsig/keyrings/AC2D62742012EA22/
    curl -fsSL https://downloads.1password.com/linux/keys/1password.asc | \
        sudo gpg --dearmor --output /usr/share/debsig/keyrings/AC2D62742012EA22/debsig.gpg
    sudo apt-get update -qq
    sudo apt-get install -y 1password-cli
    echo "✓ 1Password CLI installed."
}

_install_op_direct() {
    local version="2.30.0"
    local arch
    case "$DETECTED_ARCH" in
        amd64) arch="amd64" ;;
        arm64) arch="arm64" ;;
        *) echo "ERROR: 1P CLI direct install requires amd64/arm64."; return 1 ;;
    esac
    local zip="op_${DETECTED_OS}_${arch}_v${version}.zip"
    local url="https://cache.agilebits.com/dist/1P/op2/pkg/v${version}/${zip}"
    local tmp; tmp="$(mktemp -d)"; trap "rm -rf '$tmp'" RETURN
    curl -fsSL "$url" -o "$tmp/$zip"
    unzip -q "$tmp/$zip" -d "$tmp"
    install -m 0755 "$tmp/op" "$HOME/.local/bin/op"
    echo "✓ 1Password CLI installed to $HOME/.local/bin/op"
}

# ── Bitwarden CLI install ───────────────────────────────────────────────────
install_bw() {
    if command -v bw &>/dev/null; then
        echo "✓ Bitwarden CLI already installed: $(bw --version)"
        return 0
    fi
    case "$DETECTED_OS" in
        darwin)
            if command -v brew &>/dev/null; then
                brew install bitwarden-cli
            else
                echo "ERROR: Homebrew required for Bitwarden CLI on macOS."
                return 1
            fi
            ;;
        linux)
            local version="2024.7.2"
            local tmp; tmp="$(mktemp -d)"; trap "rm -rf '$tmp'" RETURN
            curl -fsSL "https://github.com/bitwarden/clients/releases/download/cli-v${version}/bw-linux-${version}.zip" -o "$tmp/bw.zip"
            unzip -q "$tmp/bw.zip" -d "$tmp"
            install -m 0755 "$tmp/bw" "$HOME/.local/bin/bw"
            echo "✓ Bitwarden CLI installed to $HOME/.local/bin/bw"
            ;;
        *)
            echo "WARN: Bitwarden CLI auto-install not supported on $DETECTED_OS."
            return 1
            ;;
    esac
}
```

- [ ] **Step 2: Lint**

```bash
shellcheck bootstrap/lib/secrets.sh
```

- [ ] **Step 3: Commit**

```bash
git add bootstrap/lib/secrets.sh
git commit -m "feat(bootstrap): add 1Password and Bitwarden CLI install helpers"
```

## Task B15: Create `home/dot_config/dotfiles/lib/gum.sh.tmpl`

**Files:**
- Create: `home/dot_config/dotfiles/lib/gum.sh.tmpl`

- [ ] **Step 1: Create directory and file**

```bash
mkdir -p home/dot_config/dotfiles/lib
```

Create `home/dot_config/dotfiles/lib/gum.sh.tmpl`:

```bash
# Gum styling — palette-driven, sourced by all our Gum-using scripts.
# Generated from home/.chezmoidata/palette.toml + home/dot_config/dotfiles/lib/gum.sh.tmpl.

# Choose
export GUM_CHOOSE_CURSOR_FOREGROUND="{{ .palette.accent.violet }}"
export GUM_CHOOSE_SELECTED_FOREGROUND="{{ .palette.accent.green }}"
export GUM_CHOOSE_HEADER_FOREGROUND="{{ .palette.accent.blue }}"

# Confirm
export GUM_CONFIRM_PROMPT_FOREGROUND="{{ .palette.accent.blue }}"
export GUM_CONFIRM_SELECTED_BACKGROUND="{{ .palette.accent.violet }}"
export GUM_CONFIRM_SELECTED_FOREGROUND="{{ .palette.fg.bright }}"
export GUM_CONFIRM_UNSELECTED_FOREGROUND="{{ .palette.fg.dim }}"

# Input
export GUM_INPUT_PROMPT_FOREGROUND="{{ .palette.accent.blue }}"
export GUM_INPUT_CURSOR_FOREGROUND="{{ .palette.accent.green }}"
export GUM_INPUT_PLACEHOLDER_FOREGROUND="{{ .palette.fg.dim }}"

# Spin
export GUM_SPIN_SPINNER_FOREGROUND="{{ .palette.accent.violet }}"
export GUM_SPIN_TITLE_FOREGROUND="{{ .palette.accent.blue }}"

# Style
export GUM_STYLE_FOREGROUND="{{ .palette.fg.default }}"
export GUM_STYLE_BORDER_FOREGROUND="{{ .palette.accent.violet }}"

# Colors as exported names for ad-hoc use in scripts
export DOTFILES_PALETTE_BG="{{ .palette.bg.default }}"
export DOTFILES_PALETTE_FG="{{ .palette.fg.default }}"
export DOTFILES_PALETTE_GREEN="{{ .palette.accent.green }}"
export DOTFILES_PALETTE_BLUE="{{ .palette.accent.blue }}"
export DOTFILES_PALETTE_PURPLE="{{ .palette.accent.purple }}"
export DOTFILES_PALETTE_VIOLET="{{ .palette.accent.violet }}"
export DOTFILES_PALETTE_CYAN="{{ .palette.accent.cyan }}"
export DOTFILES_PALETTE_SUCCESS="{{ .palette.semantic.success }}"
export DOTFILES_PALETTE_WARNING="{{ .palette.semantic.warning }}"
export DOTFILES_PALETTE_ERROR="{{ .palette.semantic.error }}"
```

- [ ] **Step 2: Render and inspect**

```bash
chezmoi cat ~/.config/dotfiles/lib/gum.sh
```

Expected: every `{{ .palette.* }}` resolved to a hex color.

- [ ] **Step 3: Source-test (don't break the shell)**

```bash
bash -c 'source <(chezmoi cat ~/.config/dotfiles/lib/gum.sh) && echo $GUM_CHOOSE_CURSOR_FOREGROUND'
```

Expected: `#8e7df7`.

- [ ] **Step 4: Commit**

```bash
git add home/dot_config/dotfiles/lib/gum.sh.tmpl
git commit -m "feat(palette): add Gum styling exports rendered from palette"
```

## Task B16: Rewrite `bootstrap/install.sh`

**Files:**
- Modify: `bootstrap/install.sh`

This is the biggest single file. It composes everything from B12–B15.

- [ ] **Step 1: Replace contents**

```bash
#!/usr/bin/env bash
# Bootstrap dotfiles on macOS, Linux, or Windows (Cygwin).
#
# Usage on a fresh machine:
#   sh -c "$(curl -fsSL https://raw.githubusercontent.com/nickvigilante/dotfiles/main/bootstrap/install.sh)"
#
# Or with flags (non-interactive):
#   sh -c "$(curl -fsSL .../install.sh)" -- \
#     --profile work --machine ephemeral --secrets 1password \
#     --no-display --non-interactive

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
DOTFILES_REPO="${DOTFILES_REPO:-https://github.com/nickvigilante/dotfiles.git}"
SCRIPT_VERSION="2.0.0"

# ── Parse flags + env vars ───────────────────────────────────────────────────
FLAG_PROFILE="${DOTFILES_PROFILE:-}"
FLAG_NAME="${DOTFILES_NAME:-}"
FLAG_EMAIL="${DOTFILES_EMAIL:-}"
FLAG_MACHINE="${DOTFILES_MACHINE:-}"
FLAG_DISPLAY="${DOTFILES_DISPLAY:-}"
FLAG_SECRETS="${DOTFILES_SECRETS:-}"
FLAG_OP_TOKEN="${OP_SERVICE_ACCOUNT_TOKEN:-}"
FLAG_NON_INTERACTIVE="${DOTFILES_NON_INTERACTIVE:-0}"

while (( "$#" )); do
    case "$1" in
        --profile)          FLAG_PROFILE="$2"; shift 2 ;;
        --name)             FLAG_NAME="$2"; shift 2 ;;
        --email)            FLAG_EMAIL="$2"; shift 2 ;;
        --machine)          FLAG_MACHINE="$2"; shift 2 ;;
        --display)          FLAG_DISPLAY=1; shift ;;
        --no-display)       FLAG_DISPLAY=0; shift ;;
        --secrets)          FLAG_SECRETS="$2"; shift 2 ;;
        --op-token)         FLAG_OP_TOKEN="$2"; shift 2 ;;
        --non-interactive)  FLAG_NON_INTERACTIVE=1; shift ;;
        --help|-h)
            cat <<EOF
Usage: install.sh [flags]
  --profile work|personal
  --name "Name"
  --email user@host
  --machine laptop|desktop|server|pi|ephemeral
  --display | --no-display
  --secrets none|bitwarden|1password|both
  --op-token <token>          Stored at ~/.config/op/token (chmod 600)
  --non-interactive           Fail on any unspecified field; no prompts
EOF
            exit 0
            ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

# ── Pretty output (pre-Gum) ──────────────────────────────────────────────────
BOLD=$'\033[1m'; CYAN=$'\033[0;36m'; GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; RESET=$'\033[0m'
header() { printf "\n%s%s%s\n" "$BOLD" "$*" "$RESET"; }
info()   { printf "%s  →%s %s\n" "$CYAN" "$RESET" "$*"; }
ok()     { printf "%s  ✓%s %s\n" "$GREEN" "$RESET" "$*"; }
err()    { printf "%s  ✗%s %s\n" "$RED" "$RESET" "$*" >&2; }

# ── Locate scripts (works whether run via curl|sh or from clone) ────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
if [[ -z "$SCRIPT_DIR" ]] || [[ ! -d "$SCRIPT_DIR/lib" ]]; then
    # Curl-pipe-sh — clone into a temp dir to access lib/
    TMP_REPO="$(mktemp -d)"
    info "Cloning dotfiles to $TMP_REPO for bootstrap libs..."
    git clone --depth=1 "$DOTFILES_REPO" "$TMP_REPO"
    SCRIPT_DIR="$TMP_REPO/bootstrap"
fi

# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/detect.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/preflight.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/gum-bootstrap.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/secrets.sh"

# ── 1. Detect ─────────────────────────────────────────────────────────────────
header "Step 1/8 — Detect platform"
detect_all
ok "OS: $DETECTED_OS, Arch: $DETECTED_ARCH${DETECTED_DISTRO:+, Distro: $DETECTED_DISTRO}"
[[ "$DETECTED_WSL" == 1 ]] && info "WSL detected"
[[ "$DETECTED_EPHEMERAL" == 1 ]] && info "Ephemeral environment detected"
[[ "$DETECTED_IS_PI" == 1 ]] && info "Raspberry Pi detected"

# Auto-fill defaults from detection
[[ -z "$FLAG_DISPLAY" ]] && FLAG_DISPLAY="$DETECTED_DISPLAY"
if [[ -z "$FLAG_MACHINE" ]]; then
    if [[ "$DETECTED_IS_PI" == 1 ]];     then FLAG_MACHINE="pi"
    elif [[ "$DETECTED_EPHEMERAL" == 1 ]]; then FLAG_MACHINE="ephemeral"
    fi
fi
[[ -z "$FLAG_NAME"  ]] && FLAG_NAME="$(git config --global user.name 2>/dev/null || echo '')"

# ── 2. Preflight ─────────────────────────────────────────────────────────────
header "Step 2/8 — Preflight checks"
preflight_all || { err "Preflight failed."; exit 1; }

# ── 3. Bootstrap-only essentials ─────────────────────────────────────────────
header "Step 3/8 — Install bootstrap essentials"
case "$DETECTED_OS" in
    linux)
        if [[ "$DETECTED_IS_PI" == 0 ]]; then
            if command -v apt-get &>/dev/null; then
                info "Installing apt prereqs..."
                sudo apt-get update -qq
                # shellcheck disable=SC2046
                sudo apt-get install -y curl git zsh ca-certificates build-essential file procps gnupg lsb-release
            elif command -v dnf &>/dev/null; then
                info "Installing dnf prereqs..."
                sudo dnf install -y curl git zsh ca-certificates @development-tools file procps-ng gnupg2
            fi
        fi
        ;;
    darwin)
        # Homebrew installer handles Xcode CLI tools; nothing to do here.
        :
        ;;
esac
ok "Bootstrap essentials in place."

# ── 4. Download Gum ──────────────────────────────────────────────────────────
header "Step 4/8 — Download Gum"
if command -v gum &>/dev/null; then
    GUM_BIN="$(command -v gum)"
else
    gum_install_temp || { err "Gum download failed."; exit 1; }
    export PATH="$HOME/.local/bin:$PATH"
    GUM_BIN="$HOME/.local/bin/gum.tmp"
fi
[[ -x "$GUM_BIN" ]] || { err "Gum binary not executable: $GUM_BIN"; exit 1; }
ok "Gum ready: $GUM_BIN"

# ── 5. Prompt for unset values ───────────────────────────────────────────────
header "Step 5/8 — Configure (Gum prompts for what wasn't set)"

prompt_required() {
    local var="$1" question="$2" choices="$3"
    if [[ -z "${!var}" ]]; then
        if [[ "$FLAG_NON_INTERACTIVE" == 1 ]]; then
            err "Required: $var (use --${var,,} or DOTFILES_${var^^}=)"; exit 1
        fi
        if [[ -n "$choices" ]]; then
            # shellcheck disable=SC2206
            local opts=($choices)
            printf -v "$var" '%s' "$("$GUM_BIN" choose --header "$question" "${opts[@]}")"
        else
            printf -v "$var" '%s' "$("$GUM_BIN" input --placeholder "$question")"
        fi
    fi
}

prompt_required FLAG_PROFILE "Profile"          "work personal"
prompt_required FLAG_NAME    "Full name"        ""
prompt_required FLAG_EMAIL   "Email address"    ""
prompt_required FLAG_MACHINE "Machine role"     "laptop desktop server pi ephemeral"
# Default secrets per profile if still unset
if [[ -z "$FLAG_SECRETS" ]]; then
    [[ "$FLAG_PROFILE" == "work" ]] && FLAG_SECRETS="1password" || FLAG_SECRETS="none"
    if [[ "$FLAG_NON_INTERACTIVE" == 0 ]]; then
        FLAG_SECRETS="$("$GUM_BIN" choose --header "Secret managers (default: $FLAG_SECRETS)" \
            "$FLAG_SECRETS" none bitwarden 1password both | head -1)"
    fi
fi

ok "Profile=$FLAG_PROFILE, machine=$FLAG_MACHINE, display=$FLAG_DISPLAY, secrets=$FLAG_SECRETS"

# ── 6. Pre-install secret CLIs ──────────────────────────────────────────────
header "Step 6/8 — Install secret CLIs (if needed)"
case "$FLAG_SECRETS" in
    bitwarden|both)
        if [[ "$DETECTED_EPHEMERAL" == 1 ]] && [[ "$FLAG_NON_INTERACTIVE" == 1 ]]; then
            err "Bitwarden on ephemeral non-interactive is unsupported (needs master password)."
            err "Use --secrets none or 1password instead."
            exit 1
        fi
        if ! command -v bw &>/dev/null; then
            install_bw  # defined in lib/secrets.sh, sourced below
        fi
        ;;
esac
case "$FLAG_SECRETS" in
    1password|both)
        install_op  # ensures `op` on PATH
        if [[ -n "$FLAG_OP_TOKEN" ]]; then
            mkdir -p "$HOME/.config/op"
            chmod 700 "$HOME/.config/op"
            printf '%s\n' "$FLAG_OP_TOKEN" > "$HOME/.config/op/token"
            chmod 600 "$HOME/.config/op/token"
            export OP_SERVICE_ACCOUNT_TOKEN="$FLAG_OP_TOKEN"
            ok "1Password service account token stored at ~/.config/op/token"
        elif [[ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]] && [[ "$FLAG_NON_INTERACTIVE" == 0 ]]; then
            info "Run 'op signin' once to set up Keychain integration."
        fi
        ;;
esac

case "$FLAG_SECRETS" in
    bitwarden|both)
        if [[ "$FLAG_NON_INTERACTIVE" == 0 ]]; then
            info "Logging in to Bitwarden..."
            bw login --raw >/dev/null 2>&1 || bw login
            export BW_SESSION
            BW_SESSION="$(bw unlock --raw)"
            ok "Bitwarden unlocked."
        fi
        ;;
esac

# ── 7. Install chezmoi ──────────────────────────────────────────────────────
header "Step 7/8 — Install chezmoi"
if ! command -v chezmoi &>/dev/null; then
    info "Installing chezmoi..."
    sh -c "$(curl -fsSL https://get.chezmoi.io)" -- -b "$HOME/.local/bin"
fi
export PATH="$HOME/.local/bin:$PATH"
ok "chezmoi installed: $(chezmoi --version | head -1)"

# ── 8. chezmoi init --apply ─────────────────────────────────────────────────
header "Step 8/8 — Apply dotfiles"
chezmoi init --apply \
    --promptChoice profile="$FLAG_PROFILE" \
    --promptString name="$FLAG_NAME" \
    --promptString email="$FLAG_EMAIL" \
    --promptChoice machine="$FLAG_MACHINE" \
    --promptBool   display="$([[ $FLAG_DISPLAY == 1 ]] && echo true || echo false)" \
    --promptChoice secrets="$FLAG_SECRETS" \
    "$DOTFILES_REPO"

# ── Cleanup ─────────────────────────────────────────────────────────────────
gum_cleanup_temp 2>/dev/null || true

ok "Bootstrap complete!"
echo ""
echo "Next steps:"
echo "  exec zsh                   # restart your shell"
echo "  dotfiles doctor            # health check"
echo "  chezmoi status             # show pending changes"
```

- [ ] **Step 2: Lint**

```bash
shellcheck bootstrap/install.sh
```

Expected: clean, possibly minor warnings for the `function gum()` shim (suppressible).

- [ ] **Step 3: Smoke-test the help text**

```bash
bash bootstrap/install.sh --help
```

Expected: prints usage and exits 0.

- [ ] **Step 4: Commit**

```bash
git add bootstrap/install.sh
git commit -m "feat(bootstrap): rewrite install.sh with Gum prompts and pre-install secrets"
```

## Task B17: PR B integration — push, open PR

- [ ] **Step 1: Verify state**

```bash
git status --short
git log --oneline main..HEAD
```

Expected: clean working tree, ~10–15 commits since `main`.

- [ ] **Step 2: Run a smoke `chezmoi apply` to make sure nothing exploded**

```bash
chezmoi apply --dry-run --verbose 2>&1 | head -50
```

Look for errors. Investigate any unexpected diffs.

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin nick/dotfiles-refactor-foundation

gh pr create --title "feat: foundation, unified Brewfile, Gum bootstrap" --body "$(cat <<'EOF'
## Summary
- Adds `display`, `secrets`, `arch` data fields to chezmoi.toml.tmpl; `machine=ephemeral` as new value
- Single source-of-truth color palette at `home/.chezmoidata/palette.toml`
- Replaces per-OS Brewfiles with one unified, axis-gated Brewfile at `home/dot_config/dotfiles/Brewfile.tmpl`
- Always-run `run_after_install-packages.sh.tmpl` with `brew bundle check` + per-line fallback
- New `run_once_07-set-default-shell.sh.tmpl` (chsh on Linux)
- Removes legacy `run_once_04` and `run_onchange_install-packages`
- Trims `os/linux/packages.apt` → `os/linux/bootstrap.apt` (pre-Homebrew prereqs only); adds `bootstrap.dnf`
- Rewrites `bootstrap/install.sh` with Gum prompts, auto-detect, non-interactive mode, pre-installs secret CLIs

## Test plan
- [ ] `chezmoi apply --dry-run` produces no errors on the work Mac
- [ ] `brew bundle check --file=~/.config/dotfiles/Brewfile` passes after apply
- [ ] `bash bootstrap/install.sh --help` prints usage cleanly
- [ ] `shellcheck bootstrap/lib/*.sh bootstrap/install.sh` clean

🤖 Plan: docs/superpowers/plans/2026-04-27-dotfiles-cross-platform-refactor.md
EOF
)"
```

- [ ] **Step 4: Capture PR URL.**

---

# PR C — Ephemeral, Terminal Configs, Polish (Phases 4+5+6)

After PR B merges, branch from latest `main` for PR C.

## Task C0: Branch off latest main for PR C

- [ ] **Step 1: Sync and branch**

```bash
git checkout main
git pull --ff-only
git checkout -b nick/dotfiles-refactor-polish
```

## Task C1: Update `home/private_dot_env.tmpl` to gate on `.secrets`

(Note: `bootstrap/lib/secrets.sh` was created in PR B as Task B14b — see note in that task.)


**Files:**
- Modify: `home/private_dot_env.tmpl`

- [ ] **Step 1: Replace contents**

```go-template
{{- /* ~/.env — runtime secrets, chmod 600 (chezmoi private_ prefix).
     Generated from home/private_dot_env.tmpl. Sourced by ~/.zshenv on every shell start.
     Edit with: chezmoi edit ~/.env */ -}}

# Secrets configuration: {{ .secrets }}

{{- if eq .secrets "none" }}

# This machine is configured with secrets = "none". No secrets are loaded.

{{- end }}

{{- if or (eq .secrets "1password") (eq .secrets "both") }}

# ── 1Password ────────────────────────────────────────────────────────────────
{{- if env "OP_SERVICE_ACCOUNT_TOKEN" | empty | not }}
# Service account token detected (ephemeral mode).
{{- end }}
# Add lines like:
# export AWS_ACCESS_KEY_ID="{{ "{{" }} onepasswordRead "op://Work Vault/AWS/access_key_id" {{ "}}" }}"
# export GITHUB_TOKEN="{{ "{{" }} onepasswordRead "op://Work Vault/GitHub PAT/credential" {{ "}}" }}"

{{- end }}

{{- if or (eq .secrets "bitwarden") (eq .secrets "both") }}

# ── Bitwarden ────────────────────────────────────────────────────────────────
# Add lines like:
# export PERSONAL_API_KEY="{{ "{{" }} (bitwarden "item" "Personal API Key").login.password {{ "}}" }}"

{{- end }}
```

- [ ] **Step 2: Verify rendering**

```bash
chezmoi cat ~/.env
```

Expected: file with the appropriate sections gated on the current `.secrets` value.

- [ ] **Step 3: Commit**

```bash
git add home/private_dot_env.tmpl
git commit -m "feat(secrets): gate ~/.env template on .secrets data field"
```

## Task C2: Update `home/dot_config/shell/functions.zsh` `bw-apply` for gating

**Files:**
- Modify: `home/dot_config/shell/functions.zsh`

This file isn't templated yet. Adding template logic requires renaming with `.tmpl` suffix.

- [ ] **Step 1: Rename to add `.tmpl` suffix**

```bash
git mv home/dot_config/shell/functions.zsh home/dot_config/shell/functions.zsh.tmpl
```

- [ ] **Step 2: Update the `bw-apply` and `bw-lock` definitions**

In `home/dot_config/shell/functions.zsh.tmpl`, replace the `# ── Secrets` section with:

```bash
# ── Secrets ───────────────────────────────────────────────────────────────────

bw-apply() {
{{- if or (eq .secrets "bitwarden") (eq .secrets "both") }}
    if ! command -v bw &>/dev/null; then
        echo "bw not found. Install: brew install bitwarden-cli"
        return 1
    fi
    if [[ -z "${BW_SESSION:-}" ]] || ! bw status 2>/dev/null | grep -q '"status":"unlocked"'; then
        echo "Unlocking Bitwarden..."
        export BW_SESSION
        BW_SESSION=$(bw unlock --raw) || { echo "Bitwarden unlock failed."; return 1; }
    else
        echo "Bitwarden already unlocked."
    fi
{{- end }}
    chezmoi apply
}

bw-lock() {
{{- if or (eq .secrets "bitwarden") (eq .secrets "both") }}
    bw lock
    unset BW_SESSION
{{- else }}
    echo "Bitwarden not configured for this machine (.secrets = {{ .secrets }})."
{{- end }}
}
```

- [ ] **Step 3: Verify rendering**

```bash
chezmoi cat ~/.config/shell/functions.zsh | grep -A 20 'bw-apply'
```

- [ ] **Step 4: Commit**

```bash
git add -u home/dot_config/shell/functions.zsh
git add home/dot_config/shell/functions.zsh.tmpl
git commit -m "feat(secrets): gate bw-apply on .secrets data field"
```

## Task C3: Source 1Password service-account token in `.zshenv`

**Files:**
- Modify: `home/dot_zshenv.tmpl`

- [ ] **Step 1: Add the sourcing block**

In `home/dot_zshenv.tmpl`, between the `# ── PATH` section and `# ── Secrets` section, add:

```bash
{{- if or (eq .secrets "1password") (eq .secrets "both") }}

# 1Password service-account token (ephemeral / headless machines)
if [[ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]] && [[ -f "$HOME/.config/op/token" ]]; then
    export OP_SERVICE_ACCOUNT_TOKEN="$(cat "$HOME/.config/op/token")"
fi
{{- end }}
```

- [ ] **Step 2: Render-verify**

```bash
chezmoi cat ~/.zshenv | grep -A 4 OP_SERVICE
```

Expected: shows the conditional block on a `.secrets ∈ {1password, both}` machine; absent otherwise.

- [ ] **Step 3: Commit**

```bash
git add home/dot_zshenv.tmpl
git commit -m "feat(secrets): source 1Password service-account token in .zshenv"
```

## Task C4: Capture and templatize Warp config

**Files:**
- Run `chezmoi add` for Warp paths
- Create: `home/dot_warp/themes/vigilante.yaml.tmpl`

- [ ] **Step 1: Capture current Warp configs into chezmoi source**

```bash
chezmoi add ~/.warp/keybindings.yaml 2>/dev/null || echo "no keybindings.yaml"
chezmoi add ~/.warp/themes 2>/dev/null || echo "no themes dir"
chezmoi add ~/.warp/launch_configurations 2>/dev/null || echo "no launch_configurations"
chezmoi add ~/.warp/workflows 2>/dev/null || echo "no workflows"
chezmoi cd
ls home/dot_warp/ 2>/dev/null
```

- [ ] **Step 2: Create the palette-driven theme template**

Create `home/dot_warp/themes/vigilante.yaml.tmpl`:

```yaml
# Vigilante theme — generated from home/.chezmoidata/palette.toml.
# Do NOT edit in Warp's UI; UI edits will be overwritten on next chezmoi apply.
# Iterate via:  dotfiles palette-import <wip-theme-name>

name: Vigilante
accent: '{{ .palette.accent.violet }}'
cursor: '{{ .palette.accent.green }}'
background: '{{ .palette.bg.default }}'
foreground: '{{ .palette.fg.default }}'
details: darker
terminal_colors:
  normal:
    black:    '{{ .palette.ansi.black }}'
    red:      '{{ .palette.ansi.red }}'
    green:    '{{ .palette.ansi.green }}'
    yellow:   '{{ .palette.ansi.yellow }}'
    blue:     '{{ .palette.ansi.blue }}'
    magenta:  '{{ .palette.ansi.magenta }}'
    cyan:     '{{ .palette.ansi.cyan }}'
    white:    '{{ .palette.ansi.white }}'
  bright:
    black:    '{{ .palette.ansi.bright_black }}'
    red:      '{{ .palette.ansi.bright_red }}'
    green:    '{{ .palette.ansi.bright_green }}'
    yellow:   '{{ .palette.ansi.bright_yellow }}'
    blue:     '{{ .palette.ansi.bright_blue }}'
    magenta:  '{{ .palette.ansi.bright_magenta }}'
    cyan:     '{{ .palette.ansi.bright_cyan }}'
    white:    '{{ .palette.ansi.bright_white }}'
```

- [ ] **Step 3: Verify rendering**

```bash
chezmoi cat ~/.warp/themes/vigilante.yaml
```

Expected: every `{{ .palette.* }}` resolved to a hex color.

- [ ] **Step 4: Apply and select theme in Warp**

```bash
chezmoi apply ~/.warp/themes/vigilante.yaml
```

In Warp: Settings → Appearance → Themes → select "Vigilante".

- [ ] **Step 5: Commit**

```bash
git add home/dot_warp/
git commit -m "feat(warp): track Warp config and add palette-driven Vigilante theme"
```

## Task C5: Capture and templatize Ghostty config

**Files:**
- Create: `home/dot_config/ghostty/config.tmpl`
- Create: `home/dot_config/ghostty/themes/vigilante.tmpl`

- [ ] **Step 1: Capture if Ghostty is installed**

```bash
chezmoi add ~/.config/ghostty 2>/dev/null || mkdir -p home/dot_config/ghostty/themes
```

- [ ] **Step 2: Create theme template**

`home/dot_config/ghostty/themes/vigilante.tmpl`:

```
# Vigilante theme — generated from home/.chezmoidata/palette.toml.
# Format: Ghostty theme syntax (one key=value per line).

palette = 0=#{{ slice .palette.ansi.black 1 }}
palette = 1=#{{ slice .palette.ansi.red 1 }}
palette = 2=#{{ slice .palette.ansi.green 1 }}
palette = 3=#{{ slice .palette.ansi.yellow 1 }}
palette = 4=#{{ slice .palette.ansi.blue 1 }}
palette = 5=#{{ slice .palette.ansi.magenta 1 }}
palette = 6=#{{ slice .palette.ansi.cyan 1 }}
palette = 7=#{{ slice .palette.ansi.white 1 }}
palette = 8=#{{ slice .palette.ansi.bright_black 1 }}
palette = 9=#{{ slice .palette.ansi.bright_red 1 }}
palette = 10=#{{ slice .palette.ansi.bright_green 1 }}
palette = 11=#{{ slice .palette.ansi.bright_yellow 1 }}
palette = 12=#{{ slice .palette.ansi.bright_blue 1 }}
palette = 13=#{{ slice .palette.ansi.bright_magenta 1 }}
palette = 14=#{{ slice .palette.ansi.bright_cyan 1 }}
palette = 15=#{{ slice .palette.ansi.bright_white 1 }}

background = {{ .palette.bg.default }}
foreground = {{ .palette.fg.default }}
cursor-color = {{ .palette.accent.green }}
selection-background = {{ .palette.bg.highlight }}
selection-foreground = {{ .palette.fg.bright }}
```

(`slice ... 1` strips the leading `#` since some ghostty values want `#hex`.)

- [ ] **Step 3: Create config template**

`home/dot_config/ghostty/config.tmpl`:

```
# Ghostty config — generated by chezmoi from home/dot_config/ghostty/config.tmpl

theme = vigilante

font-family = "JetBrains Mono"
font-size = 13

window-padding-x = 12
window-padding-y = 12
window-decoration = true

cursor-style = block
cursor-style-blink = true

# Match Warp's behavior: copy on selection, paste on right-click
copy-on-select = true

# Quality-of-life
confirm-close-surface = false
mouse-hide-while-typing = true
```

- [ ] **Step 4: Verify rendering**

```bash
chezmoi cat ~/.config/ghostty/config
chezmoi cat ~/.config/ghostty/themes/vigilante
```

Expected: real config files with palette-resolved colors.

- [ ] **Step 5: Commit**

```bash
git add home/dot_config/ghostty/
git commit -m "feat(ghostty): track Ghostty config and add palette-driven Vigilante theme"
```

## Task C6: Add `dotfiles` wrapper and `dotfiles-doctor` scripts

**Files:**
- Create: `home/dot_local/bin/executable_dotfiles`
- Create: `home/dot_local/bin/executable_dotfiles-doctor.tmpl`

- [ ] **Step 1: Create `dotfiles` wrapper**

`home/dot_local/bin/executable_dotfiles`:

```bash
#!/usr/bin/env bash
# dotfiles — thin wrapper for common dotfiles operations.

set -euo pipefail

case "${1:-}" in
    update)
        chezmoi update
        update-packages --force
        ;;
    doctor)
        exec dotfiles-doctor
        ;;
    palette-import)
        # Imports a Warp theme file back into palette.toml semantic tokens.
        # See spec § "Iteration workflow"
        echo "palette-import: TODO — manual flow for now."
        echo "  1. In Warp: duplicate a theme as 'vigilante-wip', edit, save"
        echo "  2. Read ~/.warp/themes/vigilante-wip.yaml manually"
        echo "  3. Update home/.chezmoidata/palette.toml with the new hex values"
        echo "  4. chezmoi apply"
        ;;
    *)
        cat <<EOF
Usage: dotfiles <command>

Commands:
  update           chezmoi update + update-packages --force
  doctor           run health check
  palette-import   (manual) import Warp WIP theme into palette.toml
EOF
        exit 1
        ;;
esac
```

Note: `palette-import` is documented as manual for now; auto-mapping deferred per spec.

- [ ] **Step 2: Create `dotfiles-doctor`**

`home/dot_local/bin/executable_dotfiles-doctor.tmpl`:

```bash
#!/usr/bin/env bash
# dotfiles-doctor — health check.

set -euo pipefail

# shellcheck source=/dev/null
[[ -f "$HOME/.config/dotfiles/lib/gum.sh" ]] && source "$HOME/.config/dotfiles/lib/gum.sh"

GUM="${HOME}/.local/bin/gum"
[[ -x "$GUM" ]] || GUM="$(command -v gum 2>/dev/null || echo "")"

ok()   { echo "  ✓ $*"; }
fail() { echo "  ✗ $*"; }
info() { echo "  → $*"; }

header() {
    if [[ -n "$GUM" ]]; then
        "$GUM" style --bold --foreground "{{ .palette.accent.violet }}" "$1"
    else
        echo ""
        echo "── $1 ──"
    fi
}

# ── Machine ──────────────────────────────────────────────────────────────────
header "Machine"
ok "os         {{ .chezmoi.os }}"
ok "arch       {{ .chezmoi.arch }}"
ok "machine    {{ .machine }}"
ok "display    {{ .display }}"
ok "profile    {{ .profile }}"
ok "secrets    {{ .secrets }}"

# ── Tooling ──────────────────────────────────────────────────────────────────
header "Tooling"
for cmd in chezmoi brew gum zsh; do
    if command -v "$cmd" &>/dev/null; then
        ok "$cmd       $($cmd --version 2>&1 | head -1)"
    else
        fail "$cmd not found"
    fi
done

{{ if or (eq .secrets "1password") (eq .secrets "both") -}}
if command -v op &>/dev/null; then
    if op whoami &>/dev/null; then
        ok "op         signed in"
    else
        fail "op installed but not signed in"
    fi
fi
{{- end }}

{{ if or (eq .secrets "bitwarden") (eq .secrets "both") -}}
if command -v bw &>/dev/null; then
    status_str="$(bw status 2>/dev/null | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')"
    case "$status_str" in
        unlocked) ok "bw         unlocked" ;;
        locked)   info "bw         locked (run bw-apply)" ;;
        *)        fail "bw         unknown status: $status_str" ;;
    esac
fi
{{- end }}

# ── Files ────────────────────────────────────────────────────────────────────
header "Files"
for f in "$HOME/.zshrc" "$HOME/.config/dotfiles/Brewfile" "$HOME/.config/dotfiles/lib/gum.sh"; do
    [[ -f "$f" ]] && ok "$f" || fail "$f missing"
done

{{ if and .display (eq .chezmoi.os "darwin") -}}
[[ -f "$HOME/.warp/themes/vigilante.yaml" ]] && ok "Warp theme" || fail "Warp theme missing"
[[ -f "$HOME/.config/ghostty/config" ]] && ok "Ghostty config" || fail "Ghostty config missing"
{{- end }}

# ── Brewfile state ───────────────────────────────────────────────────────────
{{ if ne .machine "pi" -}}
header "Brewfile state"
if command -v brew &>/dev/null; then
    if brew bundle check --file="$HOME/.config/dotfiles/Brewfile" --quiet 2>/dev/null; then
        ok "brew bundle check passes"
    else
        fail "brew bundle check found drift; run 'dotfiles update'"
    fi
fi
{{- end }}

# ── Secrets ──────────────────────────────────────────────────────────────────
header "Secrets"
if [[ -f "$HOME/.env" ]]; then
    perms=$(stat -f '%Lp' "$HOME/.env" 2>/dev/null || stat -c '%a' "$HOME/.env" 2>/dev/null)
    if [[ "$perms" == "600" ]]; then
        ok "~/.env exists, chmod 600"
    else
        fail "~/.env exists but chmod is $perms (expected 600)"
    fi
else
    info "~/.env does not exist (.secrets = {{ .secrets }})"
fi
```

- [ ] **Step 3: Verify rendering and execution**

```bash
chezmoi apply ~/.local/bin/dotfiles ~/.local/bin/dotfiles-doctor
~/.local/bin/dotfiles --help
~/.local/bin/dotfiles-doctor
```

Expected: `dotfiles --help` shows usage; `dotfiles-doctor` prints a checked report.

- [ ] **Step 4: Commit**

```bash
git add home/dot_local/bin/
git commit -m "feat(cli): add dotfiles wrapper and dotfiles-doctor health check"
```

## Task C7: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace contents**

Update sections to reflect the new flow:

- Add `--profile`, `--machine`, `--secrets`, `--display`, `--non-interactive` flags to the bootstrap section
- Document `dotfiles update` and `dotfiles doctor`
- Add a "Terminal configs" section: Warp + Ghostty tracked; UI edits off-limits; iterate via `palette-import`
- Add "Ephemeral / cloud VMs" section explaining `OP_SERVICE_ACCOUNT_TOKEN` flow
- Update package management section: unified Brewfile + minimal apt prereqs
- Document the rerun-comment header
- Note the Pi-fleet caveat (apt-only)

(See README.md for the exact starting point — keep structure, update content. Apply the same prose tone as the existing README.)

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README for cross-platform refactor"
```

## Task C8: End-to-end smoke test on a real Ubuntu cloud VM

This is a **manual verification step** that must be performed by the user (Nick), not automated by a subagent.

- [ ] **Step 1: Spin up a fresh Ubuntu 24.04 cloud VM** (EC2 t3.medium or equivalent).

- [ ] **Step 2: Set the service-account token in the VM environment**

```bash
export OP_SERVICE_ACCOUNT_TOKEN="ops_..."
```

- [ ] **Step 3: Run bootstrap non-interactively**

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/nickvigilante/dotfiles/nick/dotfiles-refactor-polish/bootstrap/install.sh)" -- \
  --profile work \
  --machine ephemeral \
  --secrets 1password \
  --no-display \
  --non-interactive
```

Time it. Expected: 5–10 minutes.

- [ ] **Step 4: After completion, verify**

```bash
exec zsh
dotfiles-doctor
brew bundle check --file=~/.config/dotfiles/Brewfile
echo "$SHELL"     # should be zsh
which eza bat ripgrep fd  # should resolve via Linuxbrew
```

Expected: doctor all green, all expected commands resolve.

- [ ] **Step 5: Re-run idempotence check**

```bash
chezmoi apply
brew bundle check --file=~/.config/dotfiles/Brewfile
```

Expected: idempotent — no changes, fast exit.

- [ ] **Step 6: Spin down the VM. No commit needed for this task — verification only.**

## Task C9: PR C integration — push, open PR

- [ ] **Step 1: Verify state**

```bash
git status --short
git log --oneline main..HEAD
```

- [ ] **Step 2: Run final smoke `chezmoi apply --dry-run`**

```bash
chezmoi apply --dry-run --verbose 2>&1 | head -50
```

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin nick/dotfiles-refactor-polish

gh pr create --title "feat: ephemeral support, terminal configs, polish" --body "$(cat <<'EOF'
## Summary
- 1Password service-account flow for ephemeral / headless boxes (`OP_SERVICE_ACCOUNT_TOKEN` → `~/.config/op/token` chmod 600)
- Pre-installs `op` (apt repo on Linux) and `bw` before chezmoi init
- `~/.env` template now gated on `.secrets` data field
- Tracks Warp configs (themes, keybindings, launch_configurations, workflows)
- Tracks Ghostty config + theme — both consume `home/.chezmoidata/palette.toml`
- New `dotfiles update` / `dotfiles doctor` wrapper commands
- README updated for the new flow
- Verified end-to-end on a real Ubuntu cloud VM (Task C8)

## Test plan
- [ ] `chezmoi apply --dry-run` clean
- [ ] `dotfiles-doctor` all green on the work Mac
- [ ] Bootstrap on fresh Ubuntu cloud VM completes in 5-10 min and produces all-green doctor

🤖 Plan: docs/superpowers/plans/2026-04-27-dotfiles-cross-platform-refactor.md
EOF
)"
```

- [ ] **Step 4: Capture PR URL.**

---

## Completion checklist

- [ ] PR A merged
- [ ] PR B merged
- [ ] PR C merged
- [ ] Smoke-tested bootstrap on the fresh work Mac
- [ ] Smoke-tested bootstrap on a fresh Ubuntu ephemeral
- [ ] `dotfiles-doctor` all-green on both
- [ ] No regression on personal Mac (verified by `brew leaves` snapshot before/after — done out-of-band)
- [ ] Picked a final palette (or stuck with Tokyo Night × Material Ocean starter)

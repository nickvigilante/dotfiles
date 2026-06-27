# Repo Housekeeping + CI/Pre-commit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a strict, chezmoi-aware quality gate (pre-commit + GitHub Actions CI) for the dotfiles repo and bring all existing files into compliance, plus light repo tidying.

**Architecture:** `.pre-commit-config.yaml` is the single source of truth for all checks. CI runs `pre-commit run --all-files` plus chezmoi-specific validation, so local and CI never drift. Dev tooling is declared in the templated Brewfile so it reproduces across machines. Strict/blocking from day one: every check fails the build, so each task fixes existing violations before committing to keep the tree green.

**Tech Stack:** chezmoi (v2.70), pre-commit, shellcheck, shfmt, actionlint, yamllint, taplo (TOML), markdownlint-cli2, GitHub Actions, Homebrew Bundle.

## Global Constraints

- **chezmoi-aware linting** — source files use Go-template syntax and chezmoi name prefixes. Never shellcheck a raw `.tmpl`; render it first. The source root is `home/` (`.chezmoiroot=home`).
- **shellcheck scope = bash/sh only** — shellcheck does NOT support zsh. The 5 `*.zsh.tmpl` and static `*.zsh` files are validated with `zsh -n` (syntax check), not shellcheck.
- **9 bash `.tmpl` scripts** (`home/run_once_*.sh.tmpl`, `home/run_after_*.sh.tmpl`, `home/dot_local/bin/executable_dotfiles-doctor.tmpl`) must be rendered via `chezmoi execute-template` before shellcheck.
- **Dev tools are declared, not ad-hoc** — add them to `home/dot_config/dotfiles/Brewfile.tmpl` (packages skill), never a bare `brew install`.
- **Commit/PR conventions** — Conventional Commits; commit messages end with the `Assisted-by: AI` trailer; PR bodies end with `🤖 Built with AI assistance.`. NEVER write any vendor/model name (Claude, Anthropic, Copilot, GPT, etc.) in commits, PRs, or tracked files.
- **Markdown** — semantic line breaks (one clause/sentence per line); CommonMark/GFM. Line-length rules stay disabled because of this.
- **Strict/blocking** — no `continue-on-error`, no warning-only hooks. `chezmoi verify` currently exits 0; keep it that way.
- **Baseline facts:** no `.github/` yet; only `jq` + `prettier` installed locally; `main` is default branch; 10 pure-shell scripts + 9 bash `.tmpl` + 5 zsh `.tmpl` + 20 markdown + 4 toml + 4 json.

---

### Task 1: Declare dev tooling in the Brewfile and install locally

**Files:**
- Modify: `home/dot_config/dotfiles/Brewfile.tmpl`

**Interfaces:**
- Produces: locally available `shellcheck`, `shfmt`, `actionlint`, `pre-commit`, `yamllint`, `taplo`, `markdownlint-cli2` — every later task depends on these.

- [ ] **Step 1: Read the Brewfile template** to find the brew-formulae block and match its formatting.

Run: `cat home/dot_config/dotfiles/Brewfile.tmpl`

- [ ] **Step 2: Add the dev-tooling formulae.** Insert into the cross-platform `brew` section (keep alphabetical if the file is, and match its comment style):

```ruby
# Repo quality gate (CI + pre-commit) — see docs/superpowers/plans/2026-06-22-repo-housekeeping-ci.md
brew "actionlint"
brew "markdownlint-cli2"
brew "pre-commit"
brew "shellcheck"
brew "shfmt"
brew "taplo"
brew "yamllint"
```

- [ ] **Step 3: Apply the rendered Brewfile and install.**

Run: `chezmoi apply ~/.config/dotfiles/Brewfile && brew bundle --file=~/.config/dotfiles/Brewfile`
Expected: all seven formulae install; exit 0.

- [ ] **Step 4: Verify the tools resolve.**

Run: `for t in shellcheck shfmt actionlint pre-commit yamllint taplo markdownlint-cli2; do command -v $t || echo "MISSING $t"; done`
Expected: a path for each, no MISSING lines.

- [ ] **Step 5: Commit.**

```bash
git add home/dot_config/dotfiles/Brewfile.tmpl
git commit -m "chore(packages): declare repo quality-gate tooling in Brewfile

Assisted-by: AI"
```

---

### Task 2: Editor + attribute baseline

**Files:**
- Create: `.editorconfig`
- Create: `.gitattributes`

- [ ] **Step 1: Create `.editorconfig`.**

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2

[*.{sh,bash,zsh}]
indent_style = tab

[*.md]
trim_trailing_whitespace = false

[Brewfile*]
indent_style = space
```

- [ ] **Step 2: Create `.gitattributes`** to normalize line endings and mark generated/vendored content.

```gitattributes
* text=auto eol=lf
*.png binary
*.lua linguist-vendored
home/dot_config/nvim/lazy-lock.json linguist-generated
```

- [ ] **Step 3: Re-normalize the working tree.**

Run: `git add --renormalize . && git status --short`
Expected: either no changes or only line-ending normalizations.

- [ ] **Step 4: Commit.**

```bash
git add .editorconfig .gitattributes
git commit -m "chore: add editorconfig and gitattributes baseline

Assisted-by: AI"
```

---

### Task 3: Pre-commit foundation — generic hygiene hooks

**Files:**
- Create: `.pre-commit-config.yaml`

**Interfaces:**
- Produces: a working `pre-commit` install that later tasks extend with more hooks.

- [ ] **Step 1: Create `.pre-commit-config.yaml`** with the generic, chezmoi-safe hooks. (Exclude the `home/` template tree from JSON/whitespace fixers where chezmoi prefixes/templates would break parsers.)

```yaml
# Single source of truth for repo checks. CI runs `pre-commit run --all-files`.
# chezmoi note: never point a syntax parser at a raw .tmpl — see the
# chezmoi-render hook (added in a later task) for template validation.
default_install_hook_types: [pre-commit, commit-msg]
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
        args: [--markdown-linebreak-ext=md]
      - id: end-of-file-fixer
      - id: mixed-line-ending
        args: [--fix=lf]
      - id: check-merge-conflict
      - id: check-added-large-files
        args: [--maxkb=512]
      - id: check-json
        exclude: '\.tmpl$'
      - id: check-toml
        exclude: '\.tmpl$'
      - id: check-yaml
        exclude: '\.tmpl$'
```

- [ ] **Step 2: Install the git hooks.**

Run: `pre-commit install --install-hooks`
Expected: "pre-commit installed at .git/hooks/pre-commit" and commit-msg.

- [ ] **Step 3: Run against everything and fix what it reports.**

Run: `pre-commit run --all-files`
Expected first pass: hooks may MODIFY files (whitespace/EOF). Re-run until all hooks report `Passed`. Inspect every change with `git diff` before staging — confirm no `.tmpl` got corrupted.

- [ ] **Step 4: Re-run to confirm green.**

Run: `pre-commit run --all-files`
Expected: every hook `Passed`.

- [ ] **Step 5: Commit** (config + any whitespace fixes).

```bash
git add .pre-commit-config.yaml
git add -u
git commit -m "build: add pre-commit with generic hygiene hooks

Assisted-by: AI"
```

---

### Task 4: Shellcheck for pure-shell scripts

**Files:**
- Create: `.shellcheckrc`
- Modify: `.pre-commit-config.yaml`

**Interfaces:**
- Consumes: pre-commit foundation (Task 3).
- Produces: shellcheck gate over the 10 pure-shell scripts (`bootstrap/**/*.sh`, `home/dot_local/bin/executable_dotfiles`, `home/dot_local/bin/executable_update-packages`).

- [ ] **Step 1: Create `.shellcheckrc`.**

```sh
# Default shell for files without a shebang-detectable dialect.
shell=bash
# Allow sourcing files shellcheck can't follow (rendered/templated libs).
external-sources=true
disable=SC1091
```

- [ ] **Step 2: Add the shellcheck hook** to `.pre-commit-config.yaml`. Scope to bash/sh only; exclude every `.tmpl` (templates) and every `*.zsh` (unsupported dialect).

```yaml
  - repo: https://github.com/koalaman/shellcheck-precommit
    rev: v0.10.0
    hooks:
      - id: shellcheck
        files: '\.(sh|bash)$|(^|/)(executable_)?(dotfiles|update-packages)$'
        exclude: '\.tmpl$|\.zsh$'
```

- [ ] **Step 3: Run shellcheck and fix every finding.**

Run: `pre-commit run shellcheck --all-files`
Expected: shellcheck reports real issues (quoting, unused vars, etc.). Fix each in the source script — do not blanket-disable. For a genuinely-inapplicable rule, add a scoped `# shellcheck disable=SCxxxx` with a one-line reason.

- [ ] **Step 4: Confirm green.**

Run: `pre-commit run shellcheck --all-files`
Expected: `Passed`.

- [ ] **Step 5: Commit.**

```bash
git add .shellcheckrc .pre-commit-config.yaml
git add -u
git commit -m "build: lint pure-shell scripts with shellcheck

Assisted-by: AI"
```

---

### Task 5: chezmoi template render + zsh syntax validation

**Files:**
- Create: `scripts/ci/lint-chezmoi-templates.sh`
- Modify: `.pre-commit-config.yaml`

**Interfaces:**
- Consumes: pre-commit foundation; `chezmoi` on PATH.
- Produces: a local hook proving every `.tmpl` renders and every shell/zsh script is syntactically valid.

- [ ] **Step 1: Create the validation script** `scripts/ci/lint-chezmoi-templates.sh`.

```bash
#!/usr/bin/env bash
# Validate that every chezmoi-managed target renders, and that every shell
# script (rendered where templated) parses. Runs in pre-commit and CI.
set -euo pipefail

fail=0

# 1. Every managed target must render without a template error.
while IFS= read -r target; do
  if ! chezmoi cat "$target" >/dev/null 2>err.log; then
    echo "TEMPLATE RENDER FAILED: $target"; cat err.log; fail=1
  fi
done < <(chezmoi managed --include=files)
rm -f err.log

# 2. Rendered bash scripts must pass `bash -n`; zsh scripts `zsh -n`.
while IFS= read -r target; do
  case "$target" in
    *.zsh) chezmoi cat "$target" | zsh -n  || { echo "zsh -n FAILED: $target"; fail=1; } ;;
    *) head1=$(chezmoi cat "$target" | head -1)
       case "$head1" in
         '#!'*bash*|'#!'*/sh) chezmoi cat "$target" | bash -n || { echo "bash -n FAILED: $target"; fail=1; } ;;
       esac ;;
  esac
done < <(chezmoi managed --include=files)

exit "$fail"
```

- [ ] **Step 2: Make it executable.**

Run: `chmod +x scripts/ci/lint-chezmoi-templates.sh`

- [ ] **Step 3: Add a local hook** to `.pre-commit-config.yaml`.

```yaml
  - repo: local
    hooks:
      - id: chezmoi-templates
        name: chezmoi templates render + shell syntax
        entry: scripts/ci/lint-chezmoi-templates.sh
        language: script
        pass_filenames: false
        files: '^home/.*'
```

- [ ] **Step 4: Run it and fix any render/syntax failures.**

Run: `pre-commit run chezmoi-templates --all-files`
Expected: `Passed`. (Baseline `chezmoi verify` is already clean, so failures here would be new regressions — fix in source.)

- [ ] **Step 5: Commit.**

```bash
git add scripts/ci/lint-chezmoi-templates.sh .pre-commit-config.yaml
git commit -m "build: validate chezmoi template rendering and shell syntax

Assisted-by: AI"
```

---

### Task 6: shfmt formatting gate for shell

**Files:**
- Modify: `.pre-commit-config.yaml`

- [ ] **Step 1: Add the shfmt hook** (tab indent per `.editorconfig`; exclude templates/zsh).

```yaml
  - repo: https://github.com/scop/pre-commit-shfmt
    rev: v3.10.0-2
    hooks:
      - id: shfmt
        args: [-i, '0', -ci, -sr, -w]
        exclude: '\.tmpl$|\.zsh$'
```

- [ ] **Step 2: Run and let it format; review the diff.**

Run: `pre-commit run shfmt --all-files && git diff`
Expected: shfmt rewrites whitespace/formatting. Confirm no logic changed.

- [ ] **Step 3: Confirm green.**

Run: `pre-commit run shfmt --all-files`
Expected: `Passed`.

- [ ] **Step 4: Commit.**

```bash
git add .pre-commit-config.yaml
git add -u
git commit -m "build: enforce shell formatting with shfmt

Assisted-by: AI"
```

---

### Task 7: Convention guard — forbid vendor attribution

**Files:**
- Create: `scripts/ci/no-vendor-attribution.sh`
- Modify: `.pre-commit-config.yaml`

**Interfaces:**
- Produces: a hook that blocks any vendor/model name in tracked files and a commit-msg hook blocking `Co-Authored-By: <vendor>`.

- [ ] **Step 1: Create the guard** `scripts/ci/no-vendor-attribution.sh`.

```bash
#!/usr/bin/env bash
# Enforce vendor-neutral AI attribution. The only allowed signal is
# "Assisted-by: AI" / "Built with AI assistance". Block specific vendors.
set -euo pipefail

# Case-insensitive vendor/model tokens that must never appear in tracked
# files or commit messages (the attribution convention is deliberate).
pattern='Co-Authored-By:[[:space:]]*Claude|Generated with \[?Claude Code|🤖 Generated with Claude'

target="${1:-}"
if [[ -n "$target" && -f "$target" ]]; then
  # commit-msg mode: scan the message file.
  if grep -nEi "$pattern" "$target"; then
    echo "ERROR: vendor-specific AI attribution found. Use 'Assisted-by: AI'." >&2
    exit 1
  fi
else
  # pre-commit mode: scan staged tracked files.
  if git grep -nEi "$pattern" -- . ':(exclude)docs/superpowers/**' ':(exclude)scripts/ci/no-vendor-attribution.sh'; then
    echo "ERROR: vendor-specific AI attribution found in tracked files." >&2
    exit 1
  fi
fi
```

- [ ] **Step 2: Make executable + wire both hook stages.**

Run: `chmod +x scripts/ci/no-vendor-attribution.sh`

Add to `.pre-commit-config.yaml`:

```yaml
  - repo: local
    hooks:
      - id: no-vendor-attribution-files
        name: no vendor-specific AI attribution (files)
        entry: scripts/ci/no-vendor-attribution.sh
        language: script
        pass_filenames: false
        stages: [pre-commit]
      - id: no-vendor-attribution-msg
        name: no vendor-specific AI attribution (commit msg)
        entry: scripts/ci/no-vendor-attribution.sh
        language: script
        stages: [commit-msg]
```

- [ ] **Step 3: Run and fix any historical leakage in tracked files.**

Run: `pre-commit run no-vendor-attribution-files --all-files`
Expected: `Passed` (global instructions already enforce neutral wording; if it flags a file, neutralize it).

- [ ] **Step 4: Commit.**

```bash
git add scripts/ci/no-vendor-attribution.sh .pre-commit-config.yaml
git commit -m "build: guard against vendor-specific AI attribution

Assisted-by: AI"
```

---

### Task 8: Markdown + YAML + TOML linting

**Files:**
- Create: `.markdownlint-cli2.yaml`
- Create: `.yamllint.yaml`
- Modify: `.pre-commit-config.yaml`

**Interfaces:**
- Produces: structural lint over 20 markdown, the YAML configs, and 4 TOML files. Line-length stays OFF (semantic line breaks).

- [ ] **Step 1: Create `.markdownlint-cli2.yaml`** (disable line-length to respect semantic line breaks).

```yaml
config:
  default: true
  MD013: false   # line-length — incompatible with semantic line breaks
  MD033: false   # inline HTML — allowed in READMEs
  MD041: false   # first-line-heading — files may start with frontmatter
globs:
  - "**/*.md"
ignores:
  - "docs/superpowers/specs/_archive/**"
```

- [ ] **Step 2: Create `.yamllint.yaml`.**

```yaml
extends: default
rules:
  line-length: disable
  document-start: disable
  truthy:
    check-keys: false
ignore: |
  home/**/*.tmpl
```

- [ ] **Step 3: Add hooks** to `.pre-commit-config.yaml`.

```yaml
  - repo: https://github.com/DavidAnson/markdownlint-cli2
    rev: v0.14.0
    hooks:
      - id: markdownlint-cli2
  - repo: https://github.com/adrienverge/yamllint
    rev: v1.35.1
    hooks:
      - id: yamllint
        args: [-c, .yamllint.yaml]
  - repo: https://github.com/ComPWA/taplo-pre-commit
    rev: v0.9.3
    hooks:
      - id: taplo-format
        exclude: '\.tmpl$'
```

- [ ] **Step 4: Run each and fix findings.**

Run: `pre-commit run markdownlint-cli2 --all-files; pre-commit run yamllint --all-files; pre-commit run taplo-format --all-files`
Expected: fix structural markdown issues (heading levels, list markers), YAML issues, and let taplo format TOML. Re-run until all `Passed`. Do NOT reflow prose into long lines — keep semantic breaks.

- [ ] **Step 5: Commit.**

```bash
git add .markdownlint-cli2.yaml .yamllint.yaml .pre-commit-config.yaml
git add -u
git commit -m "build: lint markdown, yaml, and toml

Assisted-by: AI"
```

---

### Task 9: CI workflow — run pre-commit + actionlint

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the complete `.pre-commit-config.yaml`.
- Produces: a blocking CI job on push/PR.

- [ ] **Step 1: Create `.github/workflows/ci.yml`.**

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install chezmoi
        run: sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin"
      - name: Install shell tooling
        run: |
          sudo apt-get update
          sudo apt-get install -y shellcheck zsh
          curl -fsSL https://github.com/mvdan/sh/releases/download/v3.10.0/shfmt_v3.10.0_linux_amd64 -o /usr/local/bin/shfmt
          sudo chmod +x /usr/local/bin/shfmt
      - name: Initialize chezmoi source (for template hooks)
        run: |
          echo "$HOME/.local/bin" >> "$GITHUB_PATH"
          "$HOME/.local/bin/chezmoi" init --source="$PWD" --no-tty
      - uses: pre-commit/action@v3.0.1
  actionlint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: actionlint
        uses: docker://rhysd/actionlint:latest
        with:
          args: -color
```

- [ ] **Step 2: Lint the workflow locally before pushing.**

Run: `actionlint .github/workflows/ci.yml`
Expected: no output (clean).

- [ ] **Step 3: Validate the chezmoi-init assumption.** The render hook needs chezmoi to know the source. Confirm `chezmoi init --source="$PWD"` + the hook works against a clean checkout:

Run: `pre-commit run chezmoi-templates --all-files`
Expected: `Passed`.

- [ ] **Step 4: Commit, push a branch, open a PR, and confirm CI is green** before merging.

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run pre-commit and actionlint on push/PR

Assisted-by: AI"
```

---

### Task 10: CI — chezmoi apply dry-run across profiles

**Files:**
- Create: `.github/workflows/chezmoi.yml`
- Create: `scripts/ci/chezmoi-config/personal.toml`
- Create: `scripts/ci/chezmoi-config/work.toml`

**Interfaces:**
- Produces: a matrix job proving `chezmoi apply --dry-run` succeeds for each profile against a throwaway HOME.

- [ ] **Step 1: Create CI chezmoi configs** providing the template data the source expects (mirror the real `~/.config/chezmoi/chezmoi.toml` keys: `profile`, `machine`, `hostname`). `personal.toml`:

```toml
[data]
profile = "personal"
machine = "ci"
```

`work.toml`:

```toml
[data]
profile = "work"
machine = "ci"
```

- [ ] **Step 2: Create `.github/workflows/chezmoi.yml`.**

```yaml
name: chezmoi
on:
  push:
    branches: [main]
  pull_request:
jobs:
  apply-dry-run:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        profile: [personal, work]
    steps:
      - uses: actions/checkout@v4
      - name: Install chezmoi
        run: sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin"
      - name: Apply (dry-run) for ${{ matrix.profile }}
        run: |
          export HOME="$RUNNER_TEMP/home-${{ matrix.profile }}"
          mkdir -p "$HOME/.config/chezmoi"
          cp "$GITHUB_WORKSPACE/scripts/ci/chezmoi-config/${{ matrix.profile }}.toml" "$HOME/.config/chezmoi/chezmoi.toml"
          "$RUNNER_TEMP/../chezmoi" --version >/dev/null 2>&1 || true
          chezmoi() { "$HOME/../chezmoi" "$@"; }
          "$HOME/.local/bin/chezmoi" init --source="$GITHUB_WORKSPACE" --no-tty
          "$HOME/.local/bin/chezmoi" apply --dry-run --verbose --no-tty
```

- [ ] **Step 3: Reconcile secret templates.** `private_dot_env.tmpl` and `private_homelab.yaml.tmpl` call Bitwarden and will fail in CI. Confirm they are gated so dry-run skips them on `machine = "ci"`, OR add CI gates. Check:

Run: `grep -rn 'bitwarden\|onepassword\|bw ' home/private_dot_env.tmpl home/private_dot_kube/`
Expected: identify the calls; add `{{ if ne .machine "ci" }}`-style guards (mirroring the existing `.kube` gate) so CI renders without secret managers. Update `.chezmoiignore` if cleaner to ignore them when `machine == "ci"`.

- [ ] **Step 4: Commit + verify the workflow is green on a PR.**

```bash
git add .github/workflows/chezmoi.yml scripts/ci/chezmoi-config/
git add -u
git commit -m "ci: dry-run chezmoi apply for personal and work profiles

Assisted-by: AI"
```

---

### Task 11: Repo tidying

**Files:**
- Delete (pending confirmation): `docs/superpowers/specs/_archive/wip-2026-04-27/`
- Modify: `README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Confirm the archive is dead weight.** It is a 32 KB WIP snapshot from 2026-04-27 (`Brewfile.tmpl`, `Brewfile.work`, `notes.md`, `package-details.toml`).

Run: `git log --oneline -- docs/superpowers/specs/_archive/ | head`
Decision: if nothing references it and it predates the current Brewfile, remove it. **Ask the user before deleting** (it wasn't created this session).

- [ ] **Step 2: README freshness pass.** Skim `README.md` (17.5 KB) for stale claims now that CI/pre-commit exist; add a short "Development / CI" section documenting `pre-commit install` and the checks. Use semantic line breaks.

- [ ] **Step 3: `.gitignore` review.** Ensure CI/editor artifacts (`.ruff_cache/`, `*.log`, `err.log` from the template hook) are ignored.

Run: `cat .gitignore`

- [ ] **Step 4: Commit.**

```bash
git add README.md .gitignore
git commit -m "docs: document CI workflow and tidy repo

Assisted-by: AI"
```

---

### Task 12: Branch protection (optional, needs admin)

**Files:** none (GitHub settings via `gh`).

- [ ] **Step 1: Require the CI checks on `main`.** (Run only with the user's go-ahead; requires admin on the repo.)

```bash
gh api -X PUT repos/nickvigilante/dotfiles/branches/main/protection \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[contexts][]=lint' \
  -f 'required_status_checks[contexts][]=actionlint' \
  -f 'required_status_checks[contexts][]=apply-dry-run (personal)' \
  -f 'required_status_checks[contexts][]=apply-dry-run (work)' \
  -F 'enforce_admins=false' \
  -F 'required_pull_request_reviews=null' \
  -F 'restrictions=null'
```

- [ ] **Step 2: Confirm.**

Run: `gh api repos/nickvigilante/dotfiles/branches/main/protection --jq '.required_status_checks.contexts'`
Expected: the four check contexts listed.

---

## Self-Review

**Spec coverage:**
- pre-commit as source of truth → Tasks 3–8. ✓
- CI runs pre-commit → Task 9. ✓
- chezmoi-aware (templates render, zsh vs bash, dry-run apply) → Tasks 5, 10. ✓
- Convention guards (no vendor attribution, semantic-break-friendly markdown) → Tasks 7, 8. ✓
- Dev tooling declared (packages skill) → Task 1. ✓
- Repo tidying (archive, README, gitignore) → Task 11. ✓
- Strict/blocking → Global Constraints + no `continue-on-error` anywhere; each task fixes violations before committing. ✓
- Branch protection to actually enforce "blocking" → Task 12. ✓

**Open risks flagged for execution (not placeholders — real decisions):**
- Task 10 Step 3: secret-manager templates (`private_dot_env.tmpl`, `private_homelab.yaml.tmpl`) must be gated for `machine = "ci"` or the dry-run fails. This is the most likely CI breakage.
- Task 5: `chezmoi cat` requires an initialized source in CI (handled in Task 9 Step 1 / Task 10 Step 2). If `chezmoi managed` is empty in CI, the hook is a no-op — verify it actually iterates files in CI, not just locally.
- pre-commit hook `rev:` pins are current-as-of-plan; `pre-commit autoupdate` may bump them.

**Type/name consistency:** hook ids (`chezmoi-templates`, `no-vendor-attribution-files/-msg`), script paths (`scripts/ci/lint-chezmoi-templates.sh`, `scripts/ci/no-vendor-attribution.sh`), and CI job names (`lint`, `actionlint`, `apply-dry-run`) are referenced consistently across Tasks 5, 7, 9, 10, 12. ✓

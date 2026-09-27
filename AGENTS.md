# Contributing

This repo is a [chezmoi](https://www.chezmoi.io/) dotfiles setup supporting macOS, Ubuntu,
Fedora, Raspberry Pi, and Windows (Cygwin).

## Repo structure

| Path | Purpose |
|------|---------|
| `home/` | chezmoi source root (`.chezmoiroot = home`); files here map to `~/` |
| `home/*.tmpl` | Rendered by chezmoi at apply time; use `{{ .variable }}` for data |
| `os/linux/` | Linux package lists (`packages.apt`, `packages.snap`, `packages.dnf`) and bootstrap scripts |
| `os/raspberry-pi/` | Pi-specific package list |
| `tests/` | Shell-script integration tests (run by `chezmoi-matrix` CI job) |
| `.github/workflows/ci.yml` | CI; the `ci` job is the single required gate |
| `bootstrap/` | One-liner install scripts (install.sh, install.ps1) |

The config template at `home/.chezmoi.toml.tmpl` generates `~/.config/chezmoi/chezmoi.toml`.
Key data fields: `profile` (personal/work), `machine` (laptop/desktop/server/pi/ephemeral),
`display` (bool), `secrets` (none/bitwarden/1password/both).

## One-time setup

```bash
pre-commit install
```

This installs the pre-commit hooks (shellcheck, shfmt, yamllint, chezmoi template render, secret
scan, and others). The hooks run automatically on every `git commit`. Without this step, commits
may fail CI.

## Validating changes before committing

```bash
# Run every hook against every file — same checks the lint CI job runs
pre-commit run --all-files
```

Fix all findings before opening a PR. The `lint` CI job runs the same command and is a required gate.

## Dry-running on the current machine

```bash
# Shows what chezmoi would change without touching anything
chezmoi apply --dry-run --exclude=externals
```

`--exclude=externals` skips Oh My Zsh and other git-repo fetches so the dry-run works offline
and completes in seconds. Review the diff before every `chezmoi apply`.

To simulate a different profile or machine without touching your real config:

```bash
tmp=$(mktemp -d)
cat > "$tmp/chezmoi.toml" <<EOF
sourceDir = "$HOME/.local/share/chezmoi/home"
destDir   = "$tmp/home"
[diff]
pager = ""
[data]
profile = "personal"
name    = "Test"
email   = "test@example.com"
machine = "laptop"
display = true
secrets = "none"
EOF
chezmoi apply --dry-run --no-pager --exclude=externals --config "$tmp/chezmoi.toml"
rm -rf "$tmp"
```

## CI overview

The `ci` job is the single check that branch protection requires. It passes when all of:

| Job | What it checks | Runs on |
|-----|----------------|---------|
| `lint` | pre-commit hooks (shellcheck, shfmt, yamllint, chezmoi render, secret scan) | push + PR |
| `actionlint` | GitHub Actions workflow syntax | push + PR |
| `commit-messages` | PR title, body, and commit message format | PR only |
| `chezmoi-matrix` | `.chezmoiignore` renders correctly across profile/machine/secrets combos | push + PR |
| `chezmoi-apply-dry-run` | All templates render without error on 6 OS/profile/machine cells | push + PR |
| `ci` | Required gate — depends on all above; treats skipped as success | push + PR |

All checks must pass (or be skipped on push-to-main) before merging.

## Branches and worktrees

Never commit directly to `main`. Use a git worktree for each branch:

```bash
git worktree add .worktrees/<branch-name> -b <branch-name>
# Work from .worktrees/<branch-name>/
```

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/): `type(scope): subject`

- **type**: `feat`, `fix`, `chore`, `ci`, `docs`, `refactor`
- **scope**: `chezmoi`, `packages`, `shell`, `ci`, `brew`, `dotfiles`
- **subject**: imperative, lowercase, no trailing period, ≤ 72 chars
- When AI assisted the work, end the message with `Assisted-by: AI` — never name a specific product

```
feat(packages): add VS Code DNF repo for Fedora

Assisted-by: AI
```

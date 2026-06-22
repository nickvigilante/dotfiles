---
name: packages
description: Use when installing, removing, upgrading, or auditing any system/application package via a package manager (brew, apt, pacman, dnf, pipx, cargo, npm -g, gem, flatpak, snap, mas, VS Code extensions, winget, scoop) on this user's machines. Ensures the change is DECLARED in a chezmoi-tracked manifest so it reproduces across machines, instead of being a one-off install that's forgotten.
---

# Package management (declarative, cross-machine)

This user dumps cross-machine state into their chezmoi dotfiles repo for consistency.
The rule: **installing a package = editing its manifest, not running a bare install.**
A bare `brew install x` on one machine drifts — it won't exist on the others and is lost on reinstall.
Always go through the declarative manifest, then let chezmoi apply it everywhere.

See the **`chezmoi`** skill for source-path/apply/PR mechanics; this skill is about the manifests and managers.

## The pattern (Homebrew — primary)

1. **Brewfile** is the source of truth (chezmoi-managed, e.g. `dot_config/Brewfile` → `~/.config/Brewfile`).
2. A **`run_onchange_`** script re-runs `brew bundle` whenever the Brewfile changes — embed the file's hash so chezmoi detects edits:
   ```sh
   # run_onchange_install-packages.sh.tmpl
   # Brewfile hash: {{ include ".config/Brewfile" | sha256sum }}
   brew bundle --file="$HOME/.config/Brewfile"
   ```
3. **Per-host differences** via templating — common packages everywhere, machine-specific gated:
   ```ruby
   # Brewfile.tmpl
   brew "rtk"            # everywhere (genuine cross-machine use, incl. work)
   brew "git"
   {{ if eq .chezmoi.hostname "personal-box" }}
   cask "some-hobby-app"
   {{ end }}
   ```

**Brewfile entry types** — verified against the installed brew (`grep -rh 'PACKAGE_TYPE =' "$(brew --repository)/Library/Homebrew/bundle"`), **12 types**: `tap`, `brew`, `cask`, `mas` (Mac App Store), `vscode` (VS Code extension), `cargo` (Rust crates), `go` (Go binaries), `npm` (npm globals), `uv` (Python tools), `flatpak` (Linux apps), `krew` (kubectl plugins), `winget` (Windows).
Re-verify on a new machine — the set grows over releases.
(Note: `whalebrew` was **removed**; stale docs/blogs still list it.)

## Workflows

- **Add:** add the line to the Brewfile → `chezmoi apply` (runs `brew bundle`) → commit via PR (see `chezmoi` skill). Installing and recording are one action.
- **Remove:** delete the line → `brew bundle cleanup --file=... --force` removes anything not in the Brewfile → commit.
- **Capture current state into the manifest:** `brew bundle dump --file=~/.config/Brewfile --force` (then prune to what you actually want tracked).
- **Audit drift:** `brew bundle check` (is everything in the Brewfile installed?).

## brew bundle is your near-universal manifest

Those 12 types mean a **single Brewfile declares far more than Homebrew formulae** — it natively covers cargo crates, go binaries, npm globals, uv (Python) tools, flatpaks, krew plugins, winget (Windows), Mac App Store apps, and VS Code extensions.
For all of those, **do NOT make separate manifests** — one `brew bundle` installs them:
```ruby
tap  "homebrew/bundle"
brew "ripgrep"
cask "ghostty"
mas  "Xcode", id: 497799835
vscode "ms-python.python"
cargo  "cargo-edit"
go     "github.com/jesseduffield/lazygit@latest"
npm    "typescript"
uv     "ruff"
flatpak "com.spotify.Client"
krew    "ns"
winget  "Microsoft.PowerToys"   # only applied on the Windows machine
```
Gate platform-specific lines with templating (`{{ if eq .chezmoi.os "darwin" }}` / `"linux"` / hostname).

## What brew bundle does NOT cover (these still need the dump-list + `run_onchange_` pattern)

| Manager | List / export | Notes |
|---|---|---|
| apt (Debian/Ubuntu) | `apt-mark showmanual` | OS packages |
| dnf (Fedora/RHEL) | `dnf repoquery --userinstalled` | OS packages |
| pacman (Arch) | `pacman -Qqe` (`-Qqm` = AUR) | reinstall: `pacman -S --needed - < list` |
| snap | `snap list` | Linux |
| pipx | `pipx list --short` | or just prefer `uv` in the Brewfile |
| **gem** | **Gemfile** (bundler) | its own declarative manifest — use directly |
| **mise / asdf** | **`.tool-versions` / `mise.toml`** | own declarative manifest, preferred for language runtimes |
| **Nix / home-manager** | **`home.packages`** | fully declarative; the config *is* the manifest |

**Bold = its own native declarative manifest** — track that file directly, don't shoehorn into a list+script.
Everything else here: dump the list to a chezmoi-tracked file + a `run_onchange_` installer (same shape as the brew one above).

## Which manager to use (heuristics — starting point; the user will refine)

Pick the first that cleanly applies:
1. **Native OS manager (apt/dnf/pacman)** — for system libraries, daemons, or anything other packages depend on at the OS level. Especially on servers and **Coder workspaces**, where duplicating system libs via brew causes drift/bloat. (Not in the Brewfile.)
2. **`brew`** — general CLI tools/dev utilities available as a bottle. Fastest (prebuilt), one update path, one manifest. The default for most things.
3. **Language type in the Brewfile (`cargo`/`go`/`npm`/`uv`)** — when the tool ships primarily through that ecosystem, isn't in brew, or you want the latest. Still one `brew bundle`.
4. **What-it-IS types** — `cask` (macOS GUI), `flatpak` (Linux GUI), `mas` (Mac App Store-only), `winget` (Windows), `krew` (kubectl plugins), `vscode` (editor extensions).
5. **mise/asdf** — NOT for tools; for pinning language *runtimes* (node/python/go versions). `.tool-versions` is the manifest.

Tie-breakers: prefer prebuilt binaries (brew bottles, `cargo-binstall`) over source builds — faster, especially in ephemeral Coder workspaces.
One tool → one manager (no double-install drift).
If a tool is only needed inside a specific Coder workspace, prefer baking it into that workspace's image/template over global dotfiles.

## Decision guide (where to record)
- One package, used on **all** machines (e.g. rtk) → common section of the Brewfile.
- Machine- or OS-specific → gate with a chezmoi template (`{{ if eq .chezmoi.hostname ... }}` or `{{ if eq .chezmoi.os "darwin" }}`).
- A whole new manager appears on a machine → add a manifest file + a `run_onchange_` installer for it, following the brew pattern.
- Never leave a bare install unrecorded. If you must install ad-hoc to test, note that it still needs to be added to the manifest to persist.

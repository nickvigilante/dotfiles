# Dotfiles cross-platform refactor — design

**Date:** 2026-04-27
**Author:** Nick (with Claude)
**Status:** Approved

## Goals

1. Onboard a new work Mac to the existing dotfiles repo with minimal friction.
2. Add first-class support for ephemeral Ubuntu cloud VMs (primarily AWS-style dev VMs; occasionally short-lived containers) such that a single `curl | sh` command produces a usable full dev environment in 5–10 min.
3. Track Warp and Ghostty terminal configurations in the repo, including a shared color palette consumed by both terminals plus our Gum-based prompt styling.
4. Replace chezmoi's built-in prompts with [Gum](https://github.com/charmbracelet/gum)-driven prompts that auto-detect what they can and only ask for what they must.
5. Capture everything currently installed via Homebrew on the work Mac into the new unified Brewfile.
6. Salvage the recent uncommitted work in a clean PR before the new work begins.

## Non-goals

- Cross-package-manager package mapping (e.g., maintaining a TOML map of "this is the brew name, this is the apt name, this is the dnf name" for each tool). The previous `home/.chezmoidata/package-details.toml` experiment is being abandoned. We treat Homebrew as the universal CLI layer for any "full toolkit" machine (Mac, Linux laptop, ephemeral Ubuntu) and treat native package managers as bootstrap-only.
- Bitwarden support on ephemeral / headless boxes. Bitwarden has no service-account-style auth flow that works without storing the master password; declared unsupported with a clear bootstrap warning. Easy to revisit later.
- A custom `.tmTheme` for `bat` initially. Use a stock dark theme and add custom theming later if needed.
- Major Windows refactor. The Windows bootstrap (`install.ps1`) gets minor compatibility tweaks but is not the focus of this work.

## Approach

**Approach 2 from brainstorming:** unified Brewfile with chezmoi-template axes, plus minimal native package lists for pre-Homebrew bootstrap. Rejected:

- *Approach 1 (minimal change)*: leaves the Mac/Linux Brewfile duplication intact.
- *Approach 3 (full cross-PM mapping)*: maintenance burden too high for a personal repo.

## Data model

The chezmoi data file (`~/.config/chezmoi/chezmoi.toml`, generated from `home/.chezmoi.toml.tmpl`) gains two fields and one new value:

```toml
[data]
profile  = "work"        # work | personal                 (existing)
name     = "Nick"                                          # (existing)
email    = "..."                                           # (existing — never auto-detected, always prompted)
machine  = "ephemeral"   # laptop | desktop | server | pi | ephemeral   (NEW value: ephemeral)
display  = false         # bool                            (NEW)
secrets  = "1password"   # none | bitwarden | 1password | both   (NEW)
```

`machine = "ephemeral"` indicates a cloud VM / container / Codespace. Distinct from `server` because ephemeral implies "fresh OS, full toolkit installed quickly, may be torn down."

`display` is orthogonal to `machine`. Gates GUI casks (Rectangle, DisplayLink, VS Code, Warp, Ghostty), VS Code extensions, and Warp/Ghostty configs themselves.

`secrets` replaces today's implicit "work → 1Password, everyone → Bitwarden" rule with an explicit per-machine choice.

### Architecture support

Linuxbrew supports **`x86_64`** (full bottle coverage) and **`aarch64`** / **`arm64`** (partial bottles, source-builds for the rest). It does **not** support 32-bit ARM (`armv6l`, `armv7l`) — original Pi Zero, old Pi 1/2/3 in 32-bit mode, miscellaneous SBCs.

The bootstrap auto-detects `arch` via `uname -m` and the Homebrew install scripts gate on it (see "Run-script flow"). On 32-bit ARM machines:

- `run_once_00-install-homebrew` exits successfully without installing brew.
- `run_after_install-packages` falls through to the apt branch even when `.machine != "pi"`.
- If `.machine` was auto-detected as something other than `pi` on a 32-bit ARM box (rare — generally only happens on weird SBCs), bootstrap warns the user that they may want to set `--machine pi` explicitly so the Pi-specific apt list (`os/raspberry-pi/packages.apt`) is used instead of the generic Linux one.

**Pi-fleet note:** Pi 4 / Pi 5 / Pi Zero 2 W are `aarch64` and *could* technically use Linuxbrew, but bottle coverage is poor and source-builds are slow on a Pi. The `.machine == "pi"` gate routes them to apt regardless of arch — that's the right default. If you ever want Linuxbrew on a beefier Pi, override by setting `.machine` to `laptop` or `server` instead of `pi`.

### Auto-detection rules

| Field | Detector |
|---|---|
| `os` | `uname -s` |
| `arch` | `uname -m` — values: `x86_64`, `aarch64`/`arm64`, `armv7l`, `armv6l`. Used to gate Homebrew install (see "Architecture support" below). |
| `name` | `git config --global user.name` if set |
| `email` | always prompted (never auto-detected; user preference) |
| `display` (macOS) | `true` |
| `display` (native Windows) | `true` |
| `display` (WSL) | `false` (detected via `$WSL_DISTRO_NAME` or `microsoft`/`WSL` in `/proc/version`) |
| `display` (Linux non-WSL) | `[ -n "$DISPLAY$WAYLAND_DISPLAY" ]` |
| `machine = ephemeral` | `[ -f /.dockerenv ]`, `[ -n "$CODESPACES" ]`, `$AWS_EXECUTION_ENV`, EC2/GCE/Azure metadata HTTP probes (200ms timeout), `dmidecode` vendor match (Amazon/Google/QEMU/VMware) |
| `machine = pi` | `/proc/device-tree/model` contains "Raspberry Pi" |
| `machine = laptop`/`desktop` | macOS `system_profiler SPHardwareDataType` "Model Name", or fallback Gum prompt |
| `secrets` | derived from `profile`: work → `1password`, personal → `none`. Override via `--secrets` / `$DOTFILES_SECRETS`. |

## Bootstrap flow

`bootstrap/install.sh` is rewritten to:

1. **Detect OS/arch.** Bail clearly on unsupported platforms.
2. **Pre-flight disk check.** Required free space: macOS ~12 GB, Linux+display ~8 GB, Linux headless ~5 GB. If insufficient, exit with Gum-rendered error.
3. **Install bootstrap-only essentials.** macOS: nothing (Homebrew handles Xcode CLI tools). Ubuntu/Debian/Pi: `sudo apt-get install -y curl git zsh ca-certificates build-essential file procps`. Fedora: equivalent dnf install.
4. **Download Gum binary** (pinned version, checksum verified) to `~/.local/bin/gum.tmp`.
5. **Auto-detect machine config** per the table above.
6. **Pre-install secret CLIs based on `--secrets`**: install `bw` and/or `op` via official direct-download or apt before chezmoi init. **This is critical**: chezmoi templates reference these tools at *render* time, before the Brewfile's `run_*` script can install them. (See "Failure modes" below.)
7. **Authenticate secret managers** if applicable:
   - Bitwarden: `bw login` (interactive) → `BW_SESSION=$(bw unlock --raw)`.
   - 1Password: if `OP_SERVICE_ACCOUNT_TOKEN` set, no signin needed; otherwise `op signin` (interactive, sets up Keychain on Mac).
8. **Gum-prompt only what's still unknown** (profile, machine, email, display fallback, secrets choice if not supplied).
9. **Install chezmoi.**
10. **`chezmoi init --apply`** with all answers passed as `--promptString` / `--promptChoice` / `--promptBool` flags so the template never re-prompts.
11. After all `run_*` scripts complete, verify brew-installed `gum` is on `PATH`; remove `~/.local/bin/gum.tmp`.

### CLI flags

```
install.sh \
  --profile work|personal \
  --machine laptop|desktop|server|pi|ephemeral \
  --display | --no-display \
  --secrets none|bitwarden|1password|both \
  --op-token <token>          # writes ~/.config/op/token chmod 600
  --non-interactive           # any unset value → exit 1, no prompts
```

Equivalents via env vars: `DOTFILES_PROFILE`, `DOTFILES_MACHINE`, `DOTFILES_DISPLAY=1|0`, `DOTFILES_SECRETS`, `DOTFILES_NON_INTERACTIVE=1`, `OP_SERVICE_ACCOUNT_TOKEN`.

### Replayable rerun command

`home/.chezmoi.toml.tmpl` renders a comment header showing the equivalent non-interactive bootstrap command for the current machine. Copy/paste reproduces this machine's setup elsewhere:

```toml
# ────────────────────────────────────────────────────────────
# Re-run this exact bootstrap on another machine:
#
#   sh -c "$(curl -fsSL .../install.sh)" -- \
#     --profile work \
#     --machine ephemeral \
#     --secrets 1password \
#     --no-display \
#     --non-interactive
# ────────────────────────────────────────────────────────────

[data]
profile = "work"
…
```

### Update flow

`chezmoi update` already handles "fetch latest + apply." Add a thin wrapper `~/.local/bin/dotfiles`:

```
dotfiles update    # chezmoi update + update-packages --force
dotfiles doctor    # health check (see Smoke test below)
```

The existing 24h-throttled background `update-packages` keeps working unchanged.

## Package layout

### File structure (after migration)

```
home/
  .chezmoidata/
    palette.toml                                  # NEW — single source-of-truth color palette
  dot_config/
    dotfiles/
      Brewfile.tmpl                               # NEW — unified Brewfile, chezmoi-rendered
      lib/
        gum.sh.tmpl                               # NEW — Gum styling env vars from palette
    ghostty/
      config.tmpl                                 # NEW — Ghostty config
      themes/
        vigilante.tmpl                            # NEW — Ghostty theme from palette
  dot_warp/
    keybindings.yaml                              # NEW — captured from current machine
    themes/
      vigilante.yaml.tmpl                         # NEW — Warp theme from palette
    launch_configurations/                        # NEW — captured
    workflows/                                    # NEW — captured
  run_after_install-packages.sh.tmpl              # NEW — replaces run_once_04 + run_onchange_install-packages
  run_once_07-set-default-shell.sh.tmpl           # NEW — chsh to zsh on Linux

os/
  linux/
    bootstrap.apt                                 # RENAMED from packages.apt — minimal pre-Homebrew prereqs only
    bootstrap.dnf                                 # NEW — Fedora equivalent
  raspberry-pi/
    packages.apt                                  # unchanged

# DELETED
os/macos/Brewfile
os/macos/Brewfile.work
os/linux/Brewfile.linux
home/run_once_04-install-packages.sh.tmpl         # logic absorbed into run_after_install-packages.sh.tmpl
home/run_onchange_install-packages.sh.tmpl        # ditto
```

### Unified Brewfile axes

The single `home/dot_config/dotfiles/Brewfile.tmpl` gates each line on these axes (Go-template conditionals, all data-driven):

| Axis | Source | Used for |
|---|---|---|
| `.chezmoi.os == "darwin"` | chezmoi built-in | macOS-only formulae (`mas`, `duti`, `coreutils`, GNU substitutes), all casks, all `vscode` extensions |
| `.chezmoi.os == "linux"` | chezmoi built-in | Linux-only formulae (rare) |
| `.profile == "work"` | machine data | Work tooling (awscli, kubernetes-cli, helm, vale, …) and work casks (Slack, Notion, Linear, …) |
| `.profile == "personal"` | machine data | Personal apps (Spotify, Signal, Firefox, …) |
| `.display` | machine data | All GUI casks (Rectangle, DisplayLink, VS Code, Warp, Ghostty), `vscode` extensions |
| `.secrets ∈ {bitwarden, both}` | machine data | `bitwarden-cli` |
| `.secrets ∈ {1password, both}` | machine data | `1password-cli` |
| `.machine == "pi"` | machine data | Skips the unified Brewfile entirely; uses `os/raspberry-pi/packages.apt` instead |

`.machine == "ephemeral"` deliberately gates *nothing* in the Brewfile. The orthogonal axes (`.display`, `.chezmoi.os`, `.profile`) already select the right packages; ephemeral is purely a label that influences bootstrap behavior (defaults like `display=false`, secrets handling).

### Brewfile content sourcing

Initial population: `brew bundle dump --force --describe` from the current work Mac. Each line manually classified (cross-platform CLI / mac-only / work-only / display-only / etc.) with user input on ambiguous cases. Existing `home/Brewfile.tmpl` WIP draft is folded in as additional input.

## Run-script flow

| # | File | Status |
|---|---|---|
| 00 | `run_once_00-install-homebrew.sh.tmpl` | Existing, **gate updated**. New gate: `(eq .chezmoi.os "darwin") \|\| (and (eq .chezmoi.os "linux") (ne .machine "pi") (or (eq .chezmoi.arch "amd64") (eq .chezmoi.arch "arm64")))`. The `arch` check protects against 32-bit ARM machines (Pi Zero original, old SBCs) where Linuxbrew won't compile. On macOS, both Apple Silicon (`arm64`) and Intel (`amd64`) are fully supported. |
| 01 | `run_once_01-install-bootstrap-prereqs.sh.tmpl` | NEW. Linux-only. Reads `os/linux/bootstrap.{apt,dnf}` and ensures prereqs are present. Idempotent defense in depth (in case someone clones and `chezmoi apply`s without going through bootstrap). |
| 02 | `run_once_02-install-uv.sh.tmpl` | unchanged |
| 03 | `run_once_03-setup-python-venv.sh.tmpl` | unchanged |
| — | `run_after_install-packages.sh.tmpl` | NEW. **Always-run, runs after all `run_once_*` scripts and after file-target rendering** (chezmoi's `run_after_*` convention guarantees this ordering — important because Homebrew must be installed and the Brewfile rendered before this runs). Two branches:<br>• `.machine == "pi"`: hash-and-compare against `os/raspberry-pi/packages.apt`, run `apt update + install` only if it changed (stamp file at `$XDG_CACHE_HOME/dotfiles/pi-packages.stamp`).<br>• All other platforms: run `brew bundle check --quiet` first (fast — ~300-800 ms). If satisfied, exit. If not, run `brew bundle install` with a resilient per-line fallback that catches single-package failures, accumulates them, and prints a Gum-styled summary at the end. |
| 05 | `run_once_05-macos-defaults.sh.tmpl` | unchanged |
| 06 | `run_once_06-touchid-sudo.sh.tmpl` | unchanged |
| 07 | `run_once_07-set-default-shell.sh.tmpl` | NEW. Non-Pi. Adds brew/apt-installed zsh to `/etc/shells` if missing; runs `chsh -s $(command -v zsh) $USER`. macOS no-op (already zsh). |

### Why an always-run script over `run_onchange_*`

Considered two approaches:

- **A:** put Brewfile content in `.chezmoitemplates/Brewfile`, indirect from a passthrough `Brewfile.tmpl`, hash-trigger via `{{ template "Brewfile" . | sha256sum }}` in a `run_onchange_*` script.
- **B:** keep Brewfile content in `home/dot_config/dotfiles/Brewfile.tmpl` directly, use an always-run `run_*` script that calls `brew bundle check --quiet` as the trigger.

**Chose B** because: (i) it self-heals against drift — manually uninstalling a package and running `chezmoi apply` re-installs it; (ii) the Brewfile lives at the path its name implies (no `.chezmoitemplates/` indirection); (iii) the per-apply cost is bounded (~300-800 ms) and `chezmoi apply` is invoked manually, not on every shell start.

### Resilient brew install (pseudocode)

```bash
if brew bundle check --file="$BREWFILE" --quiet; then
  exit 0
fi
if brew bundle install --file="$BREWFILE" $bundle_flags; then
  exit 0
fi
# Per-line fallback
failed=()
for line in $(grep -E '^(brew|cask|vscode) ' "$BREWFILE"); do
  case "$line" in
    brew\ *)   brew install      "$pkg" || failed+=("$pkg") ;;
    cask\ *)   brew install --cask "$pkg" || failed+=("cask:$pkg") ;;
    vscode\ *) command -v code >/dev/null && (code --install-extension "$pkg" || failed+=("vscode:$pkg")) ;;
  esac
done
if (( ${#failed[@]} )); then
  gum style --foreground 213 --bold "The following packages failed:"
  printf '  • %s\n' "${failed[@]}"
fi
```

`bundle_flags` includes `--no-vscode` when `command -v code` fails, etc.

## Secrets handling

Auth mechanism per `secrets` value:

| `.secrets` | Real machine | Ephemeral |
|---|---|---|
| `none` | `~/.env` renders empty | same |
| `bitwarden` | `bw login` → `bw-apply` to unlock + apply | **Not supported.** Bootstrap warns; user falls back to `none`. |
| `1password` | `op signin` once → system Keychain on Mac | `OP_SERVICE_ACCOUNT_TOKEN` env var, no signin |
| `both` | both above | only 1Password half works |

### Template gating

`home/private_dot_env.tmpl` is reshaped to gate on `.secrets` instead of `.profile`:

```go-template
{{- if eq .secrets "none" }}
# This machine is configured with secrets = "none". No secrets are loaded.
{{- end }}

{{- if or (eq .secrets "bitwarden") (eq .secrets "both") }}
# Bitwarden secrets — add lines like:
# export GITHUB_TOKEN="{{ "{{" }} (bitwarden "item" "GitHub PAT").login.password {{ "}}" }}"
{{- end }}

{{- if or (eq .secrets "1password") (eq .secrets "both") }}
# 1Password secrets — add lines like:
# export AWS_ACCESS_KEY_ID="{{ "{{" }} onepasswordRead "op://Work Vault/AWS/access_key_id" {{ "}}" }}"
{{- end }}
```

`bw-apply` similarly gated to short-circuit on machines without Bitwarden.

### `OP_SERVICE_ACCOUNT_TOKEN` storage on ephemeral

Tightly scoped: bootstrap writes the token to `~/.config/op/token` (chmod 600, user-owned), and `.zshenv` sources it when `secrets ∈ {1password, both}`. Easier to loosen later (e.g., to `/etc/profile.d/op.sh` for system-wide) than to tighten.

## Terminal configs and shared palette

### Tracked files

| App | Tracked path | Renders to |
|---|---|---|
| Warp | `home/dot_warp/themes/` | `~/.warp/themes/` |
| Warp | `home/dot_warp/keybindings.yaml` | `~/.warp/keybindings.yaml` |
| Warp | `home/dot_warp/launch_configurations/` | `~/.warp/launch_configurations/` |
| Warp | `home/dot_warp/workflows/` | `~/.warp/workflows/` |
| Ghostty | `home/dot_config/ghostty/config.tmpl` | `~/.config/ghostty/config` |
| Ghostty | `home/dot_config/ghostty/themes/` | `~/.config/ghostty/themes/` |

Tracked unconditionally (not gated by `.display`); harmless on machines where the apps aren't installed.

### Shared palette

`home/.chezmoidata/palette.toml` holds named-token color values:

```toml
[palette.bg]
default     = "#0d0e1a"
panel       = "#15172a"
highlight   = "#2a2b45"

[palette.fg]
default     = "#c8d1f0"
dim         = "#6d7396"
bright      = "#ffffff"

[palette.accent]
green       = "#7df7c1"
blue        = "#82aaff"
purple      = "#c792ea"
cyan        = "#5ccfe6"
violet      = "#8e7df7"

[palette.semantic]
success     = "#7df7c1"
info        = "#82aaff"
warning     = "#f7c97d"
error       = "#f78ab1"

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

Starter values are a Tokyo Night Storm × Material Ocean blend with a green/teal push — vibrant, dark, cool-leaning, higher contrast than Catppuccin Mocha. Outrun-leaning. The user can edit and `chezmoi apply` to regenerate all consumer themes.

### Consumers

- `home/dot_warp/themes/vigilante.yaml.tmpl` → Warp theme YAML
- `home/dot_config/ghostty/themes/vigilante.tmpl` → Ghostty theme syntax
- `home/dot_config/ghostty/config.tmpl` → sets `theme = vigilante`, font, etc.
- `home/dot_config/dotfiles/lib/gum.sh.tmpl` → exports `GUM_*` env vars (`GUM_INPUT_PROMPT_FOREGROUND`, `GUM_CONFIRM_SELECTED_BACKGROUND`, etc.) sourced by all our Gum-using scripts
- `home/dot_config/bat/config.tmpl` → sets `--theme=` to a stock dark theme (custom `.tmTheme` deferred)

### Iteration workflow

Treat Warp's in-app theme editor as **off-limits** for managed themes (chezmoi-managed file always wins).

To iterate on the palette: in Warp, duplicate the current theme as `vigilante-wip`, edit visually, then run `dotfiles palette-import vigilante-wip` (a small helper script — Phase 5):

1. Reads `~/.warp/themes/vigilante-wip.yaml`.
2. Maps colors back to semantic tokens (Gum-prompts for ambiguous mappings).
3. Updates `home/.chezmoidata/palette.toml`.
4. Runs `chezmoi apply` so all consumer themes regenerate.
5. Optionally deletes `vigilante-wip`.

## Migration plan

Phased; each phase is independently shippable. Target shape: **3 PRs**, with the underlying phase boundaries available as natural split points if the implementation moves faster than expected.

### Phase 0 (PR A) — Cleanup

- Salvage current real edits: `os/macos/Brewfile` (`age` → `rage`, drop the deprecated `homebrew/cask-fonts` tap, remove the stray `# sldkfmldksfdml` line), `home/.chezmoi.toml.tmpl` (formatting + `[diff] pager = "delta"`).
- Re-check stale staging on `home/dot_gitconfig.tmpl`.
- Inspect actual diffs on `home/run_once_04-install-packages.sh.tmpl` and `home/run_onchange_install-packages.sh.tmpl`; salvage line-by-line.
- Delete junk artifacts: `cask.json`, `formula.json`, `macos-versions.json`, `db.sql.zst`.
- Add `.gitignore` entries: `*.json` (root), `*.zst`, `*.sql`, `notes.md`.
- Move WIP files to `docs/superpowers/specs/_archive/wip-2026-04-27/` for design archaeology: `home/Brewfile.tmpl`, `home/Brewfile.work`, `home/.chezmoidata/package-details.toml`, `notes.md`.

### Phase 1+2+3 (PR B) — Foundation, Brewfile, bootstrap

Phase 1 — Foundation:

- Add `display` and `secrets` data fields to `home/.chezmoi.toml.tmpl`. Add `ephemeral` as a fifth `machine` value. Add WSL/Windows display defaults.
- Add `home/.chezmoidata/palette.toml` with starter values.
- Add the rerun-comment header to `home/.chezmoi.toml.tmpl`.

Phase 2 — Unified Brewfile:

- Run `brew bundle dump --force --describe` on the current work Mac; classify each line interactively; produce `home/dot_config/dotfiles/Brewfile.tmpl`.
- Create `home/run_after_install-packages.sh.tmpl` (always-run, with resilient fallback; handles both Pi apt and brew bundle paths).
- Rename `os/linux/packages.apt` → `os/linux/bootstrap.apt`; trim to minimal prereqs.
- Add `os/linux/bootstrap.dnf`.
- Delete `os/macos/Brewfile`, `os/macos/Brewfile.work`, `os/linux/Brewfile.linux`.
- Add `run_once_07-set-default-shell.sh.tmpl`.
- Delete `run_once_04-install-packages.sh.tmpl` and `run_onchange_install-packages.sh.tmpl` entirely; Pi apt logic moves into `run_after_install-packages.sh.tmpl` as a `.machine == "pi"` branch.

Phase 3 — Bootstrap rewrite:

- Add `bootstrap/lib/detect.sh` — pure-shell platform detection (OS/arch/cloud/WSL/display/ephemeral).
- Add `bootstrap/lib/preflight.sh` — disk space check.
- Add `bootstrap/lib/gum-bootstrap.sh` — pinned Gum download with checksum verification.
- Add `home/dot_config/dotfiles/lib/gum.sh.tmpl` — palette-styled Gum env vars.
- Rewrite `bootstrap/install.sh` per the bootstrap-flow section.

### Phase 4+5+6 (PR C) — Ephemeral, terminals, polish

Phase 4 — Ephemeral + 1Password:

- Add `bootstrap/lib/secrets.sh` — pre-installs `bw`/`op` based on `--secrets`; handles `OP_SERVICE_ACCOUNT_TOKEN` storage at `~/.config/op/token` chmod 600.
- Update `home/private_dot_env.tmpl` to gate on `.secrets`.
- Update `bw-apply` in `home/dot_config/shell/functions.zsh` to short-circuit when Bitwarden isn't part of `.secrets`.
- End-to-end test on a real Ubuntu cloud VM.

Phase 5 — Terminal configs:

- `chezmoi add ~/.warp/themes ~/.warp/keybindings.yaml ~/.warp/launch_configurations ~/.warp/workflows ~/.config/ghostty`.
- Templatize `home/dot_warp/themes/vigilante.yaml.tmpl` and `home/dot_config/ghostty/themes/vigilante.tmpl` from palette.
- Set `home/dot_config/ghostty/config.tmpl` with theme + font.
- Add `~/.local/bin/dotfiles palette-import` script.
- Document the off-limits-UI rule in README.

Phase 6 — Update flow + smoke test:

- Add `home/dot_local/bin/executable_dotfiles` — thin wrapper (`dotfiles update`, etc.).
- Add `home/dot_local/bin/executable_dotfiles-doctor` — health check.
- Update README.

## Failure modes and mitigations

| Failure | Mitigation |
|---|---|
| Single Brewfile package fails (renamed, removed, broken cask) | Per-line fallback wrapper; Gum-rendered failure summary; rest of bundle still installs |
| Gum binary download fails | Bootstrap aborts at that step with a clear error pointing at `--non-interactive` mode (which doesn't need Gum) as a fallback |
| Gum binary checksum mismatch | Hard fail; do not run an untrusted binary |
| `chezmoi init` fails | Bootstrap propagates exit code; nothing partial committed |
| Template references `bitwarden` / `onepasswordRead` but the CLI isn't installed at render time | **Bootstrap pre-installs `bw` and/or `op` based on `--secrets` flag, before `chezmoi init`** |
| `OP_SERVICE_ACCOUNT_TOKEN` invalid | `op` errors propagate from first `onepasswordRead`; bootstrap suggests checking the token |
| User has hand-edited a chezmoi-managed file (e.g. Warp theme via UI) | chezmoi's standard diff/refuse-without-`--force` behavior; README documents UI-off-limits rule |
| `chsh` fails (zsh not in `/etc/shells`, requires sudo, or interactive password prompt) | `run_once_07` adds zsh to `/etc/shells` first; if `chsh` still fails, prints manual command and exits 0 (non-fatal) |
| `display=true` set on a machine without a real display | Per-line fallback catches GUI cask install failures |
| Bootstrap interrupted mid-flight | Most steps idempotent; re-running resumes |
| WSL detection false negative (WSL2 image without `WSL_DISTRO_NAME`) | Fallback `/proc/version` grep covers it; `--no-display` always available as explicit override |
| 32-bit ARM machine (Pi Zero original, old SBCs) where Linuxbrew won't compile | Bootstrap detects `armv6l`/`armv7l` via `uname -m`, skips Homebrew install entirely, falls through to apt path. If `.machine != "pi"` on 32-bit ARM, bootstrap warns to set `--machine pi`. |
| Insufficient disk space | Pre-flight check (Phase 3) exits before any download |
| Disk full mid-install | `dotfiles-doctor` reports brew/apt failures; user re-runs after freeing space |

## Acceptance criteria

1. **Fresh Mac:** `bootstrap/install.sh` → answers via Gum → 5–10 min later, full toolkit installed, `~/.env` populated from 1Password, Warp + Ghostty themed, `dotfiles-doctor` all green.
2. **Fresh Ubuntu ephemeral:** `OP_SERVICE_ACCOUNT_TOKEN=ops_… curl … | sh -s -- --profile work --machine ephemeral --secrets 1password --no-display --non-interactive` → 5–10 min later, zsh as default shell, full CLI toolkit via Linuxbrew, `~/.env` populated, no GUI cruft, `dotfiles-doctor` all green for the headless case.
3. **Existing personal Mac:** `chezmoi update` post-merge produces no surprising diffs — same packages installed, same shell behavior. Verified by snapshot of `brew leaves` before/after.
4. **Re-run idempotence:** running bootstrap a second time on either machine is fast no-op.

## Open questions / future work

- Should `dotfiles-doctor` move earlier (development aid) than Phase 6? Currently Phase 6.
- Custom `bat` `.tmTheme` from palette: deferred until needed.
- Bitwarden API-key flow on ephemeral (would require interactive master password): deferred.
- Windows native bootstrap parity: out of scope for this work.
- Linux Warp/Ghostty support on display-having Linux laptops: configs are tracked but untested in that combination.

## Execution preferences (captured from brainstorming)

- **Subagent-driven execution preferred.**
- Target completion in one work session if possible (3-PR shape).
- Ratified design choices: Approach 2 / Approach B for Brewfile install / Tokyo Night × Material Ocean palette / treat Warp UI as off-limits / `OP_SERVICE_ACCOUNT_TOKEN` scoped tightly at `~/.config/op/token` / Bitwarden ephemeral declared not supported.

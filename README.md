# dotfiles

Personal dotfiles managed with [chezmoi](https://www.chezmoi.io/). Supports macOS, Ubuntu, Fedora, Raspberry Pi (Raspbian/Ubuntu), and Windows (Cygwin).

## Quick start

### macOS / Linux / Raspberry Pi / Ephemeral cloud VMs

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/nickvigilante/dotfiles/main/bootstrap/install.sh)"
```

The bootstrap script downloads [Gum](https://github.com/charmbracelet/gum) for prompts, auto-detects what it can (OS, arch, WSL, ephemeral cloud VM, display, hostname, existing git config), and only asks Gum-prompted questions for what it can't infer.

| Prompt          | Options / values                                                 |
| --------------- | ---------------------------------------------------------------- |
| Profile         | `work` or `personal`                                             |
| Full name       | used in git config                                               |
| Email address   | used in git config (always prompted; never auto-detected)        |
| Machine role    | `laptop`, `desktop`, `server`, `pi`, or `ephemeral`              |
| Display         | `true`/`false` — gates GUI casks, terminal apps, VS Code         |
| Secret managers | `none`, `bitwarden`, `1password`, or `both`                      |

Answers are saved to `~/.config/chezmoi/chezmoi.toml`. The file is generated from `home/.chezmoi.toml.tmpl` and includes a comment header showing the equivalent **non-interactive bootstrap command** for the current machine — copy/paste reproduces the same setup elsewhere. Edit later with `chezmoi edit-config`.

### Non-interactive bootstrap (for cloud-init / Terraform / scripts)

```sh
bash -c "$(curl -fsSL .../install.sh)" -- \
  --profile work \
  --machine ephemeral \
  --secrets 1password \
  --no-display \
  --non-interactive
```

Available flags: `--profile`, `--name`, `--email`, `--machine`, `--display | --no-display`, `--secrets`, `--op-token <token>`, `--non-interactive`. Each has an env-var equivalent (`DOTFILES_PROFILE`, `DOTFILES_DISPLAY=1|0`, etc.). With `--non-interactive`, any unspecified field that can't be auto-detected aborts with an error.

### Windows (elevated PowerShell)

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\bootstrap\install.ps1
```

---

## What gets installed and configured

### Shell (zsh + Oh My ZSH)

- `.zshenv` — PATH, uv/Python setup, secrets loading. Sourced by all shells including scripts.
- `.zprofile` — Homebrew initialization for login shells.
- `.zshrc` — Oh My ZSH, plugins, aliases, functions, profile-specific config.

Oh My ZSH and its plugins are managed as external git repos by chezmoi (see `.chezmoiexternal.toml`) and updated weekly on `chezmoi update`. Auto-update runs without prompting.

Shell config is split into fragments under `~/.config/shell/`:

| File                | Purpose                                            |
| ------------------- | -------------------------------------------------- |
| `aliases.zsh`       | Cross-platform aliases                             |
| `aliases_macos.zsh` | macOS-only aliases (Finder, Homebrew, pbcopy)      |
| `aliases_linux.zsh` | Linux-only aliases (apt/dnf shortcuts, clipboard)  |
| `functions.zsh`     | Utility functions (mkcd, extract, serve, groot, …) |
| `exports.zsh`       | Editor, pager, fzf, bat, and profile exports       |
| `work.zsh`          | Work profile additions                             |
| `personal.zsh`      | Personal profile additions                         |

### Python (uv only)

[uv](https://docs.astral.sh/uv/) is installed via its official installer (not Homebrew) so it works identically on all platforms. A machine-wide default venv is created at `~/venv` and sits first on `PATH`, making it the default `python` and `pip`. Project-specific venvs (`.venv/` in the project directory) take precedence when active.

No pyenv, conda, or system Python involvement.

### Package management

One unified Brewfile, gated on (OS × profile × display × secrets) axes:

| Layer                   | Source                                       | Used by                                                   |
| ----------------------- | -------------------------------------------- | --------------------------------------------------------- |
| Cross-platform CLI tools | `home/dot_config/dotfiles/Brewfile.tmpl`    | macOS, Linux laptops, ephemeral cloud VMs (via Linuxbrew) |
| Pre-Homebrew prereqs (apt) | `os/linux/bootstrap.apt`                  | Ubuntu/Debian — installs minimal `curl git zsh build-essential` before Homebrew |
| Pre-Homebrew prereqs (dnf) | `os/linux/bootstrap.dnf`                  | Fedora                                                    |
| Pi-only packages        | `os/raspberry-pi/packages.apt`              | Raspberry Pi (Homebrew not used on Pi)                    |
| Windows packages        | `os/windows/packages.choco`                  | Windows (Chocolatey)                                      |

The Brewfile uses chezmoi Go-template guards on `.chezmoi.os`, `.profile`, `.display`, and `.secrets` to install the right slice for each machine. Casks and VS Code extensions are gated on `.display && .chezmoi.os == "darwin"` (Linux Homebrew has no casks anyway). 32-bit ARM machines (original Pi Zero, old SBCs) are detected via `.chezmoi.arch` and skip Homebrew entirely.

**Adding a package:** edit `home/dot_config/dotfiles/Brewfile.tmpl` (gated under the right `{{ if ... }}` block) and run `chezmoi apply`. The always-run `run_after_install-packages.sh.tmpl` calls `brew bundle check` first (fast no-op when satisfied) and only installs if drift is detected. Single-package failures are reported at the end without blocking the whole sync.

**Pi caveat:** Linuxbrew on `aarch64` Pi 4/5 works but bottle coverage is poor and source-builds are slow. The `.machine == "pi"` gate routes Pis to the apt-only flow regardless of arch — generally the right default. Override by setting `.machine` to `laptop`/`server` if you really want Homebrew on a beefier Pi.

### Updates and maintenance

```sh
dotfiles update          # chezmoi update + update-packages --force
dotfiles doctor          # health check (machine + tooling + Brewfile + secrets)
dotfiles palette-import  # show the manual Warp-theme-iteration workflow
```

`dotfiles doctor` walks the data axes (os, arch, machine, display, profile, secrets) and verifies your tooling, files, Brewfile state, and `~/.env` permissions all match expectations. Run it whenever something feels off.

A background `~/.local/bin/update-packages` script auto-fires on every new shell, throttled to once per 24 h via `~/.cache/dotfiles/last_update`. Run manually with `update-packages` or `update-packages --force` to bypass the throttle.

### macOS-specific

- **Touch ID for sudo** — enabled via `/etc/pam.d/sudo_local` (survives macOS system updates, unlike `/etc/pam.d/sudo`). Configured automatically on first `chezmoi apply`.
- **System defaults** — Finder (show extensions, path bar, list view), Dock (auto-hide, no recent apps), keyboard (fast repeat, no autocorrect), screenshots saved to `~/Desktop/Screenshots`.

---

## Profiles

The `work` and `personal` profiles affect:

- **Git email** — different address per profile
- **Shell config** — `work.zsh` or `personal.zsh` is sourced
- **Packages** — work-only and personal-only sections in the unified `Brewfile.tmpl` are gated by `{{ if eq .profile "work" }}` / `personal`
- **Oh My ZSH plugins** — e.g. `aws` plugin enabled for work profile
- **Exports** — profile-specific environment variables in `exports.zsh`
- **Secrets default** — `work` defaults to `secrets = "1password"`, `personal` defaults to `secrets = "none"`

To switch profiles on an existing machine, edit `~/.config/chezmoi/chezmoi.toml` and run `chezmoi apply`.

## Display, machine role, and ephemeral cloud VMs

Three axes beyond profile:

- **`.display`** — `true`/`false`. Gates GUI casks (Rectangle, DisplayLink, VS Code, Warp, Ghostty), VS Code extensions, terminal-app config files. Auto-detected: macOS/Windows always `true`; Linux uses `$DISPLAY`/`$WAYLAND_DISPLAY`; WSL is forced `false` (treated as headless).
- **`.machine`** — `laptop`, `desktop`, `server`, `pi`, or `ephemeral`. `ephemeral` is for cloud VMs / containers / Codespaces (auto-detected via `/.dockerenv`, `$CODESPACES`, EC2/GCE metadata probes). `pi` skips Homebrew entirely and uses apt-only.
- **`.secrets`** — `none`, `bitwarden`, `1password`, or `both`. Drives `~/.env` template gating, `bw-apply` behavior, and which CLIs (bw/op) get pre-installed.

### Ephemeral cloud VMs (e.g., AWS EC2 dev box)

Bootstrap detects ephemeral environments automatically. For non-interactive provisioning (cloud-init / Terraform `user_data`), pre-set the 1Password service-account token in the VM's environment:

```sh
export OP_SERVICE_ACCOUNT_TOKEN="ops_..."
bash -c "$(curl -fsSL .../install.sh)" -- \
  --profile work --machine ephemeral --secrets 1password \
  --no-display --non-interactive
```

Bootstrap stores the token at `~/.config/op/token` (chmod 600), and `~/.zshenv` sources it for every shell. `op whoami` and `chezmoi`'s `onepasswordRead` will work without an interactive `op signin`.

**Bitwarden is unsupported on ephemeral / non-interactive boxes** — the master-password unlock step has no service-account equivalent. Use `--secrets none` or `--secrets 1password` on ephemeral.

## Terminal configs

[Warp](https://www.warp.dev) and [Ghostty](https://ghostty.org) configs live under `home/dot_warp/` and `home/dot_config/ghostty/` respectively. Both consume `home/.chezmoidata/palette.toml` — a single source-of-truth color palette (Tokyo Night Storm × Material Ocean blend) — so changing one hex value in the palette regenerates both terminals' themes plus Gum prompt styling on the next `chezmoi apply`.

The included theme is named **Vigilante**. To iterate:

1. In Warp: duplicate the Vigilante theme as `vigilante-wip`, edit visually, save.
2. Open `~/.warp/themes/vigilante-wip.yaml` and copy hex values into `home/.chezmoidata/palette.toml`, mapping them to the appropriate semantic tokens (`palette.bg.default`, `palette.accent.green`, `palette.ansi.red`, etc.).
3. `chezmoi apply` — Warp + Ghostty + Gum lib all regenerate from the new palette.

⚠️ **Warp's in-app theme editor is off-limits for managed themes.** chezmoi's rendered file always wins on the next apply.

---

## Secrets and environment variables

`~/.env` (chmod 600) is generated by chezmoi from `home/private_dot_env.tmpl` and sourced by `.zshenv` on every shell start. The template pulls values from your password managers at apply time — plaintext secrets are never stored in this repo.

### Per-machine secret manager choice

The `.secrets` data field controls which managers are active on this machine:

| `.secrets`    | Bitwarden | 1Password | Notes                                                                  |
| ------------- | :-------: | :-------: | ---------------------------------------------------------------------- |
| `none`        |           |           | `~/.env` renders empty. Default for `personal` profile.                |
| `bitwarden`   |     ✓     |           | `bw login` + `bw-apply` to unlock. Real machines only.                 |
| `1password`   |           |     ✓     | Default for `work` profile. Service-account flow on ephemeral.         |
| `both`        |     ✓     |     ✓     | On ephemeral boxes only the 1Password half is functional.              |

### First-time setup (real machines)

**1Password** — once per machine: `op signin` (uses system Keychain on macOS for subsequent calls).

**Bitwarden** — once per machine: `bw login`. Then use `bw-apply` instead of bare `chezmoi apply` whenever `~/.env` may need re-rendering. `bw-apply` (defined in `~/.config/shell/functions.zsh.tmpl`) unlocks Bitwarden, sets `BW_SESSION`, and runs `chezmoi apply`. It's a no-op for the unlock step on machines whose `.secrets` doesn't include `bitwarden`.

### Ephemeral 1Password (service account)

On a cloud VM, set `OP_SERVICE_ACCOUNT_TOKEN` in the environment before bootstrap (or pass `--op-token <token>`). Bootstrap stores it at `~/.config/op/token` (chmod 600), and `.zshenv` sources it on every shell. No `op signin` required.

### Adding a secret

1. Find the item name in your vault
2. Edit the template: `chezmoi edit ~/.env`
3. Add the appropriate expression:

```sh
# Bitwarden — password field
export GITHUB_TOKEN="{{ (bitwarden "item" "GitHub PAT").login.password }}"

# Bitwarden — custom field
export SOME_KEY="{{ (bitwardenFields "item" "Item Name").field_name.value }}"

# 1Password (wrap in {{ if eq .profile "work" }} block)
export AWS_KEY="{{ onepasswordRead "op://Work Vault/AWS/access_key_id" }}"
```

4. Run `bw-apply` to re-render `~/.env`

### Session management

`BW_SESSION` is set in memory only — it doesn't persist across reboots. On a fresh terminal after a restart, run `bw-apply` once to re-unlock. Use `bw-lock` to explicitly clear the session.

### On the bootstrap chicken-and-egg

`~/.env` template references to `{{ bitwarden ... }}` / `{{ onepasswordRead ... }}` need the `bw`/`op` CLI present at template *render* time, not after. Bootstrap pre-installs the relevant CLIs (apt-repo for `op` on Linux, brew on macOS, direct download for `bw` on Linux) before calling `chezmoi init --apply`. Service-account / interactive auth happens in the same step, so the first apply renders `~/.env` correctly without a second pass.

---

## Repository structure

```
dotfiles/
├── .chezmoiroot                  # tells chezmoi: source root is home/
│
├── home/                         # chezmoi source root — mirrors $HOME
│   ├── .chezmoi.toml.tmpl        # prompts + rerun-comment header
│   ├── .chezmoidata/
│   │   └── palette.toml          # shared color palette → all themes
│   ├── .chezmoiexternal.toml     # Oh My ZSH + plugins as tracked git repos
│   ├── dot_zshenv.tmpl
│   ├── dot_zprofile.tmpl
│   ├── dot_zshrc.tmpl
│   ├── dot_gitconfig.tmpl
│   ├── dot_gitignore_global
│   ├── dot_config/shell/         # → ~/.config/shell/
│   ├── dot_config/dotfiles/
│   │   ├── Brewfile.tmpl         # unified, axis-gated Brewfile
│   │   └── lib/gum.sh.tmpl       # palette-driven Gum env vars
│   ├── dot_config/ghostty/       # Ghostty config + theme
│   ├── dot_warp/                 # Warp themes/keybindings/workflows
│   ├── dot_local/bin/
│   │   ├── executable_dotfiles            # `dotfiles update|doctor|palette-import`
│   │   ├── executable_dotfiles-doctor.tmpl  # health check
│   │   └── executable_update-packages
│   ├── private_dot_env.tmpl      # ~/.env (gated on .secrets)
│   ├── run_once_01-install-bootstrap-prereqs
│   ├── run_once_02-install-uv
│   ├── run_once_03-setup-python-venv
│   ├── run_once_05-macos-defaults
│   ├── run_once_06-touchid-sudo
│   ├── run_once_07-set-default-shell
│   └── run_after_install-packages.sh.tmpl  # always-run brew bundle check
│
├── os/                           # native package lists (pre-Homebrew prereqs only)
│   ├── linux/bootstrap.apt
│   ├── linux/bootstrap.dnf
│   ├── raspberry-pi/packages.apt
│   └── windows/packages.choco
│
├── bootstrap/
│   ├── install.sh                # curl | sh entry point (macOS/Linux)
│   ├── install.ps1               # PowerShell entry point (Windows)
│   └── lib/                      # detect, preflight, gum-bootstrap, secrets
│
└── docs/superpowers/             # design specs and implementation plans
```

---

## Common commands

```sh
dotfiles update             # chezmoi update + update-packages --force
dotfiles doctor             # health check
chezmoi apply               # apply any pending changes from the source
chezmoi diff                # preview what would change
chezmoi edit ~/.zshrc       # edit a managed file in your editor
chezmoi edit-config         # change profile, name, email, machine role, display, secrets
chezmoi status              # show which files differ from source
czcd                        # cd to the chezmoi source directory
bw-apply                    # unlock Bitwarden + chezmoi apply (no-op for non-Bitwarden machines)
```

---

## Adding a new machine

1. Run the bootstrap script above (Gum prompts you for what can't be auto-detected).
2. All `run_once_` scripts execute in order: Homebrew → bootstrap prereqs → uv → Python venv → (macOS defaults) → (Touch ID) → set default shell.
3. The always-run `run_after_install-packages.sh.tmpl` runs `brew bundle check` against the rendered Brewfile and installs anything missing.
4. `exec zsh` to pick up the new shell config.
5. `dotfiles doctor` to verify everything is healthy.

To reproduce a machine's exact setup elsewhere, copy the rerun-comment header from `~/.config/chezmoi/chezmoi.toml` — it contains the equivalent non-interactive bootstrap command for the current machine.

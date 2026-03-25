# dotfiles

Personal dotfiles managed with [chezmoi](https://www.chezmoi.io/). Supports macOS, Ubuntu, Fedora, Raspberry Pi (Raspbian/Ubuntu), and Windows (Cygwin).

## Quick start

### macOS / Linux / Raspberry Pi

```sh
sh -c "$(curl -fsSL https://raw.githubusercontent.com/nickvigilante/dotfiles/main/bootstrap/install.sh)"
```

### Windows (elevated PowerShell)

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\bootstrap\install.ps1
```

Both scripts install chezmoi (if needed), clone this repo, and run `chezmoi init --apply`. You'll be prompted once for:

| Prompt        | Options                                |
| ------------- | -------------------------------------- |
| Profile       | `work` or `personal`                   |
| Full name     | used in git config                     |
| Email address | used in git config                     |
| Machine role  | `laptop`, `desktop`, `server`, or `pi` |

Answers are saved to `~/.config/chezmoi/chezmoi.toml` and never re-prompted. To change them later: `chezmoi edit-config`.

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

Packages are declared in `os/` and installed/synced by chezmoi run scripts:

| Platform        | Package manager      | File                           |
| --------------- | -------------------- | ------------------------------ |
| macOS           | Homebrew Bundle      | `os/macos/Brewfile`            |
| Linux laptops   | Homebrew (CLI tools) | `os/linux/Brewfile.linux`      |
| Ubuntu / Debian | apt                  | `os/linux/packages.apt`        |
| Fedora          | dnf                  | `os/linux/packages.dnf`        |
| Raspberry Pi    | apt                  | `os/raspberry-pi/packages.apt` |
| Windows         | Chocolatey           | `os/windows/packages.choco`    |

**Adding a package:** edit the relevant file and run `chezmoi apply`. The `run_onchange_install-packages` script detects the change via file hash and re-syncs automatically.

### Automatic update prompts

A script at `~/.local/bin/update-packages` runs in the background on every new shell. It's throttled to once per 24 hours using a timestamp at `~/.cache/dotfiles/last_update`. When it fires, it runs the appropriate package managers for the current platform (Homebrew, apt, dnf, snap, Chocolatey) and upgrades chezmoi itself.

Run manually at any time:

```sh
update-packages          # respects the 24h throttle
update-packages --force  # bypass the throttle
```

### macOS-specific

- **Touch ID for sudo** — enabled via `/etc/pam.d/sudo_local` (survives macOS system updates, unlike `/etc/pam.d/sudo`). Configured automatically on first `chezmoi apply`.
- **System defaults** — Finder (show extensions, path bar, list view), Dock (auto-hide, no recent apps), keyboard (fast repeat, no autocorrect), screenshots saved to `~/Desktop/Screenshots`.

---

## Profiles

The `work` and `personal` profiles affect:

- **Git email** — different address per profile
- **Shell config** — `work.zsh` or `personal.zsh` is sourced
- **Packages** — profile-specific packages can be declared in separate Brewfiles (`os/macos/Brewfile.work`)
- **Oh My ZSH plugins** — e.g. `aws` plugin enabled for work profile
- **Exports** — profile-specific environment variables in `exports.zsh`

To switch profiles on an existing machine, edit `~/.config/chezmoi/chezmoi.toml` and run `chezmoi apply`.

---

## Secrets and environment variables

`~/.env` (chmod 600) is generated by chezmoi from `home/private_dot_env.tmpl` and sourced by `.zshenv` on every shell start. The template pulls values from your password managers at apply time — plaintext secrets are never stored in this repo.

### Two password managers, one template

| Scope | Manager | Machine | CLI |
|---|---|---|---|
| Personal secrets | Bitwarden | All machines | `bw` |
| Work secrets | 1Password | Work machine only | `op` |

The template gates 1Password calls behind `{{ if eq .profile "work" }}`, so they only render on the work machine. Raspberry Pi machines get neither (no vault CLI installed there).

### First-time setup

**1. Log in to Bitwarden** (once per machine, stores credentials locally):
```sh
bw login
```

**2. Apply dotfiles with secrets** (use `bw-apply` instead of bare `chezmoi apply`):
```sh
bw-apply
```

`bw-apply` (defined in `~/.config/shell/functions.zsh`) unlocks Bitwarden, sets `BW_SESSION`, and runs `chezmoi apply`. On subsequent runs it reuses the session if already unlocked.

**3. Work machine only — sign in to 1Password** (once, uses system keychain after):
```sh
op signin
```

Then run `bw-apply` again. With both CLIs authenticated, chezmoi renders the full template.

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

The first `chezmoi init --apply` during bootstrap runs before `bw` is installed. The bootstrap script handles this with a two-pass approach: structure and packages first, secrets on the second pass after `bw login && bw-apply`.

---

## Repository structure

```
dotfiles/
├── .chezmoiroot                  # tells chezmoi: source root is home/
│
├── home/                         # chezmoi source root — mirrors $HOME
│   ├── .chezmoi.toml.tmpl        # bootstrap: prompts for machine config once
│   ├── .chezmoiexternal.toml     # Oh My ZSH + plugins as tracked git repos
│   ├── dot_zshenv.tmpl           # → ~/.zshenv
│   ├── dot_zprofile.tmpl         # → ~/.zprofile
│   ├── dot_zshrc.tmpl            # → ~/.zshrc
│   ├── dot_gitconfig.tmpl        # → ~/.gitconfig
│   ├── dot_gitignore_global      # → ~/.gitignore_global
│   ├── dot_config/shell/         # → ~/.config/shell/ (sourced by .zshrc)
│   ├── dot_local/bin/
│   │   └── executable_update-packages  # → ~/.local/bin/update-packages
│   ├── run_once_00-install-homebrew
│   ├── run_once_02-install-uv
│   ├── run_once_03-setup-python-venv
│   ├── run_once_04-install-packages
│   ├── run_once_05-macos-defaults
│   ├── run_once_06-touchid-sudo
│   └── run_onchange_install-packages
│
├── os/                           # package lists (referenced by run scripts)
│   ├── macos/Brewfile
│   ├── linux/{Brewfile.linux,packages.apt,packages.dnf}
│   ├── raspberry-pi/packages.apt
│   └── windows/packages.choco
│
└── bootstrap/
    ├── install.sh                # curl | sh entry point (macOS/Linux/Pi)
    └── install.ps1               # PowerShell entry point (Windows)
```

---

## Common commands

```sh
chezmoi apply               # apply any pending changes from the source
chezmoi update              # pull latest from git and apply
chezmoi diff                # preview what would change
chezmoi edit ~/.zshrc       # edit a managed file in your editor
chezmoi edit-config         # change profile, name, email, machine role
chezmoi status              # show which files differ from source
czcd                        # cd to the chezmoi source directory
```

---

## Adding a new machine

1. Run the bootstrap script above.
2. Answer the profile prompts.
3. All `run_once_` scripts execute in order: Homebrew → uv → Python venv → packages → (macOS defaults) → (Touch ID).
4. Restart your shell: `exec zsh`.

#!/usr/bin/env bash
# Bootstrap dotfiles on macOS, Linux, or Windows (Cygwin).
#
# Usage on a fresh machine:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/nickvigilante/dotfiles/main/bootstrap/install.sh)"
#
# Or with flags (non-interactive):
#   bash -c "$(curl -fsSL .../install.sh)" -- \
#     --profile work --machine ephemeral --secrets 1password \
#     --no-display --non-interactive

if [ -z "${BASH_VERSION:-}" ]; then
    printf 'Error: this installer requires bash. Re-run with:\n  bash -c "$(curl -fsSL %s)"\n' \
        "https://raw.githubusercontent.com/nickvigilante/dotfiles/main/bootstrap/install.sh" >&2
    exit 1
fi

set -euo pipefail

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
BOLD=$'\033[1m'; CYAN=$'\033[0;36m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; RESET=$'\033[0m'
header() { printf "\n%s%s%s\n" "$BOLD" "$*" "$RESET"; }
info()   { printf "%s  →%s %s\n" "$CYAN" "$RESET" "$*"; }
ok()     { printf "%s  ✓%s %s\n" "$GREEN" "$RESET" "$*"; }
warn()   { printf "%s  !%s %s\n" "$YELLOW" "$RESET" "$*" >&2; }
err()    { printf "%s  ✗%s %s\n" "$RED" "$RESET" "$*" >&2; }

# ── Locate scripts (works whether run via curl|sh or from clone) ────────────
# Under `bash -c "..."`, $0 == "--" or "bash" and BASH_SOURCE[0] is empty;
# force a path operand so `dirname --` doesn't trigger GNU's end-of-options.
SCRIPT_DIR="$(cd "$(dirname -- "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
if [[ -z "$SCRIPT_DIR" ]] || [[ ! -d "$SCRIPT_DIR/lib" ]]; then
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
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/bw-ssh-agent.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/touch-id-sudo.sh"

# ── 1. Detect ─────────────────────────────────────────────────────────────────
header "Step 1/10 — Detect platform"
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
header "Step 2/10 — Preflight checks"
preflight_all || { err "Preflight failed."; exit 1; }

# ── 3. Bootstrap-only essentials ─────────────────────────────────────────────
header "Step 3/10 — Install bootstrap essentials"
case "$DETECTED_OS" in
    linux)
        if [[ "$DETECTED_IS_PI" == 0 ]]; then
            info "Confirming sudo authentication (fingerprint, Touch ID, or password)..."
            sudo -v
            ok "Sudo authenticated."
            if command -v apt-get &>/dev/null; then
                info "Installing apt prereqs..."
                sudo apt-get update -qq
                sudo apt-get install -y curl git zsh ca-certificates build-essential file procps gnupg lsb-release
            elif command -v dnf &>/dev/null; then
                info "Installing dnf prereqs..."
                sudo dnf install -y curl git zsh ca-certificates @development-tools file procps-ng gnupg2
            fi

            # snapd: required for Bitwarden CLI (snap install bw) on Linux,
            # baseline-installed on every non-Pi Linux machine regardless of
            # --secrets choice so future snap-based tools just work.
            if ! command -v snap &>/dev/null; then
                info "Installing snapd..."
                if command -v apt-get &>/dev/null; then
                    sudo apt-get install -y snapd
                elif command -v dnf &>/dev/null; then
                    sudo dnf install -y snapd
                    # Fedora ships snapd but no /snap symlink; classically-
                    # confined snaps need it. Bitwarden's snap is strict, but
                    # creating the symlink keeps other snaps working too.
                    [[ -e /snap ]] || sudo ln -sf /var/lib/snapd/snap /snap
                else
                    warn "snapd installer not implemented for this distro."
                    warn "  Bitwarden CLI installs from snap; --secrets bitwarden will fail in step 7."
                fi
                if command -v systemctl &>/dev/null && command -v snap &>/dev/null; then
                    sudo systemctl enable --now snapd.socket
                    # Without this wait, the next 'snap install' can fail with
                    # "too early for operation" on a freshly-enabled snapd.
                    sudo snap wait system seed.loaded
                    ok "snapd installed."
                fi
            fi
            # /snap/bin holds symlinks to snap-installed apps. On Fedora and
            # similar, it isn't on $PATH until next login — prepend it now so
            # 'command -v bw' works in step 7 of this same run.
            case ":${PATH}:" in
                *:/snap/bin:*) : ;;
                *) export PATH="/snap/bin:$PATH" ;;
            esac
        fi
        ;;
    darwin)
        :
        ;;
esac
ok "Bootstrap essentials in place."

# ── 4. Download Gum ──────────────────────────────────────────────────────────
header "Step 4/10 — Download Gum"
if command -v gum &>/dev/null; then
    GUM_BIN="$(command -v gum)"
else
    gum_install_temp || { err "Gum download failed."; exit 1; }
    export PATH="$HOME/.local/bin:$PATH"
    GUM_BIN="$HOME/.local/bin/gum.tmp"
fi
[[ -x "$GUM_BIN" ]] || { err "Gum binary not executable: $GUM_BIN"; exit 1; }
ok "Gum ready: $GUM_BIN"

# When piped via `curl | bash`, stdin is the pipe rather than the terminal.
# Redirect to /dev/tty so Gum can render its interactive TUI.
if [[ "$FLAG_NON_INTERACTIVE" == 0 ]] && [[ ! -t 0 ]]; then
    exec < /dev/tty
fi

# ── 5. Prompt for unset values ───────────────────────────────────────────────
header "Step 5/10 — Configure (Gum prompts for what wasn't set)"

prompt_required() {
    local var="$1" question="$2" choices="$3"
    if [[ -z "${!var}" ]]; then
        if [[ "$FLAG_NON_INTERACTIVE" == 1 ]]; then
            err "Required: $var (use the matching CLI flag or DOTFILES_* env var)"; exit 1
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
if [[ -z "$FLAG_SECRETS" ]]; then
    [[ "$FLAG_PROFILE" == "work" ]] && FLAG_SECRETS="1password" || FLAG_SECRETS="none"
    if [[ "$FLAG_NON_INTERACTIVE" == 0 ]]; then
        FLAG_SECRETS="$("$GUM_BIN" choose --header "Secret managers" \
            --selected="$FLAG_SECRETS" \
            none bitwarden 1password both)"
    fi
fi

ok "Profile=$FLAG_PROFILE, machine=$FLAG_MACHINE, display=$FLAG_DISPLAY, secrets=$FLAG_SECRETS"

# ── 6. Install Homebrew ─────────────────────────────────────────────────────
# Lifted from home/run_once_00-install-homebrew.sh.tmpl so brew is available
# for the secret-CLI installs in step 7 (1Password on Linux + macOS bw/op).
# Skipped on Pi and on any Linux arch other than amd64/arm64.
header "Step 6/10 — Install Homebrew"
brew_supported=0
case "$DETECTED_OS" in
    darwin) brew_supported=1 ;;
    linux)
        if [[ "$DETECTED_IS_PI" == 0 ]]; then
            case "$DETECTED_ARCH" in
                amd64|arm64) brew_supported=1 ;;
            esac
        fi
        ;;
esac

if [[ "$brew_supported" == 1 ]]; then
    # Resolve brew binary path: macOS arm64 → /opt/homebrew, macOS x86_64 →
    # /usr/local, Linux → /home/linuxbrew/.linuxbrew. `command -v brew` may
    # miss it on a fresh non-login shell where the shellenv hasn't run yet.
    BREW_BIN=""
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
        [[ -x "$candidate" ]] && { BREW_BIN="$candidate"; break; }
    done
    if [[ -z "$BREW_BIN" ]]; then
        info "Installing Homebrew (non-interactive)..."
        NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
            [[ -x "$candidate" ]] && { BREW_BIN="$candidate"; break; }
        done
    fi
    if [[ -z "$BREW_BIN" ]]; then
        err "Homebrew install completed but brew not found in any standard location."
        exit 1
    fi
    eval "$("$BREW_BIN" shellenv)"
    ok "Homebrew available: $(brew --version | head -1)"
else
    info "Skipping Homebrew (unsupported on $DETECTED_OS/$DETECTED_ARCH; pi=$DETECTED_IS_PI)."
fi

install_touch_id

# ── 7. Pre-install secret CLIs ──────────────────────────────────────────────
header "Step 7/10 — Install secret CLIs (if needed)"
case "$FLAG_SECRETS" in
    bitwarden|both)
        if [[ "$DETECTED_EPHEMERAL" == 1 ]] && [[ "$FLAG_NON_INTERACTIVE" == 1 ]]; then
            err "Bitwarden on ephemeral non-interactive is unsupported (needs master password)."
            err "Use --secrets none or 1password instead."
            exit 1
        fi
        if ! command -v bw &>/dev/null; then
            if ! retry_or_skip "Bitwarden CLI install" install_bw; then
                warn "Skipping Bitwarden for this run."
                FLAG_SECRETS="${FLAG_SECRETS/bitwarden/none}"
                FLAG_SECRETS="${FLAG_SECRETS/both/1password}"
            fi
        fi
        ;;
esac
case "$FLAG_SECRETS" in
    1password|both)
        if ! retry_or_skip "1Password CLI install" install_op; then
            warn "Skipping 1Password for this run."
            FLAG_SECRETS="${FLAG_SECRETS/1password/none}"
            FLAG_SECRETS="${FLAG_SECRETS/both/bitwarden}"
        elif [[ -n "$FLAG_OP_TOKEN" ]]; then
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

# Capture `bw unlock --raw` output into the global BW_SESSION so retry_or_skip
# can treat empty output (or non-zero exit) uniformly as failure. bw prompts
# for the master password on /dev/tty directly, so no fd plumbing is needed.
_bw_unlock_capture() {
    local session
    session="$(bw unlock --raw)" || return 1
    [[ -n "$session" ]] || return 1
    BW_SESSION="$session"
    export BW_SESSION
}

case "$FLAG_SECRETS" in
    bitwarden|both)
        if [[ "$FLAG_NON_INTERACTIVE" == 0 ]]; then
            bw_status_json="$(bw status 2>/dev/null || true)"
            bw_skipped=0
            case "$bw_status_json" in
                *'"status":"unauthenticated"'*|"")
                    retry_or_skip "Bitwarden login" bw login || bw_skipped=1
                    ;;
                *)
                    info "Bitwarden session already authenticated; unlocking..."
                    ;;
            esac
            if [[ "$bw_skipped" == 0 ]]; then
                if retry_or_skip "Bitwarden unlock" _bw_unlock_capture; then
                    ok "Bitwarden unlocked."
                    setup_bw_ssh_agent || warn "SSH key setup did not complete."
                else
                    bw_skipped=1
                fi
            fi
            if [[ "$bw_skipped" == 1 ]]; then
                warn "Skipping Bitwarden; chezmoi will not pull Bitwarden secrets this run."
                unset BW_SESSION
            fi
        fi
        ;;
esac

# ── 8. Install chezmoi ──────────────────────────────────────────────────────
header "Step 8/10 — Install chezmoi"
if ! command -v chezmoi &>/dev/null; then
    info "Installing chezmoi..."
    sh -c "$(curl -fsSL https://get.chezmoi.io)" -- -b "$HOME/.local/bin"
fi
export PATH="$HOME/.local/bin:$PATH"
ok "chezmoi installed: $(chezmoi --version | head -1)"

# ── 9. chezmoi init --apply ─────────────────────────────────────────────────
header "Step 9/10 — Apply dotfiles"

display_bool="false"
[[ "$FLAG_DISPLAY" == 1 ]] && display_bool="true"

chezmoi init --apply \
    --promptChoice "Profile=$FLAG_PROFILE" \
    --promptString "Full name=$FLAG_NAME" \
    --promptString "Email address=$FLAG_EMAIL" \
    --promptChoice "Machine role=$FLAG_MACHINE" \
    --promptBool   "Has graphical display=$display_bool" \
    --promptChoice "Secret managers=$FLAG_SECRETS" \
    "$DOTFILES_REPO"

# ── 10. Set up dotfiles working copy (optional) ─────────────────────────────
header "Step 10/10 — Set up dotfiles working copy"
REPO_SLUG=$(printf '%s' "$DOTFILES_REPO" | sed -E 's|.*github\.com/||; s|\.git$||')
WORKING_COPY="$HOME/git/$REPO_SLUG"
if [[ "$FLAG_NON_INTERACTIVE" == 1 ]]; then
    info "Skipping working copy setup (non-interactive)"
elif "$GUM_BIN" confirm --default=false "Clone dotfiles to $WORKING_COPY and use as chezmoi source?"; then
    mkdir -p "$WORKING_COPY"
    if [[ ! -d "$WORKING_COPY/.git" ]]; then
        git clone "$DOTFILES_REPO" "$WORKING_COPY"
    fi
    CHEZMOI_CONFIG="$HOME/.config/chezmoi/chezmoi.toml"
    SOURCE_DIR="$WORKING_COPY/home"
    if ! grep -q '^\[chezmoi\]' "$CHEZMOI_CONFIG" 2>/dev/null; then
        { printf '[chezmoi]\nsourceDir = "%s"\n\n' "$SOURCE_DIR"; cat "$CHEZMOI_CONFIG"; } \
            > "${CHEZMOI_CONFIG}.tmp" && mv "${CHEZMOI_CONFIG}.tmp" "$CHEZMOI_CONFIG"
    else
        warn "chezmoi.toml already has a [chezmoi] section; set sourceDir manually to $SOURCE_DIR"
    fi
    ok "Working copy: $WORKING_COPY"
    ok "chezmoi source: $SOURCE_DIR"
fi

# ── Cleanup ─────────────────────────────────────────────────────────────────
gum_cleanup_temp 2>/dev/null || true

ok "Bootstrap complete!"
echo ""
echo "Next steps:"
echo "  exec zsh                   # restart your shell"
echo "  dotfiles doctor            # health check (after PR C lands)"
echo "  chezmoi status             # show pending changes"

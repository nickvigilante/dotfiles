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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
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
                sudo apt-get install -y curl git zsh ca-certificates build-essential file procps gnupg lsb-release
            elif command -v dnf &>/dev/null; then
                info "Installing dnf prereqs..."
                sudo dnf install -y curl git zsh ca-certificates @development-tools file procps-ng gnupg2
            fi
        fi
        ;;
    darwin)
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
            install_bw
        fi
        ;;
esac
case "$FLAG_SECRETS" in
    1password|both)
        install_op
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
            bw_status_json="$(bw status 2>/dev/null || true)"
            case "$bw_status_json" in
                *'"status":"unauthenticated"'*|"")
                    info "Logging in to Bitwarden..."
                    bw login
                    ;;
                *)
                    info "Bitwarden session already authenticated; unlocking..."
                    ;;
            esac
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

# home/.chezmoi.toml.tmpl pins sourceDir to ~/git/nickvigilante/dotfiles/home,
# so chezmoi reads templates from there on every apply. Make sure that path
# exists and is fresh BEFORE chezmoi init --apply, otherwise the apply phase
# reads from a stale (or missing) clone and re-runs deleted scripts.
DEV_CLONE="$HOME/git/nickvigilante/dotfiles"
if [[ ! -d "$DEV_CLONE/.git" ]]; then
    info "Cloning dotfiles repo to $DEV_CLONE..."
    mkdir -p "$(dirname "$DEV_CLONE")"
    git clone "$DOTFILES_REPO" "$DEV_CLONE"
else
    info "Updating dev clone at $DEV_CLONE..."
    git -C "$DEV_CLONE" fetch origin --quiet
    if git -C "$DEV_CLONE" merge --ff-only origin/main 2>/dev/null; then
        ok "Dev clone fast-forwarded to origin/main."
    else
        warn "Could not fast-forward $DEV_CLONE (uncommitted changes or diverged history); leaving as-is."
        warn "If bootstrap fails next, manually resolve $DEV_CLONE and re-run."
    fi
fi

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

# ── Cleanup ─────────────────────────────────────────────────────────────────
gum_cleanup_temp 2>/dev/null || true

ok "Bootstrap complete!"
echo ""
echo "Next steps:"
echo "  exec zsh                   # restart your shell"
echo "  dotfiles doctor            # health check (after PR C lands)"
echo "  chezmoi status             # show pending changes"

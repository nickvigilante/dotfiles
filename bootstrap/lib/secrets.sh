#!/usr/bin/env bash
# Secret-CLI installation helpers. Sourced by bootstrap/install.sh.
#
# Both helpers assume install.sh's earlier steps have provided:
#   - Step 3/9: snapd on Linux (non-Pi) — used by install_bw
#   - Step 6/9: Homebrew on Linux (non-Pi) + macOS — used by install_op
#                (and by install_bw on macOS only)
#
# Requires DETECTED_OS, DETECTED_ARCH, DETECTED_IS_PI from detect.sh.
# Requires GUM_BIN from install.sh for retry_or_skip prompts.

set -euo pipefail

# ── retry_or_skip ───────────────────────────────────────────────────────────
# Run a command and, on any failure, prompt: retry / skip / exit.
# Returns 0 on eventual success, 1 on user-requested skip; calls `exit 1` on
# user-requested exit. No error-message inspection — handles all failures the
# same way (wrong 2FA, transient network, brew error, etc.).
#
# Usage: retry_or_skip "Bitwarden login" bw login
retry_or_skip() {
    local label="$1"; shift
    while true; do
        if "$@"; then
            return 0
        fi
        printf "%s  !%s %s failed.\n" "${YELLOW:-}" "${RESET:-}" "$label" >&2
        local choice
        choice="$("$GUM_BIN" choose --header "$label — what now?" "retry" "skip" "exit")"
        case "$choice" in
            retry)  continue ;;
            skip)   return 1 ;;
            exit|*) printf "%s  ✗%s Aborted by user.\n" "${RED:-}" "${RESET:-}" >&2; exit 1 ;;
        esac
    done
}

# ── 1Password CLI install ───────────────────────────────────────────────────
install_op() {
    if command -v op &>/dev/null; then
        echo "✓ 1Password CLI already installed: $(op --version)"
        return 0
    fi
    case "$DETECTED_OS" in
        darwin)
            if ! command -v brew &>/dev/null; then
                echo "ERROR: Homebrew required for 1Password CLI on macOS." >&2
                return 1
            fi
            echo "Installing 1Password CLI via brew..."
            brew install --cask 1password-cli
            ;;
        linux)
            if [[ "${DETECTED_IS_PI:-0}" == 1 ]]; then
                echo "ERROR: 1Password CLI unsupported on 32-bit ARM (no Linuxbrew)." >&2
                echo "  Use --secrets none or --secrets bitwarden." >&2
                return 1
            fi
            if ! command -v brew &>/dev/null; then
                echo "ERROR: Homebrew required for 1Password CLI on Linux but brew is not on PATH." >&2
                echo "  install.sh Step 6/9 should have installed it; check that step's output." >&2
                return 1
            fi
            echo "Installing 1Password CLI via brew..."
            brew install 1password-cli
            ;;
        *)
            echo "WARN: 1Password CLI auto-install not supported on $DETECTED_OS." >&2
            return 1
            ;;
    esac
}

# ── Bitwarden CLI install ───────────────────────────────────────────────────
install_bw() {
    if command -v bw &>/dev/null; then
        existing_bw="$(command -v bw)"
        # Earlier versions of this bootstrap did a direct-zip install of
        # Bitwarden CLI to ~/.local/bin/bw. The pinned version is now too
        # stale for Bitwarden's server, which rejects logins with
        # "Please update your app". Remove the legacy binary so the snap
        # install path below takes over.
        if [[ "$DETECTED_OS" == "linux" ]] && [[ "$existing_bw" == "$HOME/.local/bin/bw" ]]; then
            echo "Removing legacy Bitwarden CLI at $existing_bw (snap will replace it)..."
            rm -f "$existing_bw"
        else
            echo "✓ Bitwarden CLI already installed: $(bw --version)"
            return 0
        fi
    fi
    case "$DETECTED_OS" in
        darwin)
            if ! command -v brew &>/dev/null; then
                echo "ERROR: Homebrew required for Bitwarden CLI on macOS." >&2
                return 1
            fi
            brew install bitwarden-cli
            ;;
        linux)
            if [[ "${DETECTED_IS_PI:-0}" == 1 ]]; then
                echo "ERROR: Bitwarden CLI unsupported on 32-bit ARM (no snap or Linuxbrew)." >&2
                echo "  Use --secrets none or --secrets 1password." >&2
                return 1
            fi
            if ! command -v snap &>/dev/null; then
                echo "ERROR: snapd required for Bitwarden CLI on Linux but snap is not on PATH." >&2
                echo "  install.sh Step 3/9 should have installed it; check that step's output." >&2
                return 1
            fi
            echo "Installing Bitwarden CLI via snap..."
            sudo snap install bw
            ;;
        *)
            echo "WARN: Bitwarden CLI auto-install not supported on $DETECTED_OS." >&2
            return 1
            ;;
    esac
}

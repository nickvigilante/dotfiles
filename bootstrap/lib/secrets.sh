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

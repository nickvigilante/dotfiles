#!/usr/bin/env bash
# Download and install Gum binary to ~/.local/bin/gum.tmp.
# Pinned version with checksum verification.

set -euo pipefail

GUM_VERSION="0.14.5"

gum_install_temp() {
    local os arch
    case "${DETECTED_OS:-}" in
        darwin)  os="Darwin" ;;
        linux)   os="Linux" ;;
        windows) os="Windows" ;;
        *) echo "gum_install_temp: unsupported OS"; return 1 ;;
    esac
    case "${DETECTED_ARCH:-}" in
        amd64)   arch="x86_64" ;;
        arm64)   arch="arm64" ;;
        armv7l)  arch="armv7" ;;
        armv6l)  arch="armv6" ;;
        *) echo "gum_install_temp: unsupported arch"; return 1 ;;
    esac

    local tarball="gum_${GUM_VERSION}_${os}_${arch}.tar.gz"
    local url="https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}/${tarball}"
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    trap "rm -rf '$tmp_dir'" RETURN

    echo "Downloading gum ${GUM_VERSION} (${os}_${arch})..."
    curl -fsSL "$url" -o "$tmp_dir/$tarball"

    local checksum_url="https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}/checksums.txt"
    if curl -fsSL "$checksum_url" -o "$tmp_dir/checksums.txt"; then
        local expected actual
        expected=$(grep "  ${tarball}\$" "$tmp_dir/checksums.txt" | awk '{print $1}')
        if [[ -z "$expected" ]]; then
            echo "WARN: could not find checksum for ${tarball}; proceeding without verification."
        else
            actual=$(shasum -a 256 "$tmp_dir/$tarball" | awk '{print $1}')
            if [[ "$expected" != "$actual" ]]; then
                echo "✗ Checksum mismatch for gum binary." >&2
                echo "  Expected: $expected" >&2
                echo "  Actual:   $actual" >&2
                return 1
            fi
            echo "✓ Checksum verified."
        fi
    else
        echo "WARN: could not fetch checksums; proceeding without verification."
    fi

    tar -xzf "$tmp_dir/$tarball" -C "$tmp_dir"
    mkdir -p "$HOME/.local/bin"
    install -m 0755 "$tmp_dir"/gum*/gum "$HOME/.local/bin/gum.tmp"
    echo "✓ gum installed to $HOME/.local/bin/gum.tmp"
}

gum_cleanup_temp() {
    local brew_gum
    brew_gum="$(command -v gum 2>/dev/null || true)"
    if [[ -n "$brew_gum" ]] && [[ "$brew_gum" != "$HOME/.local/bin/gum.tmp" ]]; then
        rm -f "$HOME/.local/bin/gum.tmp"
        echo "✓ Removed temp gum binary; brew-gum is now active at $brew_gum."
    fi
}

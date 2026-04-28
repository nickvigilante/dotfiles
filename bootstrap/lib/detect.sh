#!/usr/bin/env bash
# Pure-shell platform detection. Exports DETECTED_* env vars on success.
# Sourced by bootstrap/install.sh.

set -euo pipefail

detect_all() {
    detect_os
    detect_arch
    detect_distro
    detect_wsl
    detect_ephemeral
    detect_display
    detect_pi
}

detect_os() {
    case "$(uname -s)" in
        Darwin)              DETECTED_OS="darwin" ;;
        Linux)               DETECTED_OS="linux" ;;
        CYGWIN*|MINGW*|MSYS*) DETECTED_OS="windows" ;;
        *) echo "Unsupported OS: $(uname -s)"; exit 1 ;;
    esac
    export DETECTED_OS
}

detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64)            DETECTED_ARCH="amd64" ;;
        aarch64|arm64)           DETECTED_ARCH="arm64" ;;
        armv7l|armv7)            DETECTED_ARCH="armv7l" ;;
        armv6l|armv6)            DETECTED_ARCH="armv6l" ;;
        *)                       DETECTED_ARCH="$(uname -m)" ;;
    esac
    export DETECTED_ARCH
}

detect_distro() {
    DETECTED_DISTRO=""
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        DETECTED_DISTRO="$(. /etc/os-release && echo "${ID:-}")"
    fi
    export DETECTED_DISTRO
}

detect_wsl() {
    DETECTED_WSL=0
    if [[ "$DETECTED_OS" == "linux" ]]; then
        if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
            DETECTED_WSL=1
        elif grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
            DETECTED_WSL=1
        fi
    fi
    export DETECTED_WSL
}

detect_ephemeral() {
    DETECTED_EPHEMERAL=0
    if [[ -f /.dockerenv ]] || [[ -n "${CODESPACES:-}" ]] || [[ -n "${AWS_EXECUTION_ENV:-}" ]]; then
        DETECTED_EPHEMERAL=1
    fi
    if [[ "$DETECTED_EPHEMERAL" == 0 ]] && command -v curl &>/dev/null; then
        if curl -fsS -m 0.2 http://169.254.169.254/latest/meta-data/ &>/dev/null; then
            DETECTED_EPHEMERAL=1
        fi
    fi
    if [[ "$DETECTED_EPHEMERAL" == 0 ]] && command -v curl &>/dev/null; then
        if curl -fsS -m 0.2 -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/ &>/dev/null; then
            DETECTED_EPHEMERAL=1
        fi
    fi
    export DETECTED_EPHEMERAL
}

detect_display() {
    case "$DETECTED_OS" in
        darwin|windows) DETECTED_DISPLAY=1 ;;
        linux)
            if [[ "$DETECTED_WSL" == 1 ]]; then
                DETECTED_DISPLAY=0
            elif [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
                DETECTED_DISPLAY=1
            else
                DETECTED_DISPLAY=0
            fi
            ;;
    esac
    export DETECTED_DISPLAY
}

detect_pi() {
    DETECTED_IS_PI=0
    if [[ -f /proc/device-tree/model ]]; then
        if grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
            DETECTED_IS_PI=1
        fi
    fi
    export DETECTED_IS_PI
}

if [[ "${BASH_SOURCE[0]:-}" == "${0}" ]]; then
    detect_all
    echo "OS:        $DETECTED_OS"
    echo "Arch:      $DETECTED_ARCH"
    echo "Distro:    $DETECTED_DISTRO"
    echo "WSL:       $DETECTED_WSL"
    echo "Ephemeral: $DETECTED_EPHEMERAL"
    echo "Display:   $DETECTED_DISPLAY"
    echo "Pi:        $DETECTED_IS_PI"
fi

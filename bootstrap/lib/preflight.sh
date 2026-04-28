#!/usr/bin/env bash
# Preflight checks. Sourced by bootstrap/install.sh.
# Requires DETECTED_* env vars from detect.sh to be set.

set -euo pipefail

preflight_disk_space() {
    local required_gb
    case "${DETECTED_OS:-unknown}/${DETECTED_DISPLAY:-0}" in
        darwin/*)     required_gb=12 ;;
        linux/1)      required_gb=8  ;;
        linux/0)      required_gb=5  ;;
        windows/*)    required_gb=8  ;;
        *)            required_gb=5  ;;
    esac

    local available_gb
    if command -v df &>/dev/null; then
        if df -BG --output=avail "$HOME" &>/dev/null; then
            available_gb=$(df -BG --output=avail "$HOME" | awk 'NR==2 { sub("G",""); print }')
        else
            local kb
            kb=$(df -k "$HOME" | awk 'NR==2 {print $4}')
            available_gb=$((kb / 1024 / 1024))
        fi
    else
        echo "WARN: df not available; skipping disk-space check."
        return 0
    fi

    if (( available_gb < required_gb )); then
        echo "✗ Insufficient disk space."
        echo "  Need at least ${required_gb}G free in $HOME, have ${available_gb}G."
        return 1
    fi
    echo "✓ Disk space OK (${available_gb}G free, ${required_gb}G required)."
}

preflight_network() {
    if ! curl -fsS -m 5 https://github.com >/dev/null 2>&1; then
        echo "✗ No network connectivity to github.com."
        return 1
    fi
    echo "✓ Network OK."
}

preflight_all() {
    preflight_disk_space || return 1
    preflight_network    || return 1
}

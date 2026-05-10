#!/usr/bin/env bash
# Touch ID for sudo on macOS — writes /etc/pam.d/sudo_local.
# sudo_local survives macOS system updates; /etc/pam.d/sudo gets overwritten.
# Sourced by bootstrap/install.sh.
#
# Requires DETECTED_OS from detect.sh.

install_touch_id() {
    [[ "${DETECTED_OS:-}" == "darwin" ]] || return 0

    local sudo_local="/etc/pam.d/sudo_local"

    # Bail if Apple changes PAM structure in a future macOS version.
    if ! grep -q "sudo_local" /etc/pam.d/sudo 2>/dev/null; then
        warn "/etc/pam.d/sudo does not include sudo_local — skipping Touch ID setup."
        warn "  Apple may have changed PAM structure in this macOS version."
        return 0
    fi

    if grep -q "pam_tid" "$sudo_local" 2>/dev/null; then
        ok "Touch ID for sudo already configured."
        return 0
    fi

    info "Enabling Touch ID for sudo..."
    sudo -v
    sudo tee "$sudo_local" > /dev/null <<'EOF'
# sudo_local: local config file which survives system updates.
# Allows Touch ID to authenticate sudo.
auth       sufficient     pam_tid.so
EOF
    ok "Touch ID for sudo enabled. Open a new terminal and run 'sudo ls' to test."
}

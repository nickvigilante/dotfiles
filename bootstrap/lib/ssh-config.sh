#!/usr/bin/env bash
# SSH config.local setup from Bitwarden. Sourced by bootstrap/install.sh.
#
# Fetches the secure note named 'ssh-config-local' from the Bitwarden vault
# and writes it to ~/.ssh/config.local (chmod 600). The tracked ~/.ssh/config
# includes that file, keeping host IPs out of the public dotfiles repo.
#
# Requires:
#   - bw on PATH and BW_SESSION exported (caller has unlocked the vault).
#   - jq on PATH.
#   - GUM_BIN from install.sh for confirm prompts.
#   - info/ok/warn helpers from install.sh.

setup_ssh_config() {
    if [[ -z "${BW_SESSION:-}" ]]; then
        warn "Bitwarden vault not unlocked; skipping SSH config setup."
        return 0
    fi
    for cmd in bw jq; do
        if ! command -v "$cmd" &>/dev/null; then
            warn "$cmd not on PATH; skipping SSH config setup."
            return 0
        fi
    done

    if ! "$GUM_BIN" confirm "Configure SSH hosts from Bitwarden (ssh-config-local)?"; then
        info "Skipping SSH config setup."
        return 0
    fi

    info "Fetching SSH config from Bitwarden..."
    local item_json notes
    item_json="$(bw get item "ssh-config-local" 2>/dev/null)" || item_json=""

    if [[ -z "$item_json" ]]; then
        warn "Bitwarden item 'ssh-config-local' not found; skipping SSH config."
        warn "  Create a secure note named 'ssh-config-local' in Bitwarden with your host entries."
        return 0
    fi

    notes="$(printf '%s' "$item_json" | jq -r '.notes // empty')"
    if [[ -z "$notes" ]]; then
        warn "Bitwarden item 'ssh-config-local' has empty notes; skipping SSH config."
        return 0
    fi

    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"
    printf '%s\n' "$notes" > "$HOME/.ssh/config.local"
    chmod 600 "$HOME/.ssh/config.local"
    ok "SSH hosts written to ~/.ssh/config.local"
}

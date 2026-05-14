#!/usr/bin/env bash
# Bitwarden SSH key creation. Sourced by bootstrap/install.sh.
#
# Generates a fresh ed25519 keypair locally with ssh-keygen, uploads it as a
# Bitwarden vault item of type 5 (SSH key), then deletes the local private key
# on success — the Bitwarden desktop app's SSH agent serves it from the vault.
# On upload failure, both the private and public key files are kept under
# ~/.ssh/bw-<host>{,.pub} so the user isn't left without keys.
#
# The SSH agent itself (the unix socket at ~/.bitwarden-ssh-agent.sock) is
# served by the Bitwarden desktop app — that toggle is in the app's settings
# and cannot be enabled from the CLI. We print a reminder at the end.
#
# Requires:
#   - bw on PATH and BW_SESSION exported (caller has unlocked the vault).
#   - jq, ssh-keygen on PATH.
#   - GUM_BIN from install.sh for confirm prompts.
#   - info/ok/warn/err helpers from install.sh.

setup_bw_ssh_agent() {
    # Hard prerequisites — caller already vetted the secret-manager choice.
    if [[ -z "${BW_SESSION:-}" ]]; then
        warn "Bitwarden vault not unlocked; skipping SSH key setup."
        return 0
    fi
    for cmd in bw jq ssh-keygen; do
        if ! command -v "$cmd" &>/dev/null; then
            warn "$cmd not on PATH; skipping Bitwarden SSH key setup."
            return 0
        fi
    done

    local host key_dir key_name pub_path priv_path bw_item_name
    host="$(hostname -s 2>/dev/null || hostname)"
    key_dir="$HOME/.ssh"
    key_name="bw-${host}"
    priv_path="$key_dir/$key_name"
    pub_path="$key_dir/$key_name.pub"
    bw_item_name="$host - Home Lab"

    # Idempotency: if the .pub already exists, we've done this on this host.
    if [[ -f "$pub_path" ]]; then
        ok "Bitwarden SSH key already set up for this host ($pub_path)."
        return 0
    fi

    if ! "$GUM_BIN" confirm "Create a new SSH key for this machine and store it in Bitwarden?"; then
        info "Skipping Bitwarden SSH key setup."
        return 0
    fi

    mkdir -p "$key_dir"
    chmod 700 "$key_dir"

    # Generate locally — bw CLI cannot generate SSH keys (only the desktop/web
    # apps can), so we make the key with ssh-keygen and upload it as a vault
    # item afterwards. Empty passphrase: the BW agent provides at-rest
    # protection via the vault, and a passphrase would block agent use anyway.
    local tmp_priv tmp_pub
    tmp_priv="$(mktemp "${TMPDIR:-/tmp}/bw-ssh.XXXXXX")"
    tmp_pub="${tmp_priv}.pub"
    rm -f "$tmp_priv"  # ssh-keygen refuses to overwrite

    info "Generating ed25519 keypair..."
    if ! ssh-keygen -t ed25519 -C "$bw_item_name" -f "$tmp_priv" -N "" -q; then
        err "ssh-keygen failed."
        rm -f "$tmp_priv" "$tmp_pub"
        return 1
    fi

    local priv pub fp
    priv="$(<"$tmp_priv")"
    # Drop the trailing comment from the public key — Bitwarden stores
    # algorithm + base64 only, mirroring what its own apps generate.
    pub="$(awk '{print $1" "$2}' "$tmp_pub")"
    fp="$(ssh-keygen -lf "$tmp_pub" | awk '{print $2}')"

    # Build the item JSON. Schema reverse-engineered from a desktop-app-
    # generated item: type=5 with sshKey={privateKey, publicKey, keyFingerprint}.
    local payload
    payload="$(jq -n \
        --arg name "$bw_item_name" \
        --arg priv "$priv" \
        --arg pub "$pub" \
        --arg fp "$fp" \
        '{
            type: 5,
            name: $name,
            notes: null,
            favorite: false,
            reprompt: 0,
            fields: [],
            sshKey: { privateKey: $priv, publicKey: $pub, keyFingerprint: $fp }
        }')"

    info "Uploading SSH key item to Bitwarden as '$bw_item_name'..."
    if printf '%s' "$payload" | bw encode | bw create item >/dev/null; then
        # Upload succeeded — Bitwarden has the only canonical copy. Keep the
        # public key locally for adding to remote authorized_keys files.
        install -m 644 "$tmp_pub" "$pub_path"
        # Best-effort scrub of the local privkey; not all systems have shred.
        if command -v shred &>/dev/null; then
            shred -u "$tmp_priv" 2>/dev/null || rm -f "$tmp_priv"
        else
            rm -f "$tmp_priv"
        fi
        rm -f "$tmp_pub"
        ok "SSH key uploaded to Bitwarden. Public key kept at: $pub_path"
        info "Add this to remote ~/.ssh/authorized_keys:"
        printf '    %s\n' "$(cat "$pub_path")"
        info "To use the key, enable 'SSH agent' in the Bitwarden desktop app's settings."
        info "  (The agent listens on \$HOME/.bitwarden-ssh-agent.sock (or snap/bitwarden/current/... on Linux Snap); .zshenv exports SSH_AUTH_SOCK when present.)"
    else
        # Upload failed — preserve both files at the standard location so the
        # user can retry later with `bw create item` manually, or fall back to
        # plain ssh-agent.
        install -m 600 "$tmp_priv" "$priv_path"
        install -m 644 "$tmp_pub"  "$pub_path"
        rm -f "$tmp_priv" "$tmp_pub"
        warn "Bitwarden item creation failed; keys kept locally at:"
        warn "  $priv_path"
        warn "  $pub_path"
        warn "Re-run later or import via the Bitwarden desktop app."
        return 1
    fi
}

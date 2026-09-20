#!/usr/bin/env bash
# Render .chezmoiignore across the (profile, machine, secrets) matrix and
# assert whether ~/.kube/homelab.yaml is IGNORED (listed) or DEPLOYED (absent).
#
# The kubeconfig template calls the `bitwarden` template function, so a cell
# that renders it on a machine with no Bitwarden vault aborts `chezmoi apply`
# outright and takes the whole environment build down with it.
#
# Run against the real home/.chezmoiignore, never against the gate in
# isolation: the gate composes with the comment block above it, and a trim
# marker that swallows the preceding newline silently comments the first path
# out. Isolation proves the fragment parses, not that it composes.
set -uo pipefail

CHEZMOI="${CHEZMOI:-chezmoi}"
TMPL="${1:?usage: chezmoiignore-matrix.sh /path/to/.chezmoiignore}"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
fail=0

cfg() { # profile machine secrets
  cat > "$TMP/cfg.toml" <<EOF
[data]
profile = "$1"
name    = "x"
email   = ""
machine = "$2"
display = false
secrets = "$3"
EOF
}

render() { # profile machine secrets cluster_admin
  cfg "$1" "$2" "$3"
  WORKSPACE_CLUSTER_ADMIN="${4:-}" "$CHEZMOI" execute-template \
    --config "$TMP/cfg.toml" < "$TMPL" 2>/dev/null \
    | grep -c '^\.kube/homelab\.yaml$'
}

check() { # label profile machine secrets cluster_admin want
  local label="$1" want="$6" got n
  n=$(render "$2" "$3" "$4" "$5")
  [ "$n" -ge 1 ] && got=IGNORED || got=DEPLOYED
  if [ "$want" = "$got" ]; then
    printf '  PASS  %-46s %s\n' "$label" "$got"
  else
    printf '  FAIL  %-46s want %s, got %s\n' "$label" "$want" "$got"
    fail=1
  fi
}

echo "== workstations keep the kubeconfig =="
check "personal/laptop/bitwarden"        personal laptop    bitwarden ""  DEPLOYED
check "personal/desktop/both"            personal desktop   both      ""  DEPLOYED

echo
echo "== no Bitwarden vault, no kubeconfig =="
check "personal/ephemeral/none"          personal ephemeral none      ""  IGNORED
check "personal/laptop/none"             personal laptop    none      ""  IGNORED
check "personal/laptop/1password"        personal laptop    1password ""  IGNORED

echo
echo "== workspaces only with an explicit opt-in =="
check "personal/ephemeral/bitwarden"     personal ephemeral bitwarden ""  IGNORED
check "personal/ephemeral/bitwarden +CA" personal ephemeral bitwarden 1   DEPLOYED

echo
echo "== never on work machines or cluster nodes =="
check "work/laptop/bitwarden"            work     laptop    bitwarden ""  IGNORED
check "personal/server/bitwarden"        personal server    bitwarden ""  IGNORED

# PR #76 added .local/bin/mcp-breakglass to the same block. It port-forwards
# to the cluster and is useless without the kubeconfig, so the two must stay
# gated together -- a refactor that drops it would ship the break-glass helper
# to work machines and into published images, silently.
echo
echo "== the break-glass helper stays co-gated with the kubeconfig =="
cogate() { # label profile machine secrets cluster_admin
  local label="$1" out k m
  cfg "$2" "$3" "$4"
  out=$(WORKSPACE_CLUSTER_ADMIN="${5:-}" "$CHEZMOI" execute-template \
    --config "$TMP/cfg.toml" < "$TMPL" 2>/dev/null)
  k=$(printf '%s\n' "$out" | grep -c '^\.kube/homelab\.yaml$')
  m=$(printf '%s\n' "$out" | grep -c '^\.local/bin/mcp-breakglass$')
  if [ "$k" -eq "$m" ]; then
    printf '  PASS  %-46s both %s\n' "$label" "$([ "$k" -ge 1 ] && echo IGNORED || echo DEPLOYED)"
  else
    printf '  FAIL  %-46s kubeconfig=%s breakglass=%s\n' "$label" "$k" "$m"
    fail=1
  fi
}

cogate "personal/laptop/bitwarden"       personal laptop    bitwarden ""
cogate "personal/ephemeral/none"         personal ephemeral none      ""
cogate "work/laptop/bitwarden"           work     laptop    bitwarden ""

echo
[ "$fail" -eq 0 ] && echo "ALL PASS" || echo "FAILURES"
exit "$fail"

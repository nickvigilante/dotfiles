#!/usr/bin/env bash
# Render Brewfile.tmpl for one data cell and print its package set, normalized.
#
# Normalization strips comments and padding so the output is the semantic
# content only: which entries of which type. Formatting may change freely;
# a package appearing or disappearing may not.
#
# .chezmoi.os is supplied by the running machine and cannot be overridden, so
# macOS-gated sections are only exercised when this runs on macOS. CI runs it
# on both.
set -uo pipefail

CHEZMOI="${CHEZMOI:-chezmoi}"
PROFILE="${1:?usage: brewfile-parity.sh <profile> <display> <secrets> [machine]}"
DISPLAY_="${2:?}"
SECRETS="${3:?}"
MACHINE="${4:-laptop}"
TMPL="${TMPL:-home/dot_config/dotfiles/Brewfile.tmpl}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/cfg.toml" << EOF
[data]
profile = "$PROFILE"
name    = "x"
email   = ""
machine = "$MACHINE"
display = $DISPLAY_
secrets = "$SECRETS"
EOF

"$CHEZMOI" execute-template --config "$TMP/cfg.toml" < "$TMPL" |
	sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//' |
	grep -E '^(tap|brew|cask|vscode|cargo|go|uv) ' |
	sort

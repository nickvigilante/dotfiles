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

# Resolve paths relative to this script's own location, not the caller's cwd.
# Bare `chezmoi execute-template` does not auto-detect a source directory
# from cwd; it needs an explicit --source or a pre-existing chezmoi config.
# A developer's machine may have a config pointing elsewhere (e.g. a
# different checkout), and a CI runner has no config at all — in both cases
# relying on an ambient default silently reads the wrong (or no) data.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_DIR="$REPO_ROOT/home"

CHEZMOI="${CHEZMOI:-chezmoi}"
PROFILE="${1:?usage: brewfile-parity.sh <profile> <display> <secrets> [machine]}"
DISPLAY_="${2:?}"
SECRETS="${3:?}"
MACHINE="${4:-laptop}"
TMPL="${TMPL:-$REPO_ROOT/home/dot_config/dotfiles/Brewfile.tmpl}"
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

"$CHEZMOI" execute-template --source "$SOURCE_DIR" --config "$TMP/cfg.toml" < "$TMPL" |
	sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//' |
	grep -E '^(tap|brew|cask|vscode|cargo|go|uv|flatpak|npm) ' |
	sort

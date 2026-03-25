#!/usr/bin/env bash
# Bootstrap dotfiles on macOS, Linux, or Raspberry Pi.
#
# Usage (on a fresh machine):
#   sh -c "$(curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/dotfiles/main/bootstrap/install.sh)"
#
# Or if you've already cloned the repo:
#   ./bootstrap/install.sh

set -euo pipefail

DOTFILES_REPO="${DOTFILES_REPO:-https://github.com/nickvigilante/dotfiles.git}"
CHEZMOI_BIN_DIR="$HOME/.local/bin"

# ── Colours ───────────────────────────────────────────────────────────────────
BOLD='\033[1m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
RESET='\033[0m'

header() { echo -e "\n${BOLD}$*${RESET}"; }
info() { echo -e "${CYAN}  →${RESET} $*"; }
ok() { echo -e "${GREEN}  ✓${RESET} $*"; }

# ── Install chezmoi ───────────────────────────────────────────────────────────
header "Step 1/2 — Install chezmoi"

if command -v chezmoi &>/dev/null; then
	ok "chezmoi already installed: $(chezmoi --version)"
elif [[ -x "$CHEZMOI_BIN_DIR/chezmoi" ]]; then
	ok "chezmoi already installed at $CHEZMOI_BIN_DIR/chezmoi"
else
	info "Downloading chezmoi to $CHEZMOI_BIN_DIR..."
	mkdir -p "$CHEZMOI_BIN_DIR"
	sh -c "$(curl -fsSL https://get.chezmoi.io)" -- -b "$CHEZMOI_BIN_DIR"
	ok "chezmoi installed."
fi

export PATH="$CHEZMOI_BIN_DIR:$PATH"

# ── Apply dotfiles ─────────────────────────────────────────────────────────────
header "Step 2/2 — Apply dotfiles"
info "Repo: $DOTFILES_REPO"
info "You'll be prompted for: profile (work/personal), name, email, machine role."
echo ""

chezmoi init --apply "$DOTFILES_REPO"

# ── Done ──────────────────────────────────────────────────────────────────────
header "Done!"
echo ""
echo "  Next steps:"
echo "  1. Restart your shell:   exec zsh"
echo "  2. Check status:         chezmoi status"
echo "  3. Edit config:          chezmoi edit-config"
echo "  4. Jump to source:       czcd"
echo ""

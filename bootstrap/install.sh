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
DOTFILES_DIR="${DOTFILES_DIR:-$HOME/git/nickvigilante/dotfiles}"
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

# ── Clone repo ─────────────────────────────────────────────────────────────────
header "Step 2/3 — Apply dotfiles (first pass)"
info "Repo: $DOTFILES_REPO → $DOTFILES_DIR"

if [[ -d "$DOTFILES_DIR/.git" ]]; then
    ok "Repo already cloned at $DOTFILES_DIR"
else
    mkdir -p "$(dirname "$DOTFILES_DIR")"
    git clone "$DOTFILES_REPO" "$DOTFILES_DIR"
    ok "Cloned to $DOTFILES_DIR"
fi

# Point chezmoi at the repo. chezmoi's default source dir is ~/.local/share/chezmoi;
# we symlink it to the actual repo so the chezmoi CLI works without extra flags.
CHEZMOI_SOURCE="$HOME/.local/share/chezmoi"
if [[ -L "$CHEZMOI_SOURCE" && "$(readlink "$CHEZMOI_SOURCE")" == "$DOTFILES_DIR" ]]; then
    ok "chezmoi source symlink already correct"
else
    rm -f "$CHEZMOI_SOURCE"
    mkdir -p "$(dirname "$CHEZMOI_SOURCE")"
    ln -sf "$DOTFILES_DIR" "$CHEZMOI_SOURCE"
    ok "Linked $CHEZMOI_SOURCE → $DOTFILES_DIR"
fi

info "You'll be prompted for: profile (work/personal), name, email, machine role."
echo ""

chezmoi init --apply

# ── Secrets ────────────────────────────────────────────────────────────────────
header "Step 3/3 — Populate secrets"
echo ""
echo "  Packages including 'bw' (Bitwarden CLI) are now installed."
echo "  To populate ~/.env with your secrets, run the following after restarting:"
echo ""
echo "    bw login            # first time only — creates local vault"
echo "    bw-apply            # unlocks vault + runs chezmoi apply"
echo ""
echo "  On the work machine, also sign in to 1Password first:"
echo "    op signin           # first time only"
echo ""

# ── Done ──────────────────────────────────────────────────────────────────────
header "Bootstrap complete!"
echo ""
echo "  Next steps:"
echo "  1. Restart your shell:   exec zsh"
echo "  2. Populate secrets:     bw login && bw-apply"
echo "  3. Check status:         chezmoi status"
echo "  4. Jump to source:       czcd"
echo ""

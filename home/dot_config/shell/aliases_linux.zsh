# Linux-specific aliases.

# ── Clipboard ─────────────────────────────────────────────────────────────────
# Prefer Wayland (wl-copy), fall back to X11 (xclip).
if command -v wl-copy &>/dev/null; then
    alias copy='wl-copy'
    alias paste='wl-paste'
elif command -v xclip &>/dev/null; then
    alias copy='xclip -selection clipboard'
    alias paste='xclip -selection clipboard -o'
fi

# ── File manager ──────────────────────────────────────────────────────────────
command -v xdg-open &>/dev/null && alias open='xdg-open'

# ── Package managers (distro-aware) ───────────────────────────────────────────
if command -v apt &>/dev/null; then
    alias apti='sudo apt install'
    alias apts='apt search'
    alias aptu='sudo apt update && sudo apt upgrade'
    alias aptr='sudo apt remove'
elif command -v dnf &>/dev/null; then
    alias dnfi='sudo dnf install'
    alias dnfs='dnf search'
    alias dnfu='sudo dnf upgrade'
    alias dnfr='sudo dnf remove'
fi

# ── Homebrew (if installed on Linux) ──────────────────────────────────────────
command -v brew &>/dev/null && alias bup='brew update && brew upgrade && brew cleanup'

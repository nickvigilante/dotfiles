# macOS-specific aliases.

# ── Finder ────────────────────────────────────────────────────────────────────
alias finder='open .'
alias showfiles='defaults write com.apple.finder AppleShowAllFiles YES && killall Finder'
alias hidefiles='defaults write com.apple.finder AppleShowAllFiles NO && killall Finder'

# ── System ────────────────────────────────────────────────────────────────────
alias flushdns='sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder'
alias lock='pmset displaysleepnow'

# ── Clipboard ─────────────────────────────────────────────────────────────────
alias copy='pbcopy'
alias paste='pbpaste'

# ── Homebrew ──────────────────────────────────────────────────────────────────
# `bup` is a function in functions.zsh (takes the shared brew lock).
alias bi='brew install'
alias bs='brew search'
alias bl='brew list'
alias bci='brew install --cask'
alias bcl='brew list --cask'

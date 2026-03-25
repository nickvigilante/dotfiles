# Cross-platform aliases — sourced on all machines.

# ── Navigation ────────────────────────────────────────────────────────────────
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'
alias ~='cd ~'

# ── Listing ───────────────────────────────────────────────────────────────────
# Use eza if available (installed via Homebrew), otherwise fall back to ls.
if command -v eza &>/dev/null; then
    alias ls='eza --icons'
    alias ll='eza --icons -lh'
    alias la='eza --icons -lah'
    alias lt='eza --icons --tree --level=2'
    alias llt='eza --icons -lh --tree --level=2'
else
    alias ll='ls -lh'
    alias la='ls -lah'
fi

# ── Shell ─────────────────────────────────────────────────────────────────────
alias c='clear'
alias q='exit'
alias reload='exec zsh'

# ── Safety nets ───────────────────────────────────────────────────────────────
alias rm='rm -i'
alias cp='cp -i'
alias mv='mv -i'

# ── Git ───────────────────────────────────────────────────────────────────────
alias g='git'
alias gs='git status'
alias ga='git add'
alias gc='git commit'
alias gp='git push'
alias gl='git pull'
alias gd='git diff'
alias gco='git checkout'
alias gbr='git branch'
alias glog='git log --oneline --graph --decorate --all'

# ── Python / uv ───────────────────────────────────────────────────────────────
alias python='python3'
alias pip='uv pip'
alias venv='uv venv'

# ── chezmoi ───────────────────────────────────────────────────────────────────
alias cz='chezmoi'
alias czd='chezmoi diff'
alias cza='bw-apply'        # unlock Bitwarden then apply (see functions.zsh)
alias czaf='chezmoi apply'  # apply without unlocking (safe when no secret changes)
alias cze='chezmoi edit'
alias czs='chezmoi status'
alias czcd='cd "$(chezmoi source-path)"'
alias czup='chezmoi update'

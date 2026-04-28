# ~/.config/shell/completions.zsh
# Tool completions and shell initializations.
# Each block is guarded — safe to source on any machine regardless of what's installed.
# Sourced from ~/.zshrc after oh-my-zsh is initialized.

# ── zoxide — smarter cd (must init after compinit) ────────────────────────────
if command -v zoxide &>/dev/null; then
  eval "$(zoxide init zsh)"
fi

# ── fzf — fuzzy finder key bindings and completions ───────────────────────────
if command -v fzf &>/dev/null; then
  # fzf 0.48+ ships --zsh; fall back to sourcing the completion files directly
  if fzf --zsh &>/dev/null 2>&1; then
    source <(fzf --zsh)
  else
    [[ -f ~/.fzf.zsh ]] && source ~/.fzf.zsh
  fi
fi

# ── gh — GitHub CLI ───────────────────────────────────────────────────────────
if command -v gh &>/dev/null; then
  eval "$(gh completion -s zsh)"
fi

# ── direnv — per-directory environment variables ──────────────────────────────
if command -v direnv &>/dev/null; then
  eval "$(direnv hook zsh)"
fi

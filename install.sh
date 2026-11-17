#!/usr/bin/env bash
# Entry point for `coder dotfiles` and the Coder registry dotfiles module.
#
# Both look only for install.sh / install / bootstrap / setup at the repo root
# (or under script/), run it with no arguments, and expect it to finish
# without prompting. Outside a Coder workspace this is a plain alias for the
# full bootstrap, so `./install.sh --profile work ...` keeps working.
#
# Inside a workspace it takes a lighter path. The full bootstrap installs
# Homebrew and Gum and runs every run_* script, which means minutes of
# package installs on each workspace start. Here chezmoi goes to
# ~/.local/bin, is pointed at this clone, and applies files only
# (--exclude scripts,externals). Set DOTFILES_DRY_RUN=1 to see what would
# change without touching anything.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${CODER:-}" ]]; then
	exec "$here/bootstrap/install.sh" "$@"
fi

bin="$HOME/.local/bin"
mkdir -p "$bin"
export PATH="$bin:$PATH"

if ! command -v chezmoi > /dev/null 2>&1; then
	echo "Installing chezmoi to $bin"
	sh -c "$(curl --proto '=https' --tlsv1.2 -fsLS https://get.chezmoi.io/lb)" -- -b "$bin"
fi

# The template's git-config module exports the workspace owner's identity;
# fall back to whatever it already wrote to ~/.gitconfig.
name="${GIT_AUTHOR_NAME:-$(git config --global user.name 2> /dev/null || true)}"
email="${GIT_AUTHOR_EMAIL:-$(git config --global user.email 2> /dev/null || true)}"

# Make this clone chezmoi's source so a later `chezmoi apply` works without a
# second checkout. coder dotfiles keeps the clone at
# ~/.config/coderv2/dotfiles and pulls it on every start.
src="$HOME/.local/share/chezmoi"
if [[ -L "$src" || ! -e "$src" ]]; then
	mkdir -p "$(dirname "$src")"
	ln -sfn "$here" "$src"
elif [[ "$(cd "$src" && pwd -P)" != "$here" ]]; then
	echo "install.sh: $src exists and is not this clone; leaving it alone" >&2
	exit 1
fi

# init and apply run separately: `chezmoi init --apply --dry-run` skips
# writing the config, and the apply that follows then has no data.
chezmoi init \
	--promptChoice "Profile=work" \
	--promptString "Full name=$name" \
	--promptString "Email address=$email" \
	--promptChoice "Machine role=ephemeral" \
	--promptBool "Has graphical display=false" \
	--promptChoice "Secret managers=none"

args=(--exclude "scripts,externals")
if [[ -n "${DOTFILES_DRY_RUN:-}" ]]; then
	args+=(--dry-run --verbose)
fi
chezmoi apply "${args[@]}"

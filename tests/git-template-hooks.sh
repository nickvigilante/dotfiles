#!/usr/bin/env bash
# Commit in throwaway repos seeded from the git template hooks and assert the
# repo's pre-commit config runs only under a trusted root.
#
# HOME points at a temp dir, so the hooks' real $HOME/git/nickvigilante root
# lands inside it and the test needs no override knob. A fake `pre-commit` on
# PATH logs each stage it is asked to run instead of running anything.
set -uo pipefail

HOOKS="${1:?usage: git-template-hooks.sh /path/to/template/hooks}"
HOOKS=$(cd "$HOOKS" && pwd -P)
TMP=$(cd "$(mktemp -d)" && pwd -P)
trap 'rm -rf "$TMP"' EXIT
fail=0

export HOME="$TMP/home" XDG_CONFIG_HOME="$TMP/home/.config" GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com
export GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
mkdir -p "$HOME" "$TMP/bin" "$TMP/template/hooks" "$TMP/outside"

for f in "$HOOKS"/executable_*; do
	cp "$f" "$TMP/template/hooks/${f##*/executable_}"
	chmod +x "$TMP/template/hooks/${f##*/executable_}"
done

cat > "$TMP/bin/pre-commit" << 'FAKE'
#!/usr/bin/env bash
echo "$3" >> "$PWD/.ran"
FAKE
chmod +x "$TMP/bin/pre-commit"
export PATH="$TMP/bin:$PATH"

mkrepo() { # dir
	mkdir -p "$1"
	git init -q --template="$TMP/template" "$1"
	touch "$1/.pre-commit-config.yaml"
}

check() { # label commit-dir want(RUN|SKIP)
	local label="$1" dir="$2" want="$3" got ran
	rm -f "$dir/.ran"
	(cd "$dir" && git add .pre-commit-config.yaml && git commit -q --allow-empty -m x) > /dev/null 2>&1
	ran=$(cat "$dir/.ran" 2> /dev/null | tr '\n' ' ')
	case "$ran" in
		"pre-commit commit-msg ") got=RUN ;;
		"") got=SKIP ;;
		*) got="?($ran)" ;;
	esac
	if [ "$want" = "$got" ]; then
		printf '  PASS  %-44s %s\n' "$label" "$got"
	else
		printf '  FAIL  %-44s want %s, got %s\n' "$label" "$want" "$got"
		fail=1
	fi
}

root="$HOME/git/nickvigilante"

echo "== trusted root runs both stages =="
mkrepo "$root/repo"
check "repo under trusted root" "$root/repo" RUN
mkrepo "$root/repo/.worktrees/sub"
check "nested repo under trusted root" "$root/repo/.worktrees/sub" RUN
git -C "$root/repo" worktree add -q "$root/repo/.worktrees/wt" > /dev/null 2>&1
touch "$root/repo/.worktrees/wt/.pre-commit-config.yaml"
check "worktree under trusted root" "$root/repo/.worktrees/wt" RUN
ln -s "$root/repo" "$TMP/outside/link-in"
check "symlink from outside into trusted root" "$TMP/outside/link-in" RUN

echo
echo "== anywhere else skips silently =="
mkrepo "$TMP/outside/repo"
check "repo outside any trusted root" "$TMP/outside/repo" SKIP
mkrepo "$HOME/git/nickvigilante-evil"
check "sibling sharing the root's prefix" "$HOME/git/nickvigilante-evil" SKIP
mkrepo "$HOME/git"
check "parent of the trusted root" "$HOME/git" SKIP
ln -s "$TMP/outside/repo" "$root/link-out"
check "symlink from trusted root to outside" "$root/link-out" SKIP

echo
if [ "$fail" -ne 0 ]; then
	echo "FAILED"
	exit 1
fi
echo "all checks passed"

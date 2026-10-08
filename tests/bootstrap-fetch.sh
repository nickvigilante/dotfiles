#!/usr/bin/env bash
# Exercise install.sh's fetch_bootstrap_libs without the network: a fake
# downloader serves a `git archive` tarball of this repo, and a fake git
# either works or fails the way macOS's Xcode stub does. The libraries must
# arrive without git when GitHub is reachable, and git must be the fallback.
set -uo pipefail

INSTALL="${1:?usage: bootstrap-fetch.sh /path/to/bootstrap/install.sh}"
REPO=$(cd "$(dirname "$INSTALL")/.." && pwd -P)
TMP=$(cd "$(mktemp -d)" && pwd -P)
trap 'rm -rf "$TMP"' EXIT
fail=0

# Pull just the function out of install.sh; running the whole script would
# start installing things.
awk '/^fetch_bootstrap_libs\(\) \{/{f=1} f{print} f&&/^\}/{exit}' "$INSTALL" > "$TMP/fn.sh"
if ! grep -q '^fetch_bootstrap_libs() {' "$TMP/fn.sh"; then
	echo "FAIL  install.sh defines fetch_bootstrap_libs()"
	exit 1
fi

git -C "$REPO" archive --prefix=dotfiles-main/ HEAD | gzip > "$TMP/repo.tar.gz"
mkdir -p "$TMP/bin"
# Downloader: serves the tarball unless DOWNLOAD_FAILS=1, and logs each URL.
cat > "$TMP/bin/curl" << EOF
#!/usr/bin/env bash
echo "\${@: -1}" >> "$TMP/downloads.log"
[ "\${DOWNLOAD_FAILS:-0}" = 1 ] && exit 22
cat "$TMP/repo.tar.gz"
EOF
# git: fails like the Xcode stub unless GIT_WORKS=1; a working clone copies
# the bootstrap dir into the destination and logs its arguments.
cat > "$TMP/bin/git" << EOF
#!/usr/bin/env bash
[ "\${GIT_WORKS:-0}" = 1 ] || { echo "xcode-select: note: No developer tools were found" >&2; exit 1; }
[ "\$1" = clone ] || exit 0
echo "\$*" >> "$TMP/git.log"
dest="\${@: -1}"
mkdir -p "\$dest" && cp -R "$REPO/bootstrap" "\$dest/"
EOF
chmod +x "$TMP/bin/curl" "$TMP/bin/git"

run() { # label repo-url -> runs the function in a clean subshell; sets rc, dest
	rm -f "$TMP/downloads.log" "$TMP/git.log"
	dest="$TMP/case-$1"
	mkdir -p "$dest"
	# shellcheck disable=SC2329 # err and info are called by the sourced function
	(
		export PATH="$TMP/bin:$PATH" DOTFILES_REPO="$2"
		err() { echo "$*" >&2; }
		info() { :; }
		# shellcheck source=/dev/null
		source "$TMP/fn.sh"
		fetch_bootstrap_libs "$dest"
	) > "$TMP/out" 2>&1
	rc=$?
}

expect() { # label condition...
	local label="$1"
	shift
	if "$@"; then
		echo "PASS  $label"
	else
		echo "FAIL  $label"
		sed 's/^/      /' "$TMP/out"
		fail=1
	fi
}

GH=https://github.com/nickvigilante/dotfiles.git

run tarball "$GH"
expect "GitHub repo, git broken: succeeds" test "$rc" = 0
expect "GitHub repo, git broken: libraries unpacked" test -f "$dest/src/bootstrap/lib/detect.sh"
expect "GitHub repo: downloads main's tarball" \
	grep -qx "https://codeload.github.com/nickvigilante/dotfiles/tar.gz/refs/heads/main" "$TMP/downloads.log"
expect "GitHub repo: does not clone" test ! -e "$TMP/git.log"

DOTFILES_REF=feature run ref "$GH"
expect "DOTFILES_REF selects the branch" \
	grep -qx "https://codeload.github.com/nickvigilante/dotfiles/tar.gz/refs/heads/feature" "$TMP/downloads.log"

run no-suffix "https://github.com/nickvigilante/dotfiles"
expect "repo URL without .git: same tarball" \
	grep -qx "https://codeload.github.com/nickvigilante/dotfiles/tar.gz/refs/heads/main" "$TMP/downloads.log"

DOWNLOAD_FAILS=1 GIT_WORKS=1 run fallback "$GH"
expect "download fails, git works: succeeds" test "$rc" = 0
expect "download fails, git works: clones main shallowly" grep -q -- '--depth=1 --branch main' "$TMP/git.log"
expect "download fails, git works: libraries present" test -f "$dest/src/bootstrap/lib/detect.sh"

DOWNLOAD_FAILS=1 run neither "$GH"
expect "download fails, git broken: fails" test "$rc" != 0
expect "download fails, git broken: explains why" grep -qi 'git' "$TMP/out"

GIT_WORKS=1 run gitlab "https://gitlab.com/someone/dotfiles.git"
expect "non-GitHub repo: no download attempted" test ! -e "$TMP/downloads.log"
expect "non-GitHub repo: cloned with git" test -f "$dest/src/bootstrap/lib/detect.sh"

exit "$fail"

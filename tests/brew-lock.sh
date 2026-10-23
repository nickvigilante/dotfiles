#!/usr/bin/env bash
# Run install-packages and update-packages against a fake brew that leaves a
# background process behind, as a cask or formula can (an `op daemon` did).
# The scripts must hold the shared brew lock while brew runs, and must release
# it when they exit even though that process lives on.
set -uo pipefail

INSTALL_TEMPLATE="${1:?usage: brew-lock.sh run_after_install-packages.sh.tmpl update-packages}"
UPDATE_SCRIPT="${2:?usage: brew-lock.sh run_after_install-packages.sh.tmpl update-packages}"
command -v flock > /dev/null || {
	echo "FAIL  flock is required"
	exit 1
}
TMP=$(cd "$(mktemp -d)" && pwd -P)
kill_children() {
	[ -f "$TMP/children" ] && xargs kill < "$TMP/children" 2> /dev/null
	rm -f "$TMP/children"
}
# shellcheck disable=SC2329 # called by the EXIT trap
cleanup() {
	kill_children
	rm -rf "$TMP"
}
trap cleanup EXIT
fail=0

export XDG_CACHE_HOME="$TMP/cache"
LOCK="$XDG_CACHE_HOME/dotfiles/brew.lock"
mkdir -p "$TMP/bin" "$TMP/home/.config/dotfiles" "$XDG_CACHE_HOME"
echo 'brew "jq"' > "$TMP/home/.config/dotfiles/Brewfile"

# The fake brew records whether the lock was held while it ran, then starts a
# long-lived child for the commands that install or update.
cat > "$TMP/bin/brew" << EOF
#!/usr/bin/env bash
if flock -n "$LOCK" true; then echo free >> "$TMP/during"; else echo held >> "$TMP/during"; fi
case "\$1 \${2-}" in
	"bundle check") exit 1 ;;
	"bundle install" | "update "*)
		sleep 300 < /dev/null > /dev/null 2>&1 &
		echo \$! >> "$TMP/children"
		;;
esac
exit 0
EOF
# update-packages also runs these on Linux; keep them off the real system.
printf '#!/bin/sh\nexit 0\n' > "$TMP/bin/sudo"
printf '#!/bin/sh\nexit 0\n' > "$TMP/bin/chezmoi"
chmod +x "$TMP/bin/"*

chezmoi execute-template --override-data '{"machine": "laptop", "display": false}' \
	< "$INSTALL_TEMPLATE" > "$TMP/install.sh" || {
	echo "FAIL  could not render $INSTALL_TEMPLATE"
	exit 1
}

run() { # script -> sets rc
	: > "$TMP/during"
	HOME="$TMP/home" PATH="$TMP/bin:$PATH" bash "$1" > "$TMP/out" 2>&1
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

# shellcheck disable=SC2329 # called through expect
always_held() { [ -s "$TMP/during" ] && ! grep -q free "$TMP/during"; }

for name in install update; do
	if [ "$name" = install ]; then script="$TMP/install.sh"; else script="$UPDATE_SCRIPT"; fi
	run "$script"
	expect "$name-packages: exits 0" test "$rc" = 0
	expect "$name-packages: holds the lock while brew runs" always_held
	expect "$name-packages: a process brew left behind does not keep the lock" flock -n "$LOCK" true
	# Otherwise a leak here would stall the next script for its 5-minute wait.
	kill_children
done

exit "$fail"

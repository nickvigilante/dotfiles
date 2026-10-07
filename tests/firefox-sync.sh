#!/usr/bin/env bash
# Render the Firefox sync script's Linux branch and run it against fake HOMEs:
# it must configure every profile it finds (native, snap, Flatpak), keep other
# prefs, stay idempotent, and exit 0 with a warning when no profile exists yet
# so it never aborts `chezmoi apply`.
set -uo pipefail

TEMPLATE="${1:?usage: firefox-sync.sh /path/to/configure-firefox-sync.sh.tmpl}"
TMP=$(cd "$(mktemp -d)" && pwd -P)
trap 'rm -rf "$TMP"' EXIT
fail=0
PREF='user_pref("identity.sync.tokenserver.uri", "https://firefox-sync.vigihome.net/1.0/sync/1.5");'

# The script is gated on Linux with a display; force that branch to render.
sed 's/(eq .chezmoi.os "linux")/true/' "$TEMPLATE" |
	chezmoi execute-template --override-data '{"display": true}' > "$TMP/script.sh" || {
	echo "FAIL  could not render $TEMPLATE"
	exit 1
}

newhome() { # name -> prints a fresh HOME path
	mkdir -p "$TMP/$1"
	echo "$TMP/$1"
}

profile() { # firefox-dir ini(installs|profiles) relative-profile-path
	mkdir -p "$1/$3"
	if [ "$2" = installs ]; then
		printf '[ABCDEF0123456789]\nDefault=%s\nLocked=1\n' "$3" > "$1/installs.ini"
	else
		printf '[Profile0]\nName=default\nIsRelative=1\nPath=%s\nDefault=1\n' "$3" > "$1/profiles.ini"
	fi
}

run() { # home -> sets rc
	HOME="$1" bash "$TMP/script.sh" > "$TMP/out" 2>&1
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

prefs_in() { grep -c 'identity.sync.tokenserver.uri' "$1" 2> /dev/null || echo 0; }

h=$(newhome never-launched)
run "$h"
expect "no Firefox yet: exits 0" test "$rc" = 0
expect "no Firefox yet: warns" grep -qi 'launch Firefox' "$TMP/out"

h=$(newhome no-ini)
mkdir -p "$h/.mozilla/firefox"
run "$h"
expect "profile dir without an ini: exits 0" test "$rc" = 0

h=$(newhome native)
profile "$h/.mozilla/firefox" installs abc.default-release
run "$h"
run "$h"
expect "native profile: exits 0" test "$rc" = 0
expect "native profile: pref written exactly once after two runs" \
	test "$(prefs_in "$h/.mozilla/firefox/abc.default-release/user.js")" = 1

h=$(newhome snap)
profile "$h/snap/firefox/common/.mozilla/firefox" profiles snp.default
run "$h"
expect "snap profile: configured" \
	grep -qF "$PREF" "$h/snap/firefox/common/.mozilla/firefox/snp.default/user.js"

h=$(newhome flatpak-and-native)
profile "$h/.var/app/org.mozilla.firefox/.mozilla/firefox" installs flt.default-release
profile "$h/.mozilla/firefox" installs nat.default-release
run "$h"
expect "Flatpak profile: configured" \
	grep -qF "$PREF" "$h/.var/app/org.mozilla.firefox/.mozilla/firefox/flt.default-release/user.js"
expect "native profile next to Flatpak: configured" \
	grep -qF "$PREF" "$h/.mozilla/firefox/nat.default-release/user.js"

h=$(newhome existing-prefs)
profile "$h/.mozilla/firefox" installs old.default-release
printf '%s\n%s\n' 'user_pref("browser.startup.page", 3);' \
	'user_pref("identity.sync.tokenserver.uri", "https://old.example/1.0/sync/1.5");' \
	> "$h/.mozilla/firefox/old.default-release/user.js"
run "$h"
expect "existing user.js: other prefs kept" \
	grep -qF 'user_pref("browser.startup.page", 3);' "$h/.mozilla/firefox/old.default-release/user.js"
expect "existing user.js: old tokenserver replaced" \
	test "$(prefs_in "$h/.mozilla/firefox/old.default-release/user.js")" = 1
expect "existing user.js: new tokenserver present" \
	grep -qF "$PREF" "$h/.mozilla/firefox/old.default-release/user.js"

exit "$fail"

#!/usr/bin/env bash
# Feed sample commit messages to no-vendor-attribution.sh (commit-msg mode)
# and check its exit status. The vendor strings below are samples; this file
# and the guard are the only places they may appear.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
guard="$here/no-vendor-attribution.sh"

scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT

failures=0
total=0

# check_with <expected-exit> <label> <message> [guard option...]
check_with() {
	local want="$1" label="$2" msg="$3" got=0
	shift 3
	local file="$scratch/msg"
	printf '%s\n' "$msg" > "$file"
	"$guard" "$@" "$file" > /dev/null 2>&1 || got=$?
	total=$((total + 1))
	if [[ "$got" -eq "$want" ]]; then
		echo "PASS: $label (exit $got)"
	else
		echo "FAIL: $label (want exit $want, got $got)"
		failures=$((failures + 1))
	fi
}

# check <expected-exit> <label> <message>: the default (editor) mode.
check() {
	check_with "$1" "$2" "$3"
}

# check_stored <expected-exit> <label> <message>: --no-strip-comments, the mode
# CI uses on stored commit messages and PR text.
check_stored() {
	check_with "$1" "$2" "$3" --no-strip-comments
}

# Must be blocked (exit 1).

# A trailer for each vendor token, with a name-and-email style value.
for token in Claude Anthropic Copilot GPT ChatGPT OpenAI Gemini Codex Cursor Devin Sonnet Opus Haiku; do
	check 1 "trailer names $token" "fix: thing

Co-Authored-By: $token <noreply@example.com>"
done
check 1 "trailer, vendor only in email domain" "fix: thing

Co-Authored-By: Bot <noreply@anthropic.com>"
check 1 "trailer, lower case" "fix: thing

co-authored-by: claude <noreply@example.com>"
check 1 "trailer, upper case" "fix: thing

CO-AUTHORED-BY: COPILOT <noreply@example.com>"
check 1 "trailer, no space after colon" "fix: thing

Co-Authored-By:Claude <noreply@example.com>"
check 1 "trailer, versioned model name" "fix: thing

Co-Authored-By: GPT-4o <noreply@example.com>"
check 1 "assisted-by trailer names a vendor" "fix: thing

Assisted-by: Claude"
check 1 "footer, markdown link with robot emoji" "fix: thing

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
check 1 "footer, plain, no emoji" "Generated with Claude Code"
check 1 "footer, Built with" "Built with Cursor"
check 1 "footer, Made with" "Made with Copilot"
check 1 "footer, Created with" "Created with ChatGPT"
check 1 "footer, Written with" "Written with Gemini"
check 1 "footer, Authored by" "Authored by Devin"
check 1 "footer, filler words before the vendor" "Built with the help of Claude"
check 1 "footer, lower case" "generated with claude"
check 1 "footer, emphasised" "*Generated with Claude Code*"
check 1 "footer inside a longer multi-line message" "feat: add a widget

The widget renders a list of items and caches the result.
It falls back to an empty list when the source is missing.

Refs #12

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Assisted-by: AI"
check 1 "vendor trailer after a comment block" "fix: thing

# Please enter the commit message for your changes.

Co-Authored-By: Claude <noreply@example.com>"

# Must be allowed (exit 0).
check 0 "Assisted-by: AI trailer" "fix: thing

Assisted-by: AI"
check 0 "Built with AI assistance footer" "Built with AI assistance."
check 0 "normal message" "fix: handle empty config

The loader crashed when the file had no entries.
Return an empty map instead."
check 0 "human co-author" "fix: thing

Co-Authored-By: Jane Doe <jane@example.com>"
check 0 "prose with a vendor word (opus, haiku)" "docs: tidy the notes

Move the opus list and the haiku collection into their own section."
check 0 "prose with a vendor word inside an identifier" "refactor: rename handle_gemini and codex_index helpers"
check 0 "vendor word starts a prose sentence" "docs: note

Claude is mentioned here only as a word in a sentence."
check 0 "prose with generated/built/created and no vendor" "docs: note

Generated with care, built by hand, created for testing."
check 0 "vendor only on a comment line" "fix: thing

# Co-Authored-By: Claude <noreply@example.com>
# Generated with Claude Code

Assisted-by: AI"
check 0 "vendor only after the scissors line" "fix: thing

Assisted-by: AI
# ------------------------ >8 ------------------------
# Do not modify or remove the line above.
diff --git a/x b/x
+Co-Authored-By: Claude <noreply@example.com>
+Generated with Claude Code"
check 0 "empty message" ""

# --no-strip-comments: a "#" line is content, not a git comment.
check_stored 1 "stored: vendor footer on a # line" "fix: thing

# Co-Authored-By: Claude <noreply@example.com>"
check_stored 1 "stored: markdown heading footer" "fix: thing

## Generated with Claude Code"
check_stored 1 "stored: vendor footer after a scissors-shaped line" "fix: thing

# ------------------------ >8 ------------------------
Generated with Claude Code"
check_stored 1 "stored: plain trailer still blocked" "fix: thing

Co-Authored-By: Claude <noreply@example.com>"
check_stored 1 "stored: CRLF line endings" "$(printf 'fix: thing\r\n\r\nBuilt with Claude Code\r')"
check_stored 0 "stored: # heading without a vendor" "# Summary

Assisted-by: AI"
check_stored 0 "stored: normal message" "fix: handle empty config"
check_stored 0 "stored: empty message" ""
# Without the option the same "#" line is still ignored (editor mode).
check 0 "default mode still ignores the # footer line" "fix: thing

# Co-Authored-By: Claude <noreply@example.com>"

# Option handling: usage errors exit 2.
usage_case() {
	local label="$1" got=0
	shift
	"$guard" "$@" > /dev/null 2>&1 || got=$?
	total=$((total + 1))
	if [[ "$got" -eq 2 ]]; then
		echo "PASS: $label (exit $got)"
	else
		echo "FAIL: $label (want exit 2, got $got)"
		failures=$((failures + 1))
	fi
}
usage_case "option without a file is a usage error" --no-strip-comments
usage_case "unknown option is a usage error" --bogus "$scratch/msg"
usage_case "two files are a usage error" "$scratch/msg" "$scratch/msg"
usage_case "missing file is an error" --no-strip-comments "$scratch/absent"

echo
if [[ "$failures" -ne 0 ]]; then
	echo "$failures of $total cases failed" >&2
	exit 1
fi
echo "all $total cases passed"

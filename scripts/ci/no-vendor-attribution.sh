#!/usr/bin/env bash
# Enforce vendor-neutral AI attribution. The only allowed signals are the
# trailer "Assisted-by: AI" and the PR footer "Built with AI assistance".
# Naming an AI vendor, product or model as the author or assistant is not.
#
# Usage:
#   no-vendor-attribution.sh <commit-msg-file>   scan one commit message
#   no-vendor-attribution.sh                     scan tracked files
#
# The guard matches the SHAPE of an attribution, never a bare word, because
# ordinary prose contains some of these words (an opus, a haiku, a function
# named handle_gemini). Two shapes are blocked:
#   a) a Co-Authored-By (or Assisted-by) trailer that names a vendor token;
#   b) a "Generated with", "Built with", "Made with", "Created with",
#      "Written with" or "Authored by" style footer line that names one.
set -euo pipefail

# AI vendor, product and model tokens. This list and the sample strings in
# test-no-vendor-attribution.sh are the only places these names appear.
vendors='(claude|anthropic|copilot|(chat)?gpt[0-9]*|openai|gemini|codex|cursor|devin|sonnet|opus|haiku)'

# Lines start after any non-alphanumeric decoration (whitespace, a comment
# marker, a bullet, an emoji). No \b: it is not portable to BSD grep.
lead='^[^[:alnum:]]*'
endb='([^[:alnum:]]|$)'

# a) trailer naming a vendor anywhere in its value (name or email domain).
trailer="${lead}(co-authored-by|assisted-by)[[:space:]]*:(.*[^[:alnum:]])?${vendors}${endb}"

# b) footer: verb, preposition, up to three filler words, then a vendor.
footer="${lead}(generated|built|made|created|written|authored)[[:space:]]+(with|by|using)([^[:alnum:]]+(the|an?|ai|help|of|from|assistance|assistant)){0,3}[^[:alnum:]]+${vendors}${endb}"

fail_msg="vendor-specific AI attribution found. Use 'Assisted-by: AI' in commits and 'Built with AI assistance' in PR bodies; never name a model, vendor or product."

if [[ $# -gt 1 ]]; then
	echo "usage: ${0##*/} [commit-msg-file]" >&2
	exit 2
fi

if [[ $# -eq 1 ]]; then
	# commit-msg mode.
	target="$1"
	if [[ ! -f "$target" ]]; then
		echo "${0##*/}: not a file: $target" >&2
		exit 2
	fi
	# Blank out git's comment lines and everything after the scissors line
	# (the diff that `git commit -v` appends), keeping line numbers intact.
	scratch="$(mktemp)"
	trap 'rm -f -- "$scratch"' EXIT
	awk '/^# -+ >8 -+$/ { cut = 1 } cut || /^#/ { print ""; next } { print }' "$target" > "$scratch"
	rc=0
	hits="$(grep -nEi -e "$trailer" -e "$footer" -- "$scratch")" || rc=$?
	if [[ $rc -gt 1 ]]; then
		echo "${0##*/}: grep failed (exit $rc)" >&2
		exit "$rc"
	fi
	if [[ $rc -eq 0 ]]; then
		while IFS= read -r line; do
			printf '%s:%s\n' "$target" "${line:0:200}" >&2
		done <<< "$hits"
		echo "ERROR: $fail_msg" >&2
		exit 1
	fi
	exit 0
fi

# files mode: scan tracked files from the repo root.
cd "$(git rev-parse --show-toplevel)"
# home/dot_claude quotes the forbidden forms while documenting the rule, and
# docs holds planning artifacts. The guard and its test hold the patterns.
rc=0
hits="$(git grep -nEiI -e "$trailer" -e "$footer" -- . \
	':(exclude)docs/**' \
	':(exclude)home/dot_claude/**' \
	':(exclude)scripts/ci/no-vendor-attribution.sh' \
	':(exclude)scripts/ci/test-no-vendor-attribution.sh')" || rc=$?
if [[ $rc -gt 1 ]]; then
	echo "${0##*/}: git grep failed (exit $rc)" >&2
	exit "$rc"
fi
if [[ $rc -eq 0 ]]; then
	while IFS= read -r line; do
		printf '%s\n' "${line:0:200}" >&2
	done <<< "$hits"
	echo "ERROR: $fail_msg" >&2
	exit 1
fi
exit 0

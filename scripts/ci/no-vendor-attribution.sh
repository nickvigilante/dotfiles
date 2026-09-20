#!/usr/bin/env bash
# Enforce vendor-neutral AI attribution. The only allowed signals are the
# trailer "Assisted-by: AI" and the PR footer "Built with AI assistance".
# Naming an AI vendor, product or model as the author or assistant is not.
#
# Usage:
#   no-vendor-attribution.sh [--no-strip-comments] <msg-file>   scan one message
#   no-vendor-attribution.sh                                    scan tracked files
#
# Message mode treats the file as a message that git is about to record, so it
# ignores the comment lines git adds (lines starting with "#") and everything
# after the scissors line. --no-strip-comments treats the file as a STORED
# message (git log output, a PR title or body), where a "#" line is real
# content such as a markdown heading, and scans every line.
#
# The guard matches the SHAPE of an attribution, never a bare word, because
# ordinary prose contains some of these words (an opus, a haiku, a function
# named handle_gemini). Two shapes are blocked:
#   a) a Co-Authored-By (or Assisted-by) trailer that names a vendor token;
#   b) a "Generated with", "Built with", "Made with", "Created with",
#      "Written with" or "Authored by" style footer line that names one.
#
# Known false positives (both are blocked, by design of a shape-only match):
#   - a human co-author, or an Assisted-by value, that contains a listed token,
#     for example a person whose given name equals one of the tokens, or an
#     email domain that contains one;
#   - a footer-shaped line that starts with "Made with" followed by a
#     token-like ordinary word, for example a phrase about a text cursor.
# Reword the line so it no longer has the trailer or footer shape.
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

usage="usage: ${0##*/} [--no-strip-comments] [msg-file]"
strip_comments=1
target=""
for arg in "$@"; do
	case "$arg" in
		--no-strip-comments) strip_comments=0 ;;
		-*)
			echo "$usage" >&2
			exit 2
			;;
		*)
			if [[ -n "$target" ]]; then
				echo "$usage" >&2
				exit 2
			fi
			target="$arg"
			;;
	esac
done
if [[ -z "$target" && "$strip_comments" -eq 0 ]]; then
	echo "${0##*/}: --no-strip-comments needs a message file" >&2
	exit 2
fi

if [[ -n "$target" ]]; then
	# message mode.
	if [[ ! -f "$target" ]]; then
		echo "${0##*/}: not a file: $target" >&2
		exit 2
	fi
	if [[ "$strip_comments" -eq 1 ]]; then
		# Blank out git's comment lines and everything after the scissors line
		# (the diff that `git commit -v` appends), keeping line numbers intact.
		scratch="$(mktemp)"
		trap 'rm -f -- "$scratch"' EXIT
		awk '/^# -+ >8 -+$/ { cut = 1 } cut || /^#/ { print ""; next } { print }' "$target" > "$scratch"
	else
		# A stored message has no git-added comments and no scissors section.
		# Honouring either would let a "#" line or a scissors line hide a footer.
		scratch="$target"
	fi
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

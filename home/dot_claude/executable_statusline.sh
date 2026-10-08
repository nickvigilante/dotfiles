#!/bin/sh
# Claude Code status line. Reads the session JSON on stdin and prints two rows:
#
#   ~/git/nickvigilante/dotfiles | ⎇ main | +42 -10              fix-statusline
#   Opus 5.5 (high) | ctx 31% of 200k                            $2.45 | v2.1.300
#
# Layout inspired by Sam Volin's statusline-command.sh in github.com/untra/dotfiles.
#
# Everything comes from the payload except branch and diff stats (two git calls).
# The transcript is never read: session_name and used_percentage are in the
# payload, and slurping a multi-MB transcript on every refresh is the slowest
# thing a status line can do. Claude Code cancels a run that is still going when
# the next update arrives, so a slow script can end up showing nothing at all.
#
# Must never error: any missing field or tool just drops its segment.

command -v jq > /dev/null 2>&1 || exit 0

# @sh quotes every value, so a session name with quotes or spaces cannot break
# the eval.
eval "$(jq -r '
  def k: if . >= 1000000 then "\(. / 100000 | floor / 10)M"
         elif . >= 1000 then "\(. / 1000 | floor)k"
         else tostring end;
  .context_window as $cw
  | @sh "cwd=\(.workspace.current_dir // .cwd // "")",
    @sh "model=\(.model.display_name // "")",
    @sh "effort=\(.effort.level // "")",
    @sh "version=\(.version // "")",
    @sh "session=\(.session_name // "")",
    @sh "cost=\(.cost.total_cost_usd // "")",
    @sh "ctx_pct=\($cw.used_percentage // "" | if type == "number" then (. + 0.5 | floor) else . end)",
    @sh "ctx_size=\($cw.context_window_size // "" | if type == "number" then k else . end)"
' 2> /dev/null)" || exit 0

reset=$(printf '\033[0m')
blue=$(printf '\033[34m')
magenta=$(printf '\033[35m')
yellow=$(printf '\033[33m')
cyan=$(printf '\033[36m')
green=$(printf '\033[32m')
red=$(printf '\033[31m')
dim=$(printf '\033[2m')
sep=" ${dim}|${reset} "
sep_plain=' | '

# --no-optional-locks keeps a refresh from contending for .git/index.lock with
# whatever git command the session is running.
branch=''
changes=''
if [ -n "${cwd:-}" ] && [ -d "$cwd" ] && command -v git > /dev/null 2>&1; then
	g() { git -C "$cwd" --no-optional-locks "$@" 2> /dev/null; }
	branch=$(g branch --show-current)
	[ -n "$branch" ] || branch=$(g rev-parse --short HEAD)
	# Against HEAD covers staged and unstaged in one call.
	changes=$(g diff HEAD --shortstat | awk '{
		for (i = 2; i <= NF; i++) {
			if ($i ~ /^insertion/) a = $(i - 1)
			if ($i ~ /^deletion/) d = $(i - 1)
		}
		if (a || d) printf "+%d -%d", a, d
	}')
fi

# Display width of escape-free text. dash counts ${#s} in bytes, so the
# three-byte ⎇ would throw padding off; drop UTF-8 continuation bytes instead.
width_of() {
	printf '%s' "$1" | LC_ALL=C tr -d '\200-\277' | wc -c | tr -d ' '
}

# Each row is built twice, colored for output and plain for measuring.
add() { # add <row> <color> <text>
	eval "_c=\${$1_c:-} _p=\${$1_p:-}"
	if [ -n "$_p" ]; then
		_c="$_c$sep"
		_p="$_p$sep_plain"
	fi
	eval "$1_c=\$_c\$2\$3\$reset $1_p=\$_p\$3"
}

# Right-align the right group when $COLUMNS (set by Claude Code) leaves room;
# otherwise join the groups with a separator.
row() { # row <left> <right>
	lc='' rc=''
	eval "lc=\${$1_c:-} lp=\${$1_p:-} rc=\${$2_c:-} rp=\${$2_p:-}"
	if [ -z "$lp" ] || [ -z "$rp" ]; then
		[ -n "$lp$rp" ] && printf '%s\n' "$lc$rc"
		return 0
	fi
	case ${COLUMNS:-} in
		'' | *[!0-9]*) gap=0 ;;
		*) gap=$((COLUMNS - $(width_of "$lp") - $(width_of "$rp"))) ;;
	esac
	if [ "$gap" -ge 2 ]; then
		printf "%s%${gap}s%s\n" "$lc" '' "$rc"
	else
		printf '%s%s%s\n' "$lc" "$sep" "$rc"
	fi
}

if [ -n "${cwd:-}" ]; then
	case $cwd in
		"$HOME") cwd='~' ;;
		"$HOME"/*) cwd="~${cwd#"$HOME"}" ;;
	esac
	add l1 "$blue" "$cwd"
fi
[ -n "$branch" ] && add l1 "$magenta" "⎇ $branch"
[ -n "$changes" ] && add l1 "$yellow" "$changes"
[ -n "${session:-}" ] && add r1 "$cyan" "$session"

if [ -n "${model:-}" ]; then
	[ -n "${effort:-}" ] && model="$model ($effort)"
	add l2 '' "$model"
fi
case ${ctx_pct:-x} in *[!0-9]*) ctx_pct='' ;; esac
if [ -n "$ctx_pct" ]; then
	# Green while there is room, red as compaction approaches.
	if [ "$ctx_pct" -ge 80 ]; then
		c=$red
	elif [ "$ctx_pct" -ge 50 ]; then
		c=$yellow
	else
		c=$green
	fi
	add l2 "$c" "ctx ${ctx_pct}%${ctx_size:+ of $ctx_size}"
fi
if [ -n "${cost:-}" ]; then
	cost=$(printf '%.2f' "$cost" 2> /dev/null) && add r2 "$green" "\$$cost"
fi
[ -n "${version:-}" ] && add r2 "$dim" "v$version"

row l1 r1
row l2 r2
exit 0

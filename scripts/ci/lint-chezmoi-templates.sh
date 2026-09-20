#!/usr/bin/env bash
# Prove that every chezmoi-managed target renders, that every rendered shell
# script parses, and that every rendered bash/sh script passes shellcheck.
# Runs from pre-commit and CI.
#
# Hermetic by construction: it never reads the user's chezmoi config, source
# directory, state, cache, network or secret managers.
#   - chezmoi gets an explicit --config (scripts/ci/chezmoi-config/<profile>.toml),
#     --source, --destination, --cache and --persistent-state, all under a
#     mktemp directory except the config file.
#   - The source is a scratch copy of home/ without .chezmoiexternal.toml: an
#     archive external is downloaded whenever chezmoi reads the source state,
#     even with --refresh-externals=never. That file is rendered separately
#     with `chezmoi execute-template`, which does not fetch anything.
#   - bw and op are stubbed on PATH so a template can never reach a real vault.
#
# Usage: scripts/ci/lint-chezmoi-templates.sh
# Env:   CHEZMOI_CI_PROFILE  personal (default) | work
set -euo pipefail

repo=$(git rev-parse --show-toplevel)
profile=${CHEZMOI_CI_PROFILE:-personal}
config="$repo/scripts/ci/chezmoi-config/$profile.toml"

if [[ ! -f "$config" ]]; then
	echo "error: no chezmoi CI config for profile '$profile': $config" >&2
	exit 2
fi
for tool in chezmoi shellcheck bash zsh; do
	if ! command -v "$tool" > /dev/null 2>&1; then
		echo "error: required tool not found on PATH: $tool" >&2
		exit 2
	fi
done

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
dest="$scratch/dest"
src="$scratch/src"
out="$scratch/rendered"
mkdir -p "$dest" "$src" "$out" "$scratch/bin" "$scratch/cache"

# Scratch source: home/ minus the externals file (see header).
cp -a "$repo/home/." "$src/"
rm -f "$src/.chezmoiexternal.toml"

# Secret-manager stubs. A template that reads a Bitwarden note gets a
# placeholder; nothing else may reach a real secret manager.
cat > "$scratch/bin/bw" << 'EOF'
#!/bin/sh
# Stub for `bw get item <name>`: a Secure Note with placeholder contents.
printf '{"name":"ci-stub","notes":"ci-stub-note","login":{"username":"ci","password":"ci-stub"}}\n'
EOF
cat > "$scratch/bin/op" << 'EOF'
#!/bin/sh
echo "lint-chezmoi-templates: a template called the 1Password CLI, which is not allowed under the CI config" >&2
exit 1
EOF
chmod +x "$scratch/bin/bw" "$scratch/bin/op"
export PATH="$scratch/bin:$PATH"

cm() {
	chezmoi --source "$src" --config "$config" --destination "$dest" \
		--cache "$scratch/cache" --persistent-state "$scratch/state.boltdb" \
		--no-tty --color=false "$@"
}

fail=0
failures=()
record_failure() { # message
	failures+=("$1")
	fail=1
}

echo "chezmoi template lint: profile=$profile config=${config#"$repo"/}"

# Managed targets: files (rendered content) and run_* scripts (what chezmoi
# would execute). Absolute paths under $dest, which chezmoi cat accepts.
if ! managed=$(cm managed --include=files,scripts --path-style=absolute); then
	echo "error: 'chezmoi managed' failed (see above)" >&2
	exit 1
fi
targets=()
while IFS= read -r line; do
	if [[ -n "$line" ]]; then targets+=("$line"); fi
done <<< "$managed"

if ((${#targets[@]} == 0)); then
	echo "error: 'chezmoi managed' returned no targets; refusing to pass on an empty set" >&2
	exit 1
fi
echo "managed targets: ${#targets[@]}"

# 1. Every managed target renders without a template error.
i=0
rendered=() # rendered[i] is the file holding target i's output, or "" if it failed
for target in "${targets[@]}"; do
	f="$out/$i"
	if cm cat "$target" > "$f" 2> "$f.err"; then
		rendered+=("$f")
	else
		rendered+=("")
		record_failure "TEMPLATE RENDER FAILED: ${target#"$dest"/}"
		sed 's/^/    /' "$f.err" >&2
	fi
	i=$((i + 1))
done

# The externals file is templated even without a .tmpl suffix, and is the one
# source file the loop above cannot see: render it and check that it is TOML.
if ! cm execute-template < "$repo/home/.chezmoiexternal.toml" > "$out/external.toml" 2> "$out/external.err"; then
	record_failure "TEMPLATE RENDER FAILED: .chezmoiexternal.toml"
	sed 's/^/    /' "$out/external.err" >&2
elif ! cm execute-template "{{ \$_ := fromToml (include \"$out/external.toml\") }}" > /dev/null 2> "$out/external.err"; then
	record_failure "RENDERED TOML INVALID: .chezmoiexternal.toml"
	sed 's/^/    /' "$out/external.err" >&2
fi

# Classify a rendered file: prints bash, sh or zsh, or nothing for other files.
# By shebang first, then by name (zsh dotfiles, *.zsh, and shebang-less *.sh
# libraries that are sourced by bash scripts).
dialect_of() { # rendered-file target
	local first words interp
	first=$(head -n 1 "$1" || true)
	if [[ "$first" == '#!'* ]]; then
		read -ra words <<< "${first#'#!'}"
		interp=${words[0]:-}
		if [[ "${interp##*/}" == env ]]; then
			interp=""
			for w in "${words[@]:1}"; do
				[[ "$w" == -* ]] && continue
				interp=$w
				break
			done
		fi
		case "${interp##*/}" in
			bash) echo bash ;;
			sh | dash) echo sh ;;
			zsh) echo zsh ;;
		esac
		return
	fi
	case "${2##*/}" in
		.zshrc | .zshenv | .zprofile | .zlogin | .zlogout | *.zsh) echo zsh ;;
		*.sh | *.bash) echo bash ;;
	esac
}

# Per-script shellcheck exclusions, for rules that cannot be disabled in the template.
# chezmoi runs a run_once_* script again whenever its rendered content changes,
# so even a comment added to one would re-run it on every machine (run_once_05
# restarts Finder and Dock). Keep those templates byte-identical and exclude the
# rule here instead, per script, with the reason.
shellcheck_excludes_for() { # target-relative-name
	case "$1" in
		# $VENV_DIR is unquoted inside two echo command substitutions.
		03-setup-python-venv.sh) echo SC2086 ;;
		# Off macOS the template renders `exit 0` first, so the rest is unreachable
		# by design; on macOS the rendered script has no such exit.
		05-macos-defaults.sh) echo SC2317 ;;
	esac
}

# 2. Every rendered shell script parses; 3. bash/sh scripts also shellcheck.
checked=0
i=0
for target in "${targets[@]}"; do
	f=${rendered[$i]}
	i=$((i + 1))
	[[ -n "$f" ]] || continue # already reported as a render failure
	dialect=$(dialect_of "$f" "$target")
	[[ -n "$dialect" ]] || continue
	name=${target#"$dest"/}
	checked=$((checked + 1))

	case "$dialect" in
		bash) syntax=(bash -n) ;;
		sh) syntax=(sh -n) ;;
		zsh) syntax=(zsh -n) ;;
	esac
	if ! "${syntax[@]}" < "$f" 2> "$f.syn"; then
		record_failure "SYNTAX CHECK FAILED (${syntax[*]}): $name"
		sed 's/^/    /' "$f.syn" >&2
	fi

	if [[ "$dialect" != zsh ]]; then
		# zsh has no shellcheck dialect. Stdin plus an explicit rcfile keeps the
		# result independent of the working directory.
		sc_args=(--rcfile "$repo/.shellcheckrc" -s "$dialect")
		excludes=$(shellcheck_excludes_for "$name")
		[[ -z "$excludes" ]] || sc_args+=(--exclude="$excludes")
		if ! shellcheck "${sc_args[@]}" - < "$f" > "$f.sc" 2>&1; then
			record_failure "SHELLCHECK FAILED (-s $dialect): $name"
			sed 's/^/    /' "$f.sc" >&2
		fi
	fi
done

echo "shell scripts checked: $checked"
if ((checked == 0)); then
	record_failure "no shell scripts were recognised among ${#targets[@]} targets; classification is broken"
fi

if ((fail)); then
	echo >&2
	echo "chezmoi template lint FAILED (${#failures[@]}):" >&2
	printf '  %s\n' "${failures[@]}" >&2
	exit 1
fi
echo "chezmoi template lint passed"

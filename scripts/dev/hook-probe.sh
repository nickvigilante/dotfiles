#!/usr/bin/env bash
# Re-check, after a Claude Code upgrade, the undocumented hook behavior the
# permission prefilter relies on:
#   1. global PreToolUse hooks also fire for subagent tool calls
#   2. subagent calls carry agent_type; main-session calls do not
#   3. hooks in an agent's frontmatter fire only inside that agent
# Runs one throwaway headless session on Haiku that may only run `echo`.
# Everything it writes stays in a temporary directory.
set -euo pipefail

for tool in claude jq; do
	command -v "$tool" > /dev/null || {
		echo "error: $tool not on PATH" >&2
		exit 2
	}
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
log="$work/hooklog.jsonl"

cat > "$work/log.sh" << EOF
#!/bin/sh
# Append this hook's stdin JSON, tagged with which hook fired. Emits no decision.
printf '{"tag":"%s","input":%s}\n' "\$1" "\$(cat)" >> "$log"
EOF
chmod +x "$work/log.sh"

hook() { jq -nc --arg cmd "$work/log.sh $1" '{PreToolUse: [{matcher: "Bash", hooks: [{type: "command", command: $cmd}]}]}'; }
jq -n --argjson hooks "$(hook global)" '{hooks: $hooks}' > "$work/settings.json"
agents="$(jq -nc --argjson hooks "$(hook agent-scoped)" '{"probe-agent": {
	description: "Runs exactly one bash command it is given.",
	prompt: "Run exactly the bash command you are given with the Bash tool, then reply done.",
	tools: ["Bash"], hooks: $hooks}}')"

mkdir "$work/cwd"
(cd "$work/cwd" && claude -p \
	"Step 1: run the bash command 'echo main-probe'. Step 2: use the Agent tool with subagent_type probe-agent and ask it to run the bash command 'echo sub-probe'. Then reply done." \
	--settings "$work/settings.json" --agents "$agents" --model haiku \
	--allowedTools "Bash(echo *)" "Agent" < /dev/null > /dev/null)

failed=0
check() {
	if jq -se "$2" "$log" > /dev/null; then
		echo "PASS  $1"
	else
		echo "FAIL  $1"
		failed=1
	fi
}
main='.input.tool_input.command == "echo main-probe"'
sub='.input.tool_input.command == "echo sub-probe"'
check "global hook fires in the main session" "any(.[]; .tag == \"global\" and $main)"
check "main-session calls have no agent_type" "all(.[] | select($main); .input.agent_type == null)"
check "global hook fires inside the subagent" "any(.[]; .tag == \"global\" and $sub)"
check "subagent calls carry agent_type" "any(.[] | select($sub); true) and all(.[] | select($sub); .input.agent_type == \"probe-agent\")"
check "agent-scoped hook fires only in its agent" "any(.[]; .tag == \"agent-scoped\") and all(.[] | select(.tag == \"agent-scoped\"); $sub)"
exit "$failed"

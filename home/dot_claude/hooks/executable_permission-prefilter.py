#!/usr/bin/env python3
"""Claude Code PreToolUse hook for Bash: the runtime half of the permission policy.

The static allowlist in settings.json can only match command prefixes. This
hook checks what prefixes can't, using permission_policy.decide():

  - deny forbidden flags (deny_flags) and environment overrides (env_allow)
    on allowlisted commands, in every form: plain, `rtk`, `chezmoi git`
  - ask when a guarded command can't be parsed safely
  - allow `cargo test|clippy|build|run|check` in a trusted dev root, piped
    only into read-only filters
  - add --skip-secrets to `chezmoi cat|diff|status|verify`
  - route curl: denied everywhere except the curl-runner agent, where local
    read-only requests are allowed

It prints at most one JSON object. With no decision, Claude Code's normal
permission flow (the static allowlist, then a prompt) runs as usual.
"""

import json
import os
import sys

sys.dont_write_bytecode = True
HOOK_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HOOK_DIR)

from permission_policy import decide  # noqa: E402

POLICY_PATH = os.path.join(HOOK_DIR, "permission-policy.json")


def load_policy():
    try:
        with open(POLICY_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return
    tool_input = data.get("tool_input") or {}
    command = tool_input.get("command") or ""
    if not command:
        return
    decision = decide(command, data.get("cwd") or os.getcwd(), data.get("agent_type"), load_policy())
    output = {"hookEventName": "PreToolUse"}
    if decision.permission:
        output["permissionDecision"] = decision.permission
    if decision.reason:
        output["permissionDecisionReason"] = decision.reason
    if decision.updated_command is not None:
        output["updatedInput"] = dict(tool_input, command=decision.updated_command)
    if len(output) > 1:
        print(json.dumps({"hookSpecificOutput": output}))


if __name__ == "__main__":
    main()

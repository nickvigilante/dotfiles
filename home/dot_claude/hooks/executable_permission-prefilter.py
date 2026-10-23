#!/usr/bin/env python3
"""Claude Code PreToolUse hook for Bash: the runtime half of the permission policy.

The static allowlist in settings.json can only match command prefixes. This
hook checks what prefixes can't, using permission_policy.decide():

  - deny forbidden flags (deny_flags) and environment overrides (env_allow)
    on allowlisted commands, in every form: plain, `rtk`, `chezmoi git`
  - ask when a guarded command can't be parsed safely
  - ask for forms that destroy work (ask_flags, ask_args): force pushes,
    `git reset --hard`, `rm -rf`, `chezmoi apply`, `gh pr merge`
  - split `&&` / `||` / `;` lists and decide each piece where it runs,
    following `cd`; ask for a guarded piece after one that changes the shell
  - ask before an allowlisted git command runs in a repo whose local config
    or hooks would run a program, and before allowlisted cargo reads run
    outside a trusted dev root
  - allow `cargo test|clippy|build|run|check` in a trusted dev root, piped
    only into read-only filters
  - add --skip-secrets to `chezmoi cat|diff|status|verify`
  - route curl: denied everywhere except the curl-runner agent, where local
    read-only requests are allowed

It also runs `rtk hook claude` on its own (possibly rewritten) command and
merges the two answers, so it is the only PreToolUse Bash hook. Claude Code
runs matching hooks in parallel and does not say whose updatedInput wins
(https://code.claude.com/docs/en/hooks: "All matching hooks run in
parallel"; updatedInput "Replaces the entire input object"), so a separate
rtk hook could replace `git pull --no-rebase ... --ff-only` with its own
rewrite of the original command while this hook's allow still applied.

It prints at most one JSON object. With no decision, Claude Code's normal
permission flow (the static allowlist, then a prompt) runs as usual.
"""

import json
import os
import shutil
import subprocess
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


_RANK = {None: 0, "allow": 1, "ask": 2, "defer": 3, "deny": 4}


def run_rtk(data, command):
    """The hookSpecificOutput of `rtk hook claude` for `command`, or None."""
    rtk = shutil.which("rtk")
    if not rtk:
        return None
    payload = dict(data, tool_input=dict(data.get("tool_input") or {}, command=command))
    try:
        done = subprocess.run([rtk, "hook", "claude"], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode == 2:
        reason = done.stderr.strip() or "rtk blocked this command."
        return {"permissionDecision": "deny", "permissionDecisionReason": reason}
    try:
        spec = json.loads(done.stdout).get("hookSpecificOutput") if done.stdout.strip() else None
    except (ValueError, AttributeError):
        return None
    return spec if isinstance(spec, dict) else None


def only_adds_rtk(rewritten, command):
    """True if `rewritten` is `command` with `rtk` words inserted, so every
    flag this hook added survived rtk's rewrite."""
    def strip(text):
        return [w for w in text.split(" ") if w != "rtk"]
    return strip(rewritten) == strip(command)


def merge(tool_input, command, decision, rtk):
    """One answer from this hook's decision and rtk's output."""
    permission, reasons = decision.permission, [decision.reason]
    final = decision.updated_command or command
    rtk = rtk or {}
    rtk_permission = rtk.get("permissionDecision")
    rtk_command = (rtk.get("updatedInput") or {}).get("command")
    usable = isinstance(rtk_command, str) and (
        decision.updated_command is None or only_adds_rtk(rtk_command, final)
    )
    if usable:
        final = rtk_command
    if rtk_permission in _RANK and (usable or rtk_command is None or rtk_permission == "deny"):
        if _RANK[rtk_permission] > _RANK[permission]:
            permission = rtk_permission
        reasons.append(rtk.get("permissionDecisionReason") or "")
    output = {"hookEventName": "PreToolUse"}
    if permission:
        output["permissionDecision"] = permission
    reason = "; ".join(r for r in reasons if r)
    if reason:
        output["permissionDecisionReason"] = reason
    if final != command and permission != "deny":
        output["updatedInput"] = dict(tool_input, command=final)
    return output


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
    rtk = None
    if decision.permission != "deny":
        rtk = run_rtk(data, decision.updated_command or command)
    output = merge(tool_input, command, decision, rtk)
    if len(output) > 1:
        print(json.dumps({"hookSpecificOutput": output}))


if __name__ == "__main__":
    main()

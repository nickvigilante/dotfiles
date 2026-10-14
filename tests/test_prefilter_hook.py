"""End-to-end tests for the prefilter hook script: stdin JSON in, stdout JSON out."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "home", "dot_claude", "hooks"))


class HookHarness(unittest.TestCase):
    def setUp(self):
        # Deploy the hook the way chezmoi does: plain file names in one directory.
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        for name in ("shellscan.py", "permission_policy.py"):
            shutil.copy(os.path.join(HOOKS, name), self.dir)
        self.hook = os.path.join(self.dir, "permission-prefilter.py")
        shutil.copy(os.path.join(HOOKS, "executable_permission-prefilter.py"), self.hook)

    def write_policy(self, policy):
        with open(os.path.join(self.dir, "permission-policy.json"), "w") as handle:
            json.dump(policy, handle)

    def run_hook(self, payload, path=None):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        # No rtk on PATH unless a test installs the fake one.
        env = dict(os.environ, PATH=path or "/usr/bin:/bin")
        result = subprocess.run([sys.executable, self.hook], input=stdin,
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout else None

    def bash(self, command, **extra):
        return dict({"tool_name": "Bash", "tool_input": {"command": command},
                     "cwd": self.dir}, **extra)


class PrefilterHook(HookHarness):
    def test_no_output_for_other_tools_and_bad_input(self):
        self.write_policy({})
        for payload in ['not json', '[]', {"tool_name": "Read"},
                        {"tool_name": "Bash"}, {"tool_name": "Bash", "tool_input": {"command": None}}]:
            with self.subTest(payload=payload):
                self.assertIsNone(self.run_hook(payload))

    def test_missing_policy_still_routes_curl(self):
        out = self.run_hook(self.bash("curl http://localhost/"))
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("curl-runner", out["permissionDecisionReason"])

    def test_corrupt_policy_treated_as_missing(self):
        with open(os.path.join(self.dir, "permission-policy.json"), "w") as handle:
            handle.write("{")
        self.assertEqual(self.run_hook(self.bash("curl http://localhost/"))["permissionDecision"], "deny")
        self.assertIsNone(self.run_hook(self.bash("cargo test")))

    def test_deny_output_shape(self):
        self.write_policy({"permissions": {"commands": {"rg": {"deny_flags": ["--pre"]}}}})
        out = self.run_hook(self.bash("rg --pre=x foo"))
        self.assertEqual(out["hookEventName"], "PreToolUse")
        self.assertEqual(out["permissionDecision"], "deny")

    def test_updated_input_keeps_other_fields(self):
        self.write_policy({"permissions": {"commands": {"chezmoi": {}}}})
        payload = self.bash("chezmoi diff")
        payload["tool_input"]["description"] = "Show drift"
        out = self.run_hook(payload)
        self.assertNotIn("permissionDecision", out)
        self.assertEqual(out["updatedInput"],
                         {"command": "chezmoi diff --skip-secrets", "description": "Show drift"})

    def test_agent_type_allows_curl_in_curl_runner(self):
        self.write_policy({})
        out = self.run_hook(self.bash("curl -s http://localhost:8080/", agent_type="curl-runner"))
        self.assertEqual(out["permissionDecision"], "allow")

    def test_no_bytecode_written(self):
        self.write_policy({})
        self.run_hook(self.bash("ls"))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "__pycache__")))


FAKE_RTK = """#!%s
import json, os, sys
mode = os.environ.get("FAKE_RTK_MODE", "prefix")
data = json.load(sys.stdin)
with open(os.environ["FAKE_RTK_LOG"], "a") as log:
    log.write(data["tool_input"]["command"] + "\\n")
command = data["tool_input"]["command"]
if mode == "exit2":
    sys.stderr.write("rtk pipeline rule blocked this")
    sys.exit(2)
if mode == "silent":
    sys.exit(0)
if mode == "drop":
    command = command.replace(" --skip-secrets", "")
out = {"hookEventName": "PreToolUse", "permissionDecisionReason": "RTK auto-rewrite",
       "updatedInput": dict(data["tool_input"], command="rtk " + command)}
if mode in ("allow", "ask"):
    out["permissionDecision"] = mode
print(json.dumps({"hookSpecificOutput": out}))
"""


class RtkIsRunByThePrefilter(HookHarness):
    """Claude Code runs matching hooks in parallel and does not define which
    hook's updatedInput wins, so the prefilter runs `rtk hook claude` itself on
    its own rewritten command and returns one merged answer."""

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.dir, "bin")
        os.mkdir(self.bin)
        rtk = os.path.join(self.bin, "rtk")
        with open(rtk, "w") as handle:
            handle.write(FAKE_RTK % sys.executable)
        os.chmod(rtk, 0o755)
        self.log = os.path.join(self.dir, "rtk.log")
        os.environ["FAKE_RTK_LOG"] = self.log
        self.addCleanup(os.environ.pop, "FAKE_RTK_LOG", None)
        self.addCleanup(os.environ.pop, "FAKE_RTK_MODE", None)
        self.write_policy({"permissions": {"commands": {
            "chezmoi": {}, "rg": {"deny_flags": ["--pre"]}}}})

    def run_rtk_hook(self, command, mode="prefix"):
        os.environ["FAKE_RTK_MODE"] = mode
        return self.run_hook(self.bash(command), path=self.bin + ":/usr/bin:/bin")

    def rtk_saw(self):
        with open(self.log) as handle:
            return handle.read().splitlines()

    def test_rtk_rewrites_the_prefilter_command(self):
        out = self.run_rtk_hook("chezmoi diff")
        self.assertEqual(self.rtk_saw(), ["chezmoi diff --skip-secrets"])
        self.assertEqual(out["updatedInput"]["command"], "rtk chezmoi diff --skip-secrets")

    @unittest.skipUnless(os.path.exists("/usr/bin/git"), "needs /usr/bin/git")
    def test_git_pull_keeps_its_safety_flags(self):
        repo = os.path.join(self.dir, "r")
        subprocess.run(["git", "init", "-q", repo], check=True)
        subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                        "https://github.com/coder/coder.git"], check=True)
        self.write_policy({"permissions": {
            "hook": {"approved_git_hosts": ["github.com"], "approved_git_owners": ["coder"]},
            "commands": {"git": {"args": ["status *"]}}}})
        os.environ["FAKE_RTK_MODE"] = "prefix"
        payload = dict(self.bash("git pull --ff-only"), cwd=repo)
        out = self.run_hook(payload, path=self.bin + ":/usr/bin:/bin")
        self.assertEqual(out["permissionDecision"], "allow")
        self.assertEqual(out["updatedInput"]["command"],
                         "rtk git pull --no-rebase --no-recurse-submodules --ff-only")

    def test_rewrite_that_drops_prefilter_flags_is_ignored(self):
        out = self.run_rtk_hook("chezmoi diff", mode="drop")
        self.assertEqual(out["updatedInput"]["command"], "chezmoi diff --skip-secrets")

    def test_rtk_allow_passes_through(self):
        out = self.run_rtk_hook("ls -la", mode="allow")
        self.assertEqual(out["permissionDecision"], "allow")
        self.assertEqual(out["updatedInput"]["command"], "rtk ls -la")

    def test_most_restrictive_decision_wins(self):
        self.assertEqual(self.run_rtk_hook("ls", mode="ask")["permissionDecision"], "ask")
        out = self.run_rtk_hook("rg --pre=x y", mode="allow")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertNotIn("updatedInput", out)

    def test_rtk_exit_2_blocks(self):
        out = self.run_rtk_hook("ls", mode="exit2")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("rtk pipeline rule", out["permissionDecisionReason"])

    def test_silent_rtk_leaves_prefilter_answer(self):
        self.assertIsNone(self.run_rtk_hook("ls", mode="silent"))
        out = self.run_rtk_hook("chezmoi diff", mode="silent")
        self.assertEqual(out["updatedInput"]["command"], "chezmoi diff --skip-secrets")


if __name__ == "__main__":
    unittest.main()

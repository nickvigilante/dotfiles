"""End-to-end tests for the prefilter hook script: stdin JSON in, stdout JSON out."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "home", "dot_claude", "hooks"))


class PrefilterHook(unittest.TestCase):
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

    def run_hook(self, payload):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        result = subprocess.run([sys.executable, self.hook], input=stdin,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout else None

    def bash(self, command, **extra):
        return dict({"tool_name": "Bash", "tool_input": {"command": command},
                     "cwd": self.dir}, **extra)

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


if __name__ == "__main__":
    unittest.main()

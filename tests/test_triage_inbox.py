"""Tests for the triage-inbox wrapper and the triaging-inbox skill's scripts.

The wrapper is the one command the permissions allowlist approves, so these
tests pin what it refuses.
Everything runs offline: HOME points at a temp dir whose skill directory is a
symlink to the repo copy, and no case reaches GitHub.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "home/dot_local/bin/executable_triage-inbox"
SKILL = ROOT / "home/dot_claude/skills/triaging-inbox"
SCRIPTS = SKILL / "scripts"

ONE_THREAD = {
    "threads": [{
        "id": "t1",
        "messages": [{
            "id": "m1", "date": "2026-10-12T10:00:00Z", "sender": "noreply@hotjar.com", "subject": "digest",
            "snippet": "x", "labelIds": ["UNREAD"], "ccRecipients": [],
        }],
    }]
}


class WrapperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        home = Path(cls.tmp.name) / "home"
        (home / ".claude/skills").mkdir(parents=True)
        (home / ".claude/skills/triaging-inbox").symlink_to(SKILL)
        cls.home = home
        cls.threads = Path(cls.tmp.name) / "threads.json"
        cls.threads.write_text(json.dumps(ONE_THREAD))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_wrapper(self, *args, cwd=None):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run(["bash", str(WRAPPER), *args], capture_output=True, text=True, env=env, cwd=cwd)

    def assertRejected(self, *args, cwd=None):
        """The wrapper itself must refuse; Python's argparse also exits 2, so check who spoke."""
        proc = self.run_wrapper(*args, cwd=cwd)
        self.assertEqual(proc.returncode, 2, "%r should be refused, got rc=%s: %s" % (args, proc.returncode, proc.stderr))
        self.assertTrue(
            proc.stderr.startswith("triage-inbox"),
            "%r was refused by something other than the wrapper: %s" % (args, proc.stderr[:120]),
        )

    def test_refuses_anything_but_inbox_and_pr(self):
        self.assertRejected()
        self.assertRejected("python3")
        self.assertRejected("-c", "print(1)")

    def test_inbox_refuses_unknown_and_unsafe_options(self):
        t = str(self.threads)
        self.assertRejected("inbox", "--no-gh")
        self.assertRejected("inbox", "--threads", "/nonexistent")
        self.assertRejected("inbox", "--threads", "--format")
        # An existing file whose name looks like an option must still be refused.
        (Path(self.tmp.name) / "-x").write_text("{}")
        self.assertRejected("inbox", "--threads", "-x", cwd=self.tmp.name)
        self.assertRejected("inbox", "--threads", t, "--format", "xml")
        self.assertRejected("inbox", "--threads", t, "--out-json", "/tmp/x")
        self.assertRejected("inbox", "--threads", t, "--evil")

    def test_pr_refuses_anything_but_plain_references(self):
        for bad in ("notaref", "a/b#1;touch x", "--paginate", "../x/y#1", "./y#1", "x/..#1", "a/b/c#1"):
            self.assertRejected("pr", bad)
        self.assertRejected("pr")
        self.assertRejected("pr", *["a/b#%d" % i for i in range(51)])

    def test_help_succeeds(self):
        proc = self.run_wrapper("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("triage-inbox inbox", proc.stdout)

    def test_inbox_runs_offline_and_writes_nothing(self):
        proc = self.run_wrapper("inbox", "--threads", str(self.threads), "--no-gh")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("INBOX: 1 unread threads", proc.stdout)
        self.assertIn("-> OK", proc.stdout)
        self.assertEqual(list(SCRIPTS.glob("__pycache__")), [], "the wrapper must not write bytecode")

    def test_missing_skill_directory_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as empty:
            env = dict(os.environ, HOME=empty)
            proc = subprocess.run(["bash", str(WRAPPER), "pr", "a/b#1"], capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("run chezmoi apply", proc.stderr)


def load_tests(loader, tests, pattern):
    """Also run the skill's own unit tests, so one CI step covers both."""
    sys.path.insert(0, str(SCRIPTS))
    tests.addTests(loader.discover(str(SCRIPTS), pattern="test_triage.py", top_level_dir=str(SCRIPTS)))
    return tests


if __name__ == "__main__":
    unittest.main()

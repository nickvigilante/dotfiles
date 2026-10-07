"""Render the real permission config with chezmoi and check its invariants
and key decisions. Skipped when chezmoi is not installed."""

import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOOKS = os.path.join(ROOT, "home", "dot_claude", "hooks")
sys.path.insert(0, HOOKS)

from permission_policy import decide  # noqa: E402


def render(relative_path):
    with open(os.path.join(ROOT, relative_path), encoding="utf-8") as handle:
        result = subprocess.run(["chezmoi", "execute-template", "--source", ROOT],
                                stdin=handle, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("chezmoi"), "needs chezmoi")
class RenderedSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = render("home/dot_claude/settings.json.tmpl")
        cls.allow = cls.settings["permissions"]["allow"]
        cls.deny = cls.settings["permissions"]["deny"]

    def test_no_duplicate_rules(self):
        self.assertEqual(len(self.allow), len(set(self.allow)))

    def test_wildcards_only_at_the_end(self):
        # A `*` before the subcommand would also match global options such as
        # `git -c`; so after the first `*`, nothing but `)` may follow.
        for rule in self.allow:
            with self.subTest(rule=rule):
                if "*" in rule:
                    self.assertEqual(rule[rule.index("*"):].strip("*"), ")")

    def test_no_static_curl_rules(self):
        self.assertFalse([r for r in self.allow if r.startswith(("Bash(curl", "Bash(rtk curl"))])

    def test_plain_and_rtk_forms_together(self):
        for tool in ("ls", "rg", "tree", "wc", "diff", "du", "df", "ps", "grep"):
            with self.subTest(tool=tool):
                self.assertIn("Bash(%s *)" % tool, self.allow)
                self.assertIn("Bash(rtk %s *)" % tool, self.allow)
        self.assertIn("Bash(rtk read *)", self.allow)
        self.assertNotIn("Bash(read *)", self.allow)

    def test_branch_delete_denied_in_every_form(self):
        for head in ("git", "rtk git", "chezmoi git"):
            with self.subTest(head=head):
                self.assertIn("Bash(%s branch -D *)" % head, self.deny)


@unittest.skipUnless(shutil.which("chezmoi"), "needs chezmoi")
class RenderedPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = render("home/dot_claude/hooks/permission-policy.json.tmpl")

    def permission(self, command, cwd=ROOT, agent=None):
        return decide(command, cwd, agent, self.policy).permission

    def test_denied(self):
        for command in ["rg --pre=./x foo", "rtk rg --hostname-bin=x foo", "tree -o f",
                        "git log --output=/tmp/x", "chezmoi git -- show --ext-diff",
                        "tree -R -H . -L 1",
                        "chezmoi cat -o ~/.zshrc x", "chezmoi diff --source /tmp/x",
                        "GIT_PAGER=less git log", "RUSTFLAGS=x cargo build",
                        "curl http://localhost/"]:
            with self.subTest(command=command):
                self.assertEqual(self.permission(command), "deny")

    def test_not_denied(self):
        for command in ["rg -n foo src", "git log --oneline -5", "NO_COLOR=1 git diff",
                        "chezmoi diff --source .worktrees/x", "RUST_LOG=debug cargo tree"]:
            with self.subTest(command=command):
                self.assertNotEqual(self.permission(command), "deny")

    def test_working_tree_is_the_repo(self):
        self.assertEqual(os.path.realpath(self.policy["chezmoi_working_tree"]),
                         os.path.realpath(ROOT))


if __name__ == "__main__":
    unittest.main()

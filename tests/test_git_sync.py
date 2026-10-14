"""Tests for the git fetch / pull auto-approval in permission_policy.py."""

import copy
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.join(os.path.dirname(__file__), "..", "home", "dot_claude", "hooks")
sys.path.insert(0, os.path.abspath(HOOKS))

from permission_policy import decide  # noqa: E402

POLICY = {
    "permissions": {
        "hook": {
            "approved_git_hosts": ["github.com"],
            "approved_git_owners": ["nickvigilante", "coder"],
        },
        "commands": {
            "git": {"deny_flags": ["--upload-pack", "--exec", "--output"],
                    "args": ["log *", "diff *", "status *", "ls-remote *", "remote show *"]},
        },
    },
}


def make_repo(root, **remotes):
    subprocess.run(["git", "init", "-q", root], check=True)
    for name, url in remotes.items():
        subprocess.run(["git", "-C", root, "remote", "add", name, url], check=True)
    return root


@unittest.skipUnless(shutil.which("git"), "needs git")
class GitSync(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.counter = 0

    def repo(self, **remotes):
        self.counter += 1
        return make_repo(os.path.join(self._dir.name, "r%d" % self.counter), **remotes)

    def decide(self, command, cwd, policy=POLICY):
        return decide(command, cwd, None, policy)

    def test_fetch_from_approved_remote_is_allowed_and_hardened(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        decision = self.decide("git fetch -q origin main", repo)
        self.assertEqual(decision.permission, "allow")
        self.assertEqual(
            decision.updated_command, "git fetch --no-recurse-submodules -q origin main"
        )

    def test_url_forms(self):
        for url in [
            "https://github.com/nickvigilante/dotfiles",
            "https://user:token@github.com/coder/coder.git",
            "git@github.com:coder/coder.git",
            "ssh://git@github.com/coder/coder.git",
            "https://GitHub.com/Coder/coder",
        ]:
            with self.subTest(url=url):
                repo = self.repo(origin=url)
                self.assertEqual(self.decide("git fetch", repo).permission, "allow")

    def test_unapproved_remote_gets_no_decision(self):
        for url in [
            "https://github.com/evil/coder.git",
            "https://github.com/coder-evil/x",
            "https://github.com.evil.com/coder/x",
            "https://evil.com/github.com/coder/x",
            "https://github.com@evil.com/coder/x",
            "git@evil.com:coder/x.git",
            "https://gitlab.com/coder/x",
            "/some/local/path",
        ]:
            with self.subTest(url=url):
                repo = self.repo(origin=url)
                self.assertIsNone(self.decide("git fetch", repo).permission)

    def test_bare_fetch_checks_every_remote(self):
        repo = self.repo(
            origin="https://github.com/coder/coder.git", other="https://github.com/evil/x"
        )
        self.assertIsNone(self.decide("git fetch", repo).permission)
        self.assertIsNone(self.decide("git fetch --all", repo).permission)
        self.assertEqual(self.decide("git fetch origin", repo).permission, "allow")
        self.assertIsNone(self.decide("git fetch other", repo).permission)

    def test_insteadof_rewrite_is_resolved(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        subprocess.run(
            ["git", "-C", repo, "config", "url.https://evil.com/.insteadOf",
             "https://github.com/coder/"],
            check=True,
        )
        self.assertIsNone(self.decide("git fetch", repo).permission)

    def test_direct_url_argument(self):
        repo = self.repo()
        self.assertEqual(
            self.decide("git fetch https://github.com/coder/coder.git main", repo).permission,
            "allow",
        )
        self.assertIsNone(self.decide("git fetch https://evil.com/x main", repo).permission)

    def test_unknown_remote_name_is_not_approved(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        self.assertIsNone(self.decide("git fetch nosuch", repo).permission)

    def test_not_a_repo_or_no_remotes(self):
        self.assertIsNone(self.decide("git fetch", self._dir.name).permission)
        self.assertIsNone(self.decide("git fetch", self.repo()).permission)

    def test_flags(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        for command in [
            "git fetch --prune --tags --depth=5", "git fetch -qp", "git fetch --dry-run",
            "git fetch origin pull/12/head:pr-12", "git fetch origin main:refs/heads/x",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.decide(command, repo).permission, "allow")
        for command in [
            "git fetch --recurse-submodules", "git fetch -f", "git fetch --force",
            "git fetch origin +main:main", "git fetch --all origin",
            "git fetch origin -- main", "git fetch --depth=x",
            "git fetch origin ../x", "git fetch -u",
        ]:
            with self.subTest(command=command):
                self.assertIsNone(self.decide(command, repo).permission)
        self.assertEqual(self.decide("git fetch --upload-pack=x", repo).permission, "deny")

    def test_pull_needs_ff_only(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        self.assertIsNone(self.decide("git pull", repo).permission)
        self.assertIsNone(self.decide("git pull --rebase", repo).permission)
        self.assertIsNone(self.decide("git pull origin main", repo).permission)
        decision = self.decide("git pull --ff-only origin main", repo)
        self.assertEqual(decision.permission, "allow")
        self.assertEqual(
            decision.updated_command,
            "git pull --no-rebase --no-recurse-submodules --ff-only origin main",
        )
        self.assertIsNone(self.decide("git pull --ff-only origin a:b", repo).permission)

    def test_forced_flags_are_not_duplicated(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        decision = self.decide("git fetch --no-recurse-submodules", repo)
        self.assertEqual(decision.permission, "allow")
        self.assertIsNone(decision.updated_command)

    def test_rtk_prefix_and_filters(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        decision = self.decide("rtk git fetch | tail -3", repo)
        self.assertEqual(decision.permission, "allow")
        self.assertEqual(
            decision.updated_command, "rtk git fetch --no-recurse-submodules | tail -3"
        )
        self.assertIsNone(self.decide("git fetch | sh", repo).permission)

    def test_forms_that_are_never_auto_approved(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        for command in [
            "chezmoi git fetch",
            "FOO=1 git fetch",
            "git -C /tmp fetch",
            "git -c core.sshCommand=x fetch",
            "git fetch > out",
            "git fetch; ls",
            "timeout 5 git fetch",
            "xargs git fetch",
        ]:
            with self.subTest(command=command):
                self.assertNotEqual(self.decide(command, repo).permission, "allow")

    def test_repo_local_config_that_runs_code_blocks_approval(self):
        for key, value in [
            ("core.sshCommand", "evil"), ("core.hooksPath", ".evil"),
            ("core.fsmonitor", "evil"), ("credential.helper", "!evil"),
            ("remote.origin.uploadpack", "evil"), ("remote.origin.vcs", "evil"),
            ("protocol.ext.allow", "always"), ("include.path", "../x"),
            ("filter.lfs.smudge", "evil"), ("http.proxy", "http://evil"),
        ]:
            with self.subTest(key=key):
                repo = self.repo(origin="https://github.com/coder/coder.git")
                subprocess.run(["git", "-C", repo, "config", key, value], check=True)
                self.assertEqual(self.decide("git fetch", repo).permission, "ask")

    def test_harmless_repo_local_config_is_fine(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        subprocess.run(["git", "-C", repo, "config", "user.name", "n"], check=True)
        subprocess.run(["git", "-C", repo, "config", "pull.rebase", "true"], check=True)
        self.assertEqual(self.decide("git fetch", repo).permission, "allow")

    def test_hooks_that_fire_on_fetch_or_pull_block_approval(self):
        for name in ["reference-transaction", "post-merge", "pre-auto-gc"]:
            with self.subTest(hook=name):
                repo = self.repo(origin="https://github.com/coder/coder.git")
                with open(os.path.join(repo, ".git", "hooks", name), "w") as f:
                    f.write("#!/bin/sh\n")
                self.assertEqual(self.decide("git pull --ff-only", repo).permission, "ask")

    def test_unrelated_hooks_do_not_block_approval(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        for name in ["pre-commit", "commit-msg", "pre-push"]:
            with open(os.path.join(repo, ".git", "hooks", name), "w") as f:
                f.write("#!/bin/sh\n")
        self.assertEqual(self.decide("git fetch", repo).permission, "allow")

    def test_needs_configured_owners(self):
        repo = self.repo(origin="https://github.com/coder/coder.git")
        for hook in [{}, {"approved_git_hosts": ["github.com"]},
                     {"approved_git_owners": ["coder"]}]:
            policy = copy.deepcopy(POLICY)
            policy["permissions"]["hook"] = hook
            with self.subTest(hook=hook):
                self.assertIsNone(self.decide("git fetch", repo, policy).permission)



@unittest.skipUnless(shutil.which("git"), "needs git")
class ReadOnlyGitRepoState(unittest.TestCase):
    """Allowlisted read-only git commands also run repo-local config (diff
    drivers, fsmonitor, pagers, credential helpers), so a risky repo asks."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.repo = make_repo(os.path.join(self._dir.name, "r"))

    def permission(self, command, cwd=None, policy=POLICY):
        return decide(command, cwd or self.repo, None, policy).permission

    def config(self, key, value, repo=None):
        subprocess.run(["git", "-C", repo or self.repo, "config", key, value], check=True)

    def test_clean_repo_and_non_repo_get_no_decision(self):
        for command in ["git status", "git log --oneline -3", "rtk git diff | head -5"]:
            with self.subTest(command=command):
                self.assertIsNone(self.permission(command))
        self.assertIsNone(self.permission("git ls-remote https://github.com/coder/coder",
                                          cwd=self._dir.name))

    def test_risky_config_asks(self):
        for key, value in [
            ("core.fsmonitor", "./evil"), ("diff.external", "./evil"),
            ("diff.x.textconv", "./evil"), ("diff.x.command", "./evil"),
            ("core.pager", "./evil"), ("pager.log", "./evil"),
            ("core.sshCommand", "./evil"), ("credential.helper", "!evil"),
            ("filter.x.clean", "./evil"), ("gpg.program", "./evil"),
            ("include.path", "../x"),
        ]:
            with self.subTest(key=key):
                repo = make_repo(os.path.join(self._dir.name, key))
                self.config(key, value, repo)
                for command in ["git status", "rtk git diff", "git log -p",
                                "git remote show origin", "ls | git log"]:
                    self.assertEqual(self.permission(command, cwd=repo), "ask", command)

    def test_unallowlisted_subcommands_are_left_alone(self):
        self.config("core.fsmonitor", "./evil")
        self.assertIsNone(self.permission("git commit -m x"))

    def test_dash_c_dir_is_checked(self):
        self.config("diff.external", "./evil")
        self.assertEqual(self.permission("git -C %s diff" % self.repo, cwd=self._dir.name), "ask")
        self.assertEqual(self.permission("git -C r diff", cwd=self._dir.name), "ask")
        self.assertEqual(
            self.permission("git --git-dir=%s/.git log" % self.repo, cwd=self._dir.name), "ask")

    def test_risky_command_line_config_asks(self):
        self.assertEqual(self.permission("git -c core.pager=./evil log"), "ask")
        self.assertEqual(self.permission("git --exec-path=/tmp/x status"), "ask")
        self.assertIsNone(self.permission("git -c color.ui=never log"))

    def test_chezmoi_git_checks_the_source_repo(self):
        policy = copy.deepcopy(POLICY)
        policy["chezmoi_working_tree"] = self.repo
        self.config("core.fsmonitor", "./evil")
        self.assertEqual(self.permission("chezmoi git status", cwd="/", policy=policy), "ask")
        self.assertEqual(self.permission("chezmoi git -- log", cwd="/", policy=policy), "ask")

    def test_index_hook_asks_but_other_hooks_do_not(self):
        hooks = os.path.join(self.repo, ".git", "hooks")
        for name in ["pre-commit", "post-merge", "post-checkout"]:
            with open(os.path.join(hooks, name), "w") as f:
                f.write("#!/bin/sh\n")
        self.assertIsNone(self.permission("git status"))
        with open(os.path.join(hooks, "post-index-change"), "w") as f:
            f.write("#!/bin/sh\n")
        self.assertEqual(self.permission("git status"), "ask")

    def test_hooks_path_is_followed_not_flagged(self):
        os.makedirs(os.path.join(self.repo, ".husky"))
        self.config("core.hooksPath", ".husky")
        self.assertIsNone(self.permission("git status"))
        with open(os.path.join(self.repo, ".husky", "post-index-change"), "w") as f:
            f.write("#!/bin/sh\n")
        self.assertEqual(self.permission("git status"), "ask")

    def test_submodule_config_is_checked(self):
        module = os.path.join(self.repo, ".git", "modules", "sub")
        subprocess.run(["git", "init", "-q", "--bare", module], check=True)
        self.assertIsNone(self.permission("git status"))
        self.config("core.fsmonitor", "./evil", module)
        self.assertEqual(self.permission("git status"), "ask")


class AbbreviatedFlags(unittest.TestCase):
    """git accepts unambiguous prefixes of long options, so `--upl=x` runs a
    program exactly as `--upload-pack=x` does."""

    POLICY = {"permissions": {"commands": {"git": {"deny_flags": [
        "--upload-pack", "--exec", "--open-files-in-pager", "--output", "-O",
    ]}}}}

    def permission(self, command):
        return decide(command, "/tmp", None, self.POLICY).permission

    def test_abbreviations_are_denied(self):
        for command in [
            "git ls-remote --upload-pack=x .", "git ls-remote --upl=x .",
            "git ls-remote --upload x .", "git grep --open-f=x hi",
            "git grep --open-files-in-pager=x hi", "git grep -O x hi",
            "git log --out=f", "git log --output=f",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.permission(command), "deny")

    def test_other_long_flags_are_not_swept_up(self):
        for command in ["git log --oneline", "git grep --count hi", "git log --stat"]:
            with self.subTest(command=command):
                self.assertIsNone(self.permission(command))


if __name__ == "__main__":
    unittest.main()

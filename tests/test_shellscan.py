"""Tests for home/dot_claude/hooks/shellscan.py."""

import os
import shutil
import subprocess
import sys
import unittest

HOOKS = os.path.join(os.path.dirname(__file__), "..", "home", "dot_claude", "hooks")
sys.path.insert(0, os.path.abspath(HOOKS))

from shellscan import scan  # noqa: E402


class ScanAccepts(unittest.TestCase):
    def test_pipeline_segments(self):
        segments = scan("cargo test 2>&1 | grep -i fail | head -5")
        self.assertEqual([s.argv for s in segments],
                         [["cargo", "test"], ["grep", "-i", "fail"], ["head", "-5"]])
        self.assertEqual(segments[0].redirects, ["2>&1"])

    def test_env_assignment_split_from_argv(self):
        [segment] = scan("RUST_BACKTRACE=1 cargo test")
        self.assertEqual(segment.env, [("RUST_BACKTRACE", "1")])
        self.assertEqual(segment.argv, ["cargo", "test"])

    def test_quoted_assignment_is_an_argument(self):
        [segment] = scan("'FOO=1' cmd")
        self.assertEqual(segment.env, [])
        self.assertEqual(segment.argv, ["FOO=1", "cmd"])

    def test_single_quotes_are_literal(self):
        [segment] = scan("sed -n '$p'")
        self.assertEqual(segment.argv, ["sed", "-n", "$p"])

    def test_double_quote_escapes(self):
        [segment] = scan('grep "a\\"b" "x\\ny" "!="')
        self.assertEqual(segment.argv, ["grep", 'a"b', "x\\ny", "!="])

    def test_word_offsets(self):
        [segment] = scan("chezmoi diff | head")[:1]
        self.assertEqual((segment.words[1].start, segment.words[1].end), (8, 12))

    def test_tilde_at_word_start(self):
        [segment] = scan("ls ~/x ~")
        home = os.path.expanduser("~")
        self.assertEqual(segment.argv, ["ls", home + "/x", home])

    def test_non_ascii_inside_quotes(self):
        [segment] = scan("grep 'é ü' x")
        self.assertEqual(segment.argv, ["grep", "é ü", "x"])


class ScanRejects(unittest.TestCase):
    REJECTED = [
        "a ~user/x", "a x~", "FOO=~/x", "=ls", "a\nb", "a; b", "a && b", "a & b", "a > f", "a < f",
        "a $(b)", "a `b`", 'a "$X"', 'a "`b`"', "a *", "a ?", "a [x]", "a {b}",
        "a || b", "| a", "a |", "a 'x", 'a "x', "a #c", "a \\x", "a !x",
        "cmd <<EOF", "a é", "FOO=1", "", "a 2>/tmp/f", "a 2>&2", "a2>&1",
    ]

    def test_rejected(self):
        for command in self.REJECTED:
            with self.subTest(command=command):
                self.assertIsNone(scan(command))


@unittest.skipUnless(shutil.which("bash") and shutil.which("zsh"), "needs bash and zsh")
class ScanMatchesRealShells(unittest.TestCase):
    """Every accepted command must be read the same way by scan(), bash and zsh."""

    COMMANDS = [
        'grep -n "a\\"b" x',
        "echo 'a$b' \"c\\nd\" e=f",
        "x 'it''s' \"!=\"",
        "FOO=1 cmd a,b:c+d%e@f",
        "echo \"a\\\\b\" '\\n'",
        "printf 'é ü'",
        "sed -n '5,10p'",
        "cargo +nightly test --features a/b -- --nocapture",
        "curl -w '%{http_code}' 'http://localhost:8080/x?a=1'",
        "ls ~/x ~ ~/",
    ]
    SHELLS = (["bash", "--noprofile", "--norc", "-c"], ["zsh", "-f", "-c"])

    def test_shells_agree(self):
        for command in self.COMMANDS:
            [segment] = scan(command)
            expected = ["%s=%s" % pair for pair in segment.env] + segment.argv
            for shell in self.SHELLS:
                with self.subTest(command=command, shell=shell[0]):
                    out = subprocess.run(shell + ["printf '%s\\0' " + command],
                                         capture_output=True, text=True, check=True)
                    self.assertEqual(out.stdout.split("\0")[:-1], expected)


if __name__ == "__main__":
    unittest.main()

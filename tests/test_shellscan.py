"""Tests for home/dot_claude/hooks/shellscan.py."""

import os
import shutil
import subprocess
import sys
import unittest

HOOKS = os.path.join(os.path.dirname(__file__), "..", "home", "dot_claude", "hooks")
sys.path.insert(0, os.path.abspath(HOOKS))

from shellscan import scan, split_list  # noqa: E402


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

    def test_dollar_before_closing_quote_is_literal(self):
        [segment] = scan('grep -c "^AI$" f')
        self.assertEqual(segment.argv, ["grep", "-c", "^AI$", "f"])

    def test_quoted_heredoc_operator(self):
        for command, op in [("git commit -F - <<'EOF'", "<<'EOF'"),
                            ('cat <<-"END_1" | wc -l', '<<-"END_1"')]:
            with self.subTest(command=command):
                segments = scan(command)
                self.assertEqual(segments[0].redirects, [op])
                self.assertTrue(segments[0].heredoc)

    def test_literal_prefix_globs_are_marked(self):
        [segment] = scan("rg x docs/*.md a?c ~/x* '*'")
        self.assertEqual([w.glob for w in segment.words],
                         [False, False, True, True, True, False])


class ScanRejects(unittest.TestCase):
    REJECTED = [
        "a ~user/x", "a x~", "FOO=~/x", "=ls", "a\nb", "a; b", "a && b", "a & b", "a > f", "a < f",
        "a $(b)", "a `b`", 'a "$X"', 'a "`b`"', "a *", "a ?", "a [x]", "a {b}",
        "a || b", "| a", "a |", "a 'x", 'a "x', "a #c", "a \\x", "a !x",
        "cmd <<EOF", "a é", "FOO=1", "", "a 2>/tmp/f", "a 2>&2", "a2>&1",
        "a -x*", "a =x*", "a 'x'*", "FOO=x* cmd", "cmd <<'EOF'x", "cmd <<<'x'",
        "cmd<<'EOF'", 'a "x$y"',
    ]

    def test_rejected(self):
        for command in self.REJECTED:
            with self.subTest(command=command):
                self.assertIsNone(scan(command))


class SplitList(unittest.TestCase):
    def pieces(self, command):
        return [(command[p.start:p.end], p.before, p.after) for p in split_list(command)]

    def test_operators(self):
        self.assertEqual(self.pieces("cd /x && git log | head; rg 'a;b' || ls\nwc"), [
            ("cd /x", "", "&&"), ("git log | head", "&&", ";"), ("rg 'a;b'", ";", "||"),
            ("ls", "||", ";"), ("wc", ";", ""),
        ])

    def test_redirect_ampersands_and_blank_lines(self):
        self.assertEqual(self.pieces("a 2>&1 &> f\n\n  b ;"),
                         [("a 2>&1 &> f", "", ";"), ("b", ";", ";")])

    def test_heredoc_bodies_are_skipped(self):
        command = "git commit -F - <<'EOF'\nfix: a; b && c\n EOF\nEOF\ngit log -1"
        self.assertEqual(self.pieces(command), [
            ("git commit -F - <<'EOF'", "", ";"), ("git log -1", ";", ""),
        ])
        self.assertEqual(self.pieces('cat <<-"X"\nbody\n\t\tX\nls'),
                         [('cat <<-"X"', "", ";"), ("ls", ";", "")])

    def test_line_continuation_and_quoted_separators(self):
        self.assertEqual(self.pieces('a \\\n b "x && y" \\;'),
                         [('a \\\n b "x && y" \\;', "", "")])

    def test_substitutions_are_skipped_whole(self):
        self.assertEqual(self.pieces('a $(b; c "$(d)" \')\' e) && f "$(g; h)"; i'), [
            ('a $(b; c "$(d)" \')\' e)', "", "&&"), ('f "$(g; h)"', "&&", ";"), ("i", ";", ""),
        ])

    REFUSED = [
        "(a)", "{ a; }", "a & b", "a |& b", "a ;; b", "a && && b", "&& a", "a ||",
        "a # c", "a `b`", "a ${b}", "a <(b)", "a $(b", 'a "$(b)', "a $(b `c`)",
        "a $(case x in y) z;; esac)", "a $(cat <<'E'\nx\nE\n)",
        "a <<EOF\nx\nEOF", "a <<'EOF'\nno end", "a <<'EOF' && b\nx\nEOF",
        "a <<'EOF'; b\nx\nEOF", "a 'x", 'a "x',
    ]

    def test_refused(self):
        for command in self.REFUSED:
            with self.subTest(command=command):
                self.assertIsNone(split_list(command))


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
        'grep -c "^AI$" "$" "$"x',
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

    def test_heredoc_bodies_end_where_split_list_ends_them(self):
        near_misses = ["x $HOME `id` $(id) \\$x ${y} 'q' \"d\"", " EOF", "EOF ", "EOF;",
                       "echo INJECTED"]
        for op, last in [("<<'EOF'", "\tEOF"), ('<<"EOF"', "\tEOF"), ("<<-'EOF'", "x")]:
            body = near_misses + [last]
            for terminator in ("EOF", "\t\tEOF") if op.startswith("<<-") else ("EOF",):
                command = "cat %s\n%s\n%s\necho after" % (op, "\n".join(body), terminator)
                pieces = [command[p.start:p.end] for p in split_list(command)]
                self.assertEqual(pieces, ["cat " + op, "echo after"])
                if op.startswith("<<-"):
                    body = [line.lstrip("\t") for line in body]
                for shell in self.SHELLS:
                    with self.subTest(op=op, terminator=terminator, shell=shell[0]):
                        out = subprocess.run(shell + [command], capture_output=True,
                                             text=True, check=True)
                        self.assertEqual(out.stdout, "\n".join(body) + "\nafter\n")


if __name__ == "__main__":
    unittest.main()

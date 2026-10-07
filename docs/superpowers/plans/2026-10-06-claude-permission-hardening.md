# Claude Code permission hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the auto-approval holes the audit found in the generated Bash allowlist and the permission-prefilter hook, without losing the everyday commands they exist for.

**Architecture:** A hand-written shell scanner (`shellscan.py`) feeds a pure decision module (`permission_policy.py`), called by a thin hook script that reads a policy JSON rendered by chezmoi from `permissions.toml`.
The static allowlist keeps doing prefix matching; the hook adds what prefixes cannot express: forbidden flags, environment overrides, the cargo fast-path, chezmoi `--source`/`--skip-secrets`, and curl routing by `agent_type`.

**Tech Stack:** Python 3.9+ standard library only (hook and tests), chezmoi Go templates, TOML, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-06-claude-permission-hardening-design.md`

## Global Constraints

- Hook code must run on Python 3.9 or newer and import only the standard library (Raspberry Pi OS and older distros ship older `python3`).
- The hook prints at most one JSON object and exits 0; with no decision it prints nothing.
- A permission head must never contain a wildcard: after the first `*` in an allow rule, only `)` may follow.
- Work happens in `.worktrees/claude-permission-hardening` on branch `fix/claude-permission-hardening`; never on `main`.
- Commits use Conventional Commits and end with the trailer `Assisted-by: AI`; never name a model or vendor.
- Markdown files use one sentence per line.
- Shell scripts pass `shellcheck` and `shfmt -i 0 -ci -sr`.
- Run every test command from the worktree root.

## Review Focus

- A fresh machine before the first `chezmoi apply` has no `permission-policy.json`, or a corrupt one: the hook must still deny curl and must allow nothing (test in Task 3).
- `--skip-secrets` is spliced into the raw command text, so unusual spacing and quoting must survive unchanged (test in Task 2).
- A symlink inside the repo can point outside it, so `--source` must be checked after resolving symlinks (test in Task 2).
- Non-ASCII text is fine inside quotes and rejected outside them (tests in Task 1).
- The hook checks the original command, but the rtk hook runs a rewritten one; that is safe only while rtk's rewrite is a pure `rtk ` prefix (manual check in Task 6).

---

### Task 1: Shell scanner

**Files:**
- Create: `home/dot_claude/hooks/shellscan.py`
- Test: `tests/test_shellscan.py`
- Modify: `.github/workflows/ci.yml` (lint job, before the `pre-commit` step)

**Interfaces:**
- Produces: `scan(command: str) -> Optional[List[Segment]]`; `Segment.env: List[Tuple[str, str]]`, `Segment.words: List[Word]`, `Segment.redirects: List[str]`, `Segment.argv -> List[str]`; `Word.value`, `Word.start`, `Word.end`, `Word.unquoted_prefix`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_shellscan.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_shellscan -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'shellscan'`.

- [ ] **Step 3: Write the scanner**

Create `home/dot_claude/hooks/shellscan.py` (a plain file name: chezmoi deploys it to `~/.claude/hooks/shellscan.py`, and the hook imports it from there):

```python
"""Conservative shell lexer for the permission prefilter hook.

scan() accepts a small, quote-aware subset of shell syntax and returns None for
anything outside it, so the caller falls back to Claude Code's normal
permission flow. Anything scan() accepts must be read identically by bash and
zsh; tests/test_shellscan.py checks that against both real shells.

Accepted syntax:
  - outside quotes: letters, digits, `_ . / : = , + % @ -`, spaces, tabs, and
    `|` between commands (an `=` may not start a word: zsh expands `=cmd`)
  - a `~` that starts a word and is followed by `/` or the end of the word,
    which both shells expand to $HOME
  - single quotes: anything, taken literally
  - double quotes: anything except `$` and backticks; a backslash escapes
    `$ ` " \\` and newline, and is literal before any other character
  - the whole-word stderr redirects `2>&1` and `2>/dev/null`
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

_UNQUOTED_OK = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:=,+%@-"
)
_DQ_FORBIDDEN = frozenset("$`")
_DQ_ESCAPABLE = frozenset('$`"\\\n')
_WORD_END = frozenset(" \t|")
REDIRECTS = ("2>&1", "2>/dev/null")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


@dataclass
class Word:
    value: str
    start: int
    end: int
    # Leading characters that appeared outside quotes; decides whether
    # `NAME=value` is an environment assignment or a quoted argument.
    unquoted_prefix: str


@dataclass
class Segment:
    env: List[Tuple[str, str]] = field(default_factory=list)
    words: List[Word] = field(default_factory=list)
    redirects: List[str] = field(default_factory=list)

    @property
    def argv(self) -> List[str]:
        return [w.value for w in self.words]


def scan(command: str) -> Optional[List[Segment]]:
    """Split `command` into pipeline segments, or return None if it uses
    any syntax outside the accepted subset."""
    try:
        tokens = _lex(command)
    except ValueError:
        return None
    segments: List[Segment] = []
    current = Segment()
    for kind, token in tokens:
        if kind == "pipe":
            if not current.words:
                return None
            segments.append(current)
            current = Segment()
        elif kind == "redirect":
            if not current.words:
                return None
            current.redirects.append(token)
        elif not current.words and _ASSIGNMENT.match(token.unquoted_prefix):
            name, value = token.value.split("=", 1)
            current.env.append((name, value))
        else:
            current.words.append(token)
    if not current.words:
        return None
    segments.append(current)
    return segments


def _lex(command):
    tokens = []
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c in " \t":
            i += 1
        elif c == "|":
            tokens.append(("pipe", None))
            i += 1
        else:
            redirect = next(
                (
                    r
                    for r in REDIRECTS
                    if command.startswith(r, i)
                    and (i + len(r) == n or command[i + len(r)] in _WORD_END)
                ),
                None,
            )
            if redirect:
                tokens.append(("redirect", redirect))
                i += len(redirect)
            else:
                word, i = _read_word(command, i)
                tokens.append(("word", word))
    return tokens


def _read_word(command, i):
    start, n = i, len(command)
    value, prefix = [], []
    prefix_open = True
    while i < n and command[i] not in _WORD_END:
        c = command[i]
        if c == "'":
            close = command.find("'", i + 1)
            if close < 0:
                raise ValueError("unterminated single quote")
            value.append(command[i + 1 : close])
            prefix_open = False
            i = close + 1
        elif c == '"':
            chunk, i = _read_double_quoted(command, i + 1)
            value.append(chunk)
            prefix_open = False
        elif c == "~" and i == start and (i + 1 == n or command[i + 1] in "/ \t|"):
            value.append(os.path.expanduser("~"))
            if prefix_open:
                prefix.append(c)
            i += 1
        elif c in _UNQUOTED_OK:
            if c == "=" and i == start:
                raise ValueError("zsh expands a word starting with =")
            value.append(c)
            if prefix_open:
                prefix.append(c)
            i += 1
        else:
            raise ValueError("character not allowed outside quotes: %r" % c)
    return Word("".join(value), start, i, "".join(prefix)), i


def _read_double_quoted(command, i):
    out, n = [], len(command)
    while i < n:
        c = command[i]
        if c == '"':
            return "".join(out), i + 1
        if c in _DQ_FORBIDDEN:
            raise ValueError("expansion inside double quotes")
        if c == "\\" and i + 1 < n:
            nxt = command[i + 1]
            if nxt != "\n":
                out.append(nxt if nxt in _DQ_ESCAPABLE else c + nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    raise ValueError("unterminated double quote")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_shellscan -v`
Expected: `OK`.
The `ScanMatchesRealShells` test needs `bash` and `zsh`; it is skipped, not failed, where either is missing.

- [ ] **Step 5: Run the tests in CI**

In `.github/workflows/ci.yml`, insert this step in the `lint` job directly above `      - name: pre-commit` (the job already installs Python 3.12, zsh and chezmoi in earlier steps):

```yaml
      # Unit tests for the Claude Code permission hook and its rendered config.
      # The scanner test compares against real bash and zsh, and the config test
      # renders templates with chezmoi; both are installed above.
      - name: Python unit tests
        run: python -m unittest discover -s tests -p 'test_*.py' -v

```

Run: `actionlint .github/workflows/ci.yml` (or `pre-commit run actionlint --all-files`)
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add home/dot_claude/hooks/shellscan.py tests/test_shellscan.py .github/workflows/ci.yml
git commit -m "feat(claude): add a conservative shell scanner for the permission hook" -m "Assisted-by: AI"
```

---

### Task 2: Decision module

**Files:**
- Create: `home/dot_claude/hooks/permission_policy.py`
- Test: `tests/test_permission_policy.py`

**Interfaces:**
- Consumes: `scan`, `Segment` from Task 1.
- Produces: `decide(command: str, cwd: str, agent_type: Optional[str], policy: Dict) -> Decision`; `Decision.permission: Optional[str]` (`"allow"`, `"deny"`, `"ask"` or `None`), `Decision.reason: str`, `Decision.updated_command: Optional[str]`; constant `CURL_AGENT = "curl-runner"`.
  The policy shape is `{"permissions": {...the [permissions] TOML table...}, "chezmoi_working_tree": "<path>"}`.

The module has five sections a reviewer can judge separately: shared helpers, pipeline filters, the cargo fast-path, chezmoi, and curl-runner.

- [ ] **Step 1: Write the failing test**

Create `tests/test_permission_policy.py`:

```python
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
            "tree": {"deny_flags": ["-o"]},
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


class MissingPolicy(unittest.TestCase):
    def test_empty_policy_never_allows_but_still_routes_curl(self):
        self.assertIsNone(permission("cargo test", policy={}))
        self.assertEqual(permission("curl http://localhost/", policy={}), "deny")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_permission_policy -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'permission_policy'`.

- [ ] **Step 3: Write the decision module**

Create `home/dot_claude/hooks/permission_policy.py`:

```python
"""Decision logic for the permission prefilter hook.

decide() is pure: it takes the Bash command, the session cwd, the hook's
`agent_type` field (absent in the main session) and the policy, and returns a
Decision. The policy is rendered by chezmoi from home/.chezmoidata/permissions.toml
into ~/.claude/hooks/permission-policy.json:

    {"permissions": {...the [permissions] table...},
     "chezmoi_working_tree": "/path/to/dotfiles"}

Per-command keys read from permissions.commands.<name>:
    deny_flags  flags that block the command outright
    ask_flags   flags that force a manual approval
    env_allow   NAME -> regex; any other VAR= prefix blocks the command
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from shellscan import Segment, scan

CURL_AGENT = "curl-runner"
ROUTE_TO_CURL_AGENT = (
    "curl is only allowed inside the curl-runner agent. "
    "Use the Agent tool with subagent_type curl-runner for HTTP requests."
)
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_ANY = r"(?s).*"
_NUMBER = r"\d+"


@dataclass
class Decision:
    permission: Optional[str] = None  # "allow", "deny", "ask", or None
    reason: str = ""
    updated_command: Optional[str] = None


def decide(
    command: str, cwd: str, agent_type: Optional[str], policy: Dict
) -> Decision:
    segments = scan(command)
    crude = _crude_head(command)
    heads = [_normalize(s.argv)[0] for s in segments] if segments else []
    is_curl = os.path.basename(crude) == "curl" or any(
        os.path.basename(h) == "curl" for h in heads
    )

    if agent_type == CURL_AGENT:
        return _decide_curl_agent(segments, heads, crude)
    if is_curl:
        return Decision("deny", ROUTE_TO_CURL_AGENT)

    if segments is None:
        if crude in _guarded_heads(policy):
            # A rough whitespace split can still spot a forbidden flag, and
            # erring toward deny is safe; otherwise ask, since hidden syntax
            # could smuggle one past the check.
            rough = [w.strip("'\"") for w in command.split()]
            table = _commands(policy).get(crude, {})
            flag = _has_flag(rough, table.get("deny_flags", []))
            if flag:
                return Decision("deny", "%s %s is blocked." % (crude, flag))
            return Decision(
                "ask",
                "Could not parse this %s command safely, so its flags "
                "cannot be checked." % crude,
            )
        return Decision()

    for segment in segments:
        decision = _check_segment(segment, cwd, policy)
        if decision.permission:
            return decision

    if heads[0] == "cargo":
        return _decide_cargo(segments, cwd, policy)
    if heads[0] == "chezmoi":
        return _chezmoi_skip_secrets(command, segments[0])
    return Decision()


# --- shared helpers -----------------------------------------------------------


def _normalize(argv: List[str]):
    """Return (head, args, rtk) with a leading `rtk` removed and
    `chezmoi git [--]` mapped to `git`."""
    rtk = bool(argv) and argv[0] == "rtk"
    if rtk:
        argv = argv[1:]
    if len(argv) >= 2 and argv[0] == "chezmoi" and argv[1] == "git":
        args = argv[2:]
        if args and args[0] == "--":
            args = args[1:]
        return "git", args, rtk
    return (argv[0] if argv else ""), argv[1:], rtk


def _crude_head(command: str) -> str:
    """First command word by whitespace split. Only used when scan() fails,
    so it errs toward recognizing the command."""
    words = command.split()
    while words and _ASSIGNMENT.match(words[0]):
        words.pop(0)
    if words and words[0] == "rtk":
        words.pop(0)
    if not words:
        return ""
    if words[0] == "chezmoi" and len(words) > 1 and words[1] == "git":
        return "git"
    return words[0].strip("'\"")


def _commands(policy: Dict) -> Dict:
    return policy.get("permissions", {}).get("commands", {})


def _guarded_heads(policy: Dict) -> set:
    guarded = {"cargo", "chezmoi", "git"}
    for name, table in _commands(policy).items():
        if table.get("deny_flags") or table.get("ask_flags"):
            guarded.add(name)
    return guarded


def _has_flag(args: List[str], flags: List[str]) -> Optional[str]:
    """Return the first of `flags` present in `args`. Long flags match
    `--flag` and `--flag=value`; a one-letter flag like `-o` also matches
    inside a cluster such as `-ao` or `-ofile`."""
    for arg in args:
        for flag in flags:
            if flag.startswith("--"):
                if arg == flag or arg.startswith(flag + "="):
                    return flag
            elif len(flag) == 2 and flag.startswith("-"):
                if arg.startswith("-") and not arg.startswith("--") and flag[1] in arg[1:]:
                    return flag
            elif arg == flag:
                return flag
    return None


def _check_segment(segment: Segment, cwd: str, policy: Dict) -> Decision:
    head, args, _ = _normalize(segment.argv)
    table = _commands(policy).get(head)
    if table is None:
        return Decision()
    env_allow = table.get("env_allow", {})
    for name, value in segment.env:
        pattern = env_allow.get(name)
        if pattern is None or not re.fullmatch(pattern, value):
            return Decision(
                "deny", "%s= is not an allowed environment override for %s." % (name, head)
            )
    flag = _has_flag(args, table.get("deny_flags", []))
    if flag:
        return Decision(
            "deny",
            "%s %s is blocked: it can run programs, write files, or read "
            "files it should not." % (head, flag),
        )
    flag = _has_flag(args, table.get("ask_flags", []))
    if flag:
        return Decision("ask", "%s %s needs a manual approval." % (head, flag))
    if head == "chezmoi":
        return _check_chezmoi_source(args, cwd, policy)
    return Decision()


def _opts_ok(args, bool_flags, value_flags, max_positionals) -> bool:
    """True if every arg is an allowed flag, a flag value matching its
    regex, or one of at most `max_positionals` positional arguments."""
    positionals, i = 0, 0
    while i < len(args):
        arg = args[i]
        if arg in bool_flags:
            i += 1
        elif arg in value_flags:
            if i + 1 >= len(args) or not re.fullmatch(value_flags[arg], args[i + 1]):
                return False
            i += 2
        elif arg.startswith("--") and "=" in arg:
            flag, value = arg.split("=", 1)
            if flag not in value_flags or not re.fullmatch(value_flags[flag], value):
                return False
            i += 1
        elif arg.startswith("-") and len(arg) > 2 and arg[:2] in value_flags:
            if not re.fullmatch(value_flags[arg[:2]], arg[2:]):
                return False
            i += 1
        elif arg.startswith("-") and len(arg) > 1:
            if arg.startswith("--") or not all("-" + ch in bool_flags for ch in arg[1:]):
                return False
            i += 1
        else:
            positionals += 1
            if positionals > max_positionals:
                return False
            i += 1
    return True


# --- pipeline filters (#1) ------------------------------------------------------

_GREP_BOOL = {"-i", "-v", "-n", "-c", "-E", "-F", "-w", "-x", "-o", "-h", "-s", "-q"}
_GREP_VALUE = {
    "-m": _NUMBER, "-A": _NUMBER, "-B": _NUMBER, "-C": _NUMBER,
    "-e": _ANY, "--color": "auto|always|never",
}
_SED_PRINT = re.compile(r"(\d+|\$)(,(\d+|\$))?p")
_JQ_ENV = re.compile(r"\$ENV|\benv\b")


def _grep_ok(args):
    patterns_given = sum(1 for a in args if a == "-e" or a.startswith("-e"))
    return _opts_ok(args, _GREP_BOOL, _GREP_VALUE, 0 if patterns_given else 1)


def _head_tail_ok(args):
    args = [a for a in args if not re.fullmatch(r"-\d+", a)]
    return _opts_ok(args, set(), {"-n": r"[-+]?\d+", "-c": _NUMBER}, 0)


def _sed_ok(args):
    return len(args) == 2 and args[0] == "-n" and bool(_SED_PRINT.fullmatch(args[1]))


def _jq_ok(args):
    filters = [a for a in args if not a.startswith("-")]
    if any(_JQ_ENV.search(f) for f in filters):
        return False
    return _opts_ok(args, {"-r", "-c", "-S", "-e", "-M", "-C", "-j"}, {}, 1)


_FILTERS = {
    "grep": _grep_ok,
    "egrep": _grep_ok,
    "fgrep": _grep_ok,
    "head": _head_tail_ok,
    "tail": _head_tail_ok,
    "wc": lambda a: _opts_ok(a, {"-l", "-w", "-c", "-m"}, {}, 0),
    "sort": lambda a: _opts_ok(
        a, {"-n", "-r", "-u", "-h", "-V", "-f", "-b"},
        {"-k": r"[0-9.,a-zA-Z]+", "-t": r"(?s)."}, 0,
    ),
    "uniq": lambda a: _opts_ok(a, {"-c", "-d", "-u", "-i"}, {}, 0),
    "cut": lambda a: _opts_ok(
        a, set(), {"-d": r"(?s).", "-f": r"[0-9,-]+", "-c": r"[0-9,-]+"}, 0
    ),
    "tr": lambda a: _opts_ok(a, {"-d", "-s", "-c"}, {}, 2),
    "tac": lambda a: not a,
    "rev": lambda a: not a,
    "nl": lambda a: not a,
    "column": lambda a: _opts_ok(a, {"-t"}, {"-s": _ANY}, 0),
    "fold": lambda a: _opts_ok(a, {"-s"}, {"-w": _NUMBER}, 0),
    "jq": _jq_ok,
    "sed": _sed_ok,
}


def _filter_ok(segment: Segment) -> bool:
    if segment.env or segment.redirects:
        return False
    head, args, _ = _normalize(segment.argv)
    check = _FILTERS.get(head)
    return bool(check) and check(args)


# --- cargo fast-path ------------------------------------------------------------

_CARGO_OK_SUBCOMMANDS = {"test", "clippy", "build", "run", "check"}
_TOOLCHAIN = re.compile(
    r"\+(?:(?:stable|beta|nightly)(?:-\d{4}-\d{2}-\d{2})?|1\.\d+(?:\.\d+)?)"
)
_NAME = r"[A-Za-z0-9_-]+"
_CARGO_BOOL = {
    "--release", "--workspace", "--all", "--lib", "--bins", "--tests",
    "--examples", "--benches", "--all-targets", "--all-features",
    "--no-default-features", "--locked", "--offline", "--frozen", "--no-run",
    "--doc", "--keep-going", "--timings", "-q", "-v", "-vv", "--quiet",
    "--verbose",
}
_CARGO_VALUE = {
    "-p": _NAME, "--package": _NAME, "--bin": _NAME, "--example": _NAME,
    "--test": _NAME, "--bench": _NAME, "--exclude": _NAME,
    "-F": r"[A-Za-z0-9_,/-]+", "--features": r"[A-Za-z0-9_,/-]+",
    "--target": r"[a-z0-9_]+(?:-[a-z0-9_]+){1,4}",
    "-j": _NUMBER, "--jobs": _NUMBER,
    "--color": "auto|always|never",
    "--message-format": r"human|short|json|json-diagnostic-[a-z-]+",
}
_CARGO_POSITIONAL = re.compile(r"[A-Za-z0-9_:.-]+")


def _cargo_args_ok(args: List[str]) -> bool:
    if args and _TOOLCHAIN.fullmatch(args[0]):
        args = args[1:]
    if "--" in args:
        args = args[: args.index("--")]
    subcommand, rest, i = None, [], 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            rest.append(arg)
            if arg in _CARGO_VALUE and i + 1 < len(args):
                rest.append(args[i + 1])
                i += 1
        elif subcommand is None:
            subcommand = arg
        elif not _CARGO_POSITIONAL.fullmatch(arg):
            return False
        i += 1
    if subcommand not in _CARGO_OK_SUBCOMMANDS:
        return False
    return _opts_ok(rest, _CARGO_BOOL, _CARGO_VALUE, 0)


def _trusted(cwd: str, policy: Dict) -> bool:
    real = os.path.realpath(cwd)
    roots = policy.get("permissions", {}).get("hook", {}).get("trusted_dev_roots", [])
    for root in roots:
        root = os.path.realpath(os.path.expanduser(root))
        if real == root or real.startswith(root + os.sep):
            return True
    return False


def _decide_cargo(segments: List[Segment], cwd: str, policy: Dict) -> Decision:
    _, args, _ = _normalize(segments[0].argv)
    if not _cargo_args_ok(args):
        return Decision()
    if not all(_filter_ok(s) for s in segments[1:]):
        return Decision()
    if not _trusted(cwd, policy):
        return Decision()
    return Decision("allow", "cargo build/test in a trusted dev root (%s)" % cwd)


# --- chezmoi --------------------------------------------------------------------

_SECRET_RENDERING = {"cat", "diff", "status", "verify"}


def _option_values(args: List[str], long: str, short: str) -> Optional[List[str]]:
    """Values given to an option in any spelling (`--source X`,
    `--source=X`, `-S X`, `-SX`, `-vS X`), or None if one lacks a value."""
    values, i = [], 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            break
        single = arg.startswith("-") and not arg.startswith("--")
        if arg == long or (single and arg.endswith(short)):
            if i + 1 >= len(args):
                return None
            values.append(args[i + 1])
            i += 2
            continue
        if arg.startswith(long + "="):
            values.append(arg[len(long) + 1 :])
        elif single and short in arg[1:]:
            values.append(arg[arg.index(short, 1) + 1 :])
        i += 1
    return values


def _check_chezmoi_source(args: List[str], cwd: str, policy: Dict) -> Decision:
    values = _option_values(args, "--source", "S")
    if values is None:
        return Decision("deny", "chezmoi --source needs a value.")
    root = policy.get("chezmoi_working_tree")
    for value in values:
        path = os.path.realpath(os.path.join(cwd, os.path.expanduser(value)))
        real_root = os.path.realpath(root) if root else None
        if not real_root or not (path == real_root or path.startswith(real_root + os.sep)):
            return Decision(
                "deny", "chezmoi --source is limited to the dotfiles repo and its worktrees."
            )
    return Decision()


def _chezmoi_skip_secrets(command: str, segment: Segment) -> Decision:
    if len(segment.words) < 2 or segment.words[0].value != "chezmoi":
        return Decision()
    sub = segment.words[1]
    if sub.value not in _SECRET_RENDERING or "--skip-secrets" in segment.argv:
        return Decision()
    updated = command[: sub.end] + " --skip-secrets" + command[sub.end :]
    return Decision(
        None,
        "Added --skip-secrets so templates that call a secret manager are not rendered.",
        updated,
    )


# --- curl-runner ----------------------------------------------------------------

_CURL_URL = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?(?:/[A-Za-z0-9._~/?&=%:+,-]*)?"
)
_CURL_BOOL = {
    "-s", "--silent", "-S", "--show-error", "-i", "--include", "-v",
    "--verbose", "-f", "--fail", "--compressed", "-I", "--head",
}
_CURL_METHOD = "GET|HEAD|OPTIONS"
_CURL_TIME = r"\d+(?:\.\d+)?"
_CURL_HEADER = r"(?s)[A-Za-z0-9-]+:.*"
_CURL_WRITE_OUT = r"(?s)[^@].*"
_CURL_VALUE = {
    "-X": _CURL_METHOD, "--request": _CURL_METHOD,
    "-m": _CURL_TIME, "--max-time": _CURL_TIME, "--connect-timeout": _CURL_TIME,
    "-H": _CURL_HEADER, "--header": _CURL_HEADER,
    "-w": _CURL_WRITE_OUT, "--write-out": _CURL_WRITE_OUT,
}


def _curl_ok(args: List[str]) -> bool:
    args = list(args)
    for i in range(len(args) - 1):
        if args[i] == "-o" and args[i + 1] == "/dev/null":
            del args[i : i + 2]
            break
    if sum(1 for a in args if a in ("-X", "--request") or a.startswith("--request=")) > 1:
        return False
    urls = [a for a in args if a.startswith(("http://", "https://"))]
    if len(urls) != 1 or not _CURL_URL.fullmatch(urls[0]):
        return False
    rest = [a for a in args if a != urls[0]]
    return _opts_ok(rest, _CURL_BOOL, _CURL_VALUE, 0)


def _decide_curl_agent(segments, heads, crude) -> Decision:
    if segments is None:
        if os.path.basename(crude) == "curl":
            return Decision()
        return Decision("deny", "curl-runner only runs curl.")
    if heads[0] != "curl":
        return Decision("deny", "curl-runner only runs curl.")
    if not all(_filter_ok(s) for s in segments[1:]):
        return Decision(
            "deny", "curl-runner only runs curl, optionally piped into read-only filters."
        )
    first = segments[0]
    _, args, _ = _normalize(first.argv)
    if first.env or not _curl_ok(args):
        return Decision()
    return Decision("allow", "local read-only curl request in curl-runner")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_permission_policy -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/dot_claude/hooks/permission_policy.py tests/test_permission_policy.py
git commit -m "feat(claude): add permission decision logic for the prefilter hook" -m "Assisted-by: AI"
```

---

### Task 3: Hook script

**Files:**
- Modify (replace the whole file): `home/dot_claude/hooks/executable_permission-prefilter.py`
- Test: `tests/test_prefilter_hook.py`

**Interfaces:**
- Consumes: `decide` from Task 2.
- Produces: the hook reads `~/.claude/hooks/permission-policy.json` (rendered in Task 4) and prints `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision"?, "permissionDecisionReason"?, "updatedInput"?}}` or nothing.
  The `settings.json` hook wiring does not change.

- [ ] **Step 1: Write the failing test**

Create `tests/test_prefilter_hook.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_prefilter_hook -v`
Expected: failures, because the old hook knows neither `agent_type` nor `--skip-secrets` and still auto-approves `python -c`.

- [ ] **Step 3: Replace the hook script**

Replace the entire contents of `home/dot_claude/hooks/executable_permission-prefilter.py` with:

```python
#!/usr/bin/env python3
"""Claude Code PreToolUse hook for Bash: the runtime half of the permission policy.

The static allowlist in settings.json can only match command prefixes. This
hook checks what prefixes can't, using permission_policy.decide():

  - deny forbidden flags (deny_flags) and environment overrides (env_allow)
    on allowlisted commands, in every form: plain, `rtk`, `chezmoi git`
  - ask when a guarded command can't be parsed safely
  - allow `cargo test|clippy|build|run|check` in a trusted dev root, piped
    only into read-only filters
  - add --skip-secrets to `chezmoi cat|diff|status|verify`
  - route curl: denied everywhere except the curl-runner agent, where local
    read-only requests are allowed

It prints at most one JSON object. With no decision, Claude Code's normal
permission flow (the static allowlist, then a prompt) runs as usual.
"""

import json
import os
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
    output = {"hookEventName": "PreToolUse"}
    if decision.permission:
        output["permissionDecision"] = decision.permission
    if decision.reason:
        output["permissionDecisionReason"] = decision.reason
    if decision.updated_command is not None:
        output["updatedInput"] = dict(tool_input, command=decision.updated_command)
    if len(output) > 1:
        print(json.dumps({"hookSpecificOutput": output}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_prefilter_hook -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/dot_claude/hooks/executable_permission-prefilter.py tests/test_prefilter_hook.py
git commit -m "fix(claude): rebuild the permission prefilter on the scanner and policy" -m "Removes the python -c fast-path (tracked in #135) and the name-only pipeline filters." -m "Assisted-by: AI"
```

---

### Task 4: Generated config

**Files:**
- Modify: `home/.chezmoidata/permissions.toml`
- Modify: `home/dot_claude/settings.json.tmpl`
- Create: `home/dot_claude/hooks/permission-policy.json.tmpl`
- Test: `tests/test_permission_config.py`

**Interfaces:**
- Consumes: `decide` from Task 2 (the test runs real decisions against the rendered policy).
- Produces: new per-command TOML keys `deny_flags`, `ask_flags`, `env_allow`, `deny_args`, `rtk_only`; `[permissions.hook] trusted_dev_roots`; an empty `args` entry renders the bare command (`Bash(ls)`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_permission_config.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_permission_config -v`
Expected: failures and errors: curl rules are still present, `chezmoi git branch -D` is missing from `deny`, and `permission-policy.json.tmpl` does not exist yet.

- [ ] **Step 3: Edit `home/.chezmoidata/permissions.toml`**

Make these six edits.

(a) Document the new keys. Replace:

```toml
# A space before `*` is required for Claude Code prefix matching. A bare entry (no
# trailing ` *`) matches that exact invocation only. List ONLY read-only,
# non-mutating, non-exfiltrating subcommands.
```

with:

```toml
# A space before `*` is required for Claude Code prefix matching. A bare entry (no
# trailing ` *`) matches that exact invocation only; an empty string matches the
# bare command. List ONLY read-only, non-mutating, non-exfiltrating subcommands.
#
# Optional per-command keys, enforced at runtime by the permission-prefilter hook
# (home/dot_claude/hooks/) for every head form at once:
#   deny_flags  flags that block the command (`--flag`, `--flag=value`, and a
#               one-letter flag inside a cluster such as `-ao`)
#   ask_flags   flags that force a manual approval instead
#   env_allow   NAME = "regex" for allowed VAR= prefixes; any other prefix blocks
#   deny_args   static deny rules, generated for every head form like args
#   rtk_only    generate only the `rtk <cmd>` head (no plain command exists)
```

(b) rtk rewrites `du`, `df` and `ps`, so add them to `rtk_wraps`. Replace:

```toml
  "rg",
  "wget",
  "wc",
  "ls",
  "tree",
```

with:

```toml
  "rg",
  "wget",
  "wc",
  "ls",
  "tree",
  "du",
  "df",
  "ps",
```

(c) Replace the whole `rtk_only_tools` block:

```toml
# rtk-only coreutils twins: vanilla form is auto-allowed by Claude Code, so only
# Bash(rtk <tool> *) is needed. (du/df/ps retained from prior hand-maintained config.)
rtk_only_tools = [
  "ls",
  "tree",
  "read",
  "grep",
  "rg",
  "wc",
  "diff",
  "du",
  "df",
  "ps",
]
```

with the hook settings table:

```toml
# Settings for the permission-prefilter hook.
[permissions.hook]
# `cargo test|clippy|build|run|check` is auto-approved only under these roots.
trusted_dev_roots = ["~/git/nickvigilante", "~/rust"]
```

(d) Add git's flag rules. Replace:

```toml
[permissions.commands.git]
extra_heads = ["chezmoi git"]
```

with:

```toml
[permissions.commands.git]
extra_heads = ["chezmoi git"]
deny_flags = ["--output", "--ext-diff", "--textconv", "--no-index", "--contents"]
env_allow = { NO_COLOR = "1", GIT_PAGER = "cat" }
deny_args = ["branch -d *", "branch -D *", "branch --delete *"]
```

(e) Add cargo's `env_allow`, the read-only tool tables, and the chezmoi table. Replace:

```toml
[permissions.commands.cargo]
args = ["tree *", "metadata *", "search *"]
```

with:

```toml
[permissions.commands.cargo]
args = ["tree *", "metadata *", "search *"]
env_allow = { RUST_BACKTRACE = "0|1|full", RUST_LOG = "[A-Za-z0-9_=,:.-]+", CARGO_TERM_COLOR = "always|never|auto", NO_COLOR = "1" }

# Read-only tools. rtk rewrites the plain forms (`cat`/`head` become `rtk read`),
# so each needs its plain and rtk heads; deny_flags covers both.
[permissions.commands.ls]
args = ["", "*"]

[permissions.commands.tree]
args = ["", "*"]
deny_flags = ["-o"]

[permissions.commands.read]
rtk_only = true
args = ["*"]

[permissions.commands.grep]
args = ["*"]

[permissions.commands.rg]
args = ["*"]
deny_flags = ["--pre", "--pre-glob", "--hostname-bin"]

[permissions.commands.wc]
args = ["*"]

[permissions.commands.diff]
args = ["*"]

[permissions.commands.du]
args = ["", "*"]

[permissions.commands.df]
args = ["", "*"]

[permissions.commands.ps]
args = ["", "*"]

[permissions.commands.chezmoi]
args = [
  "diff *",
  "status *",
  "data",
  "doctor",
  "verify *",
  "cat *",
  "managed *",
  "unmanaged *",
  "ignored *",
  "target-path *",
  "source-path *",
]
# --source is allowed only inside the dotfiles repo (checked by the hook).
deny_flags = [
  "--config", "-c", "--pager", "--output", "-o", "--persistent-state",
  "--cache", "--refresh-externals", "-R", "--destination", "-D",
  "--override-data-file", "--init", "--working-tree", "-W",
]
env_allow = { NO_COLOR = "1" }
```

(f) Delete the whole `[permissions.commands.curl]` table (its header line and its `args = [ … ]` list) at the end of the file, leaving the file ending with a single newline.

- [ ] **Step 4: Edit `home/dot_claude/settings.json.tmpl`**

(a) Generate heads with `rtk_only` and empty-arg support, and drop the `rtk_only_tools` loop and the hardcoded chezmoi rules (they now come from the `chezmoi` table). Replace:

```text
{{- range $base, $spec := .permissions.commands }}
    {{- $heads := list $base }}
    {{- if has $base $.permissions.rtk_wraps }}{{ $heads = append $heads (printf "rtk %s" $base) }}{{ end }}
    {{- if hasKey $spec "extra_heads" }}{{ range $eh := $spec.extra_heads }}{{ $heads = append $heads $eh }}{{ end }}{{ end }}
    {{- range $head := $heads }}
        {{- range $arg := $spec.args }}
      "Bash({{ $head }} {{ $arg }})",
        {{- end }}
    {{- end }}
{{- end }}
{{- range $tool := .permissions.rtk_only_tools }}
      "Bash(rtk {{ $tool }} *)",
{{- end }}
      "Bash(chezmoi diff *)",
      "Bash(chezmoi status *)",
      "Bash(chezmoi data)",
      "Bash(chezmoi doctor)",
      "Bash(chezmoi verify *)",
      "Bash(chezmoi cat *)",
      "Bash(chezmoi managed *)",
      "Bash(chezmoi unmanaged *)",
      "Bash(chezmoi ignored *)",
      "Bash(chezmoi target-path *)",
      "Bash(chezmoi source-path *)",
```

with:

```text
{{- range $base, $spec := .permissions.commands }}
    {{- $heads := list }}
    {{- if not (hasKey $spec "rtk_only") }}{{ $heads = append $heads $base }}{{ end }}
    {{- if has $base $.permissions.rtk_wraps }}{{ $heads = append $heads (printf "rtk %s" $base) }}{{ end }}
    {{- if hasKey $spec "extra_heads" }}{{ range $eh := $spec.extra_heads }}{{ $heads = append $heads $eh }}{{ end }}{{ end }}
    {{- range $head := $heads }}
        {{- range $arg := $spec.args }}
      "Bash({{ $head }}{{ if $arg }} {{ $arg }}{{ end }})",
        {{- end }}
    {{- end }}
{{- end }}
```

(b) Generate the `deny` list from `deny_args`, so `chezmoi git branch -D` is covered too. Replace:

```text
    "deny": [
      "Bash(git branch -d *)",
      "Bash(git branch -D *)",
      "Bash(git branch --delete *)",
      "Bash(rtk git branch -d *)",
      "Bash(rtk git branch -D *)",
      "Bash(rtk git branch --delete *)"
    ]
```

with:

```text
    "deny": [
{{- $first := true }}
{{- range $base, $spec := .permissions.commands }}
  {{- if hasKey $spec "deny_args" }}
    {{- $heads := list $base }}
    {{- if has $base $.permissions.rtk_wraps }}{{ $heads = append $heads (printf "rtk %s" $base) }}{{ end }}
    {{- if hasKey $spec "extra_heads" }}{{ range $eh := $spec.extra_heads }}{{ $heads = append $heads $eh }}{{ end }}{{ end }}
    {{- range $head := $heads }}
      {{- range $arg := $spec.deny_args }}
        {{- if not $first }},{{ end }}{{ $first = false }}
      "Bash({{ $head }} {{ $arg }})"
      {{- end }}
    {{- end }}
  {{- end }}
{{- end }}
    ]
```

- [ ] **Step 5: Create the policy template**

Create `home/dot_claude/hooks/permission-policy.json.tmpl` with exactly this one line:

```text
{{ dict "permissions" .permissions "chezmoi_working_tree" .chezmoi.workingTree | toPrettyJson }}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v`
Expected: `OK` across all four suites.
Also run: `chezmoi execute-template --source "$PWD" < home/dot_claude/settings.json.tmpl | jq -e . > /dev/null && echo valid`
Expected: `valid`.

- [ ] **Step 7: Commit**

```bash
git add home/.chezmoidata/permissions.toml home/dot_claude/settings.json.tmpl home/dot_claude/hooks/permission-policy.json.tmpl tests/test_permission_config.py
git commit -m "fix(claude): generate rtk parity tables and flag rules from permissions.toml" -m "Replaces rtk_only_tools with command tables, adds deny_flags/env_allow/deny_args, moves the chezmoi read rules into a table, and removes the static curl rules." -m "Assisted-by: AI"
```

---

### Task 5: curl-runner agent, global instructions, and probe script

**Files:**
- Modify (replace the whole file): `home/dot_claude/agents/curl-runner.md`
- Modify: `home/dot_claude/CLAUDE.md` (the `# Claude Code permissions` section, from that heading to the end of the file)
- Create: `scripts/dev/hook-probe.sh` (mode 0755)

**Interfaces:**
- Consumes: the curl rules enforced by the hook from Tasks 2 and 3 (`agent_type == "curl-runner"`).
- Produces: nothing other tasks rely on.

- [ ] **Step 1: Replace the curl-runner agent**

Replace the entire contents of `home/dot_claude/agents/curl-runner.md` with:

```markdown
---
name: curl-runner
description: Runs HTTP requests with curl and returns a trimmed summary. The only place curl may run — the permission prefilter denies curl in the main session and every other agent, with a message pointing here. Local read-only requests (GET/HEAD/OPTIONS to localhost, 127.0.0.1 or [::1]) run without a prompt; anything else asks.
model: haiku
tools: Bash
permissionMode: default
---

You run exactly one `curl` command per request, then return a compact summary of the response.

The permission prefilter hook enforces what you may run, so these rules describe what will succeed rather than what keeps things safe:

- Run only `curl` (or `rtk curl`), optionally piped into a read-only filter such as `jq`, `grep` or `head`.
  Any other command is denied.
- Requests that run without a prompt:
  - one URL on `localhost`, `127.0.0.1` or `[::1]`, over http or https, with any port and path and no user name;
  - method GET (the default), `-X HEAD`, `-X OPTIONS`, or `-I`;
  - flags from `-s -S -i -v -f --compressed -m --connect-timeout -H 'Name: value' -w '<format>'`, plus `-o /dev/null`.
- Quote any URL that contains `?`, `&`, `[` or `]`, for example `'http://localhost:8080/api?page=2'`.
- Anything else — a remote host, POST/PUT/PATCH/DELETE, a request body, `-L`, or writing output to a file — asks for permission.
  That is intended: surface the prompt, and never rewrite the command to avoid it.
- Return the status line, the key response headers, and a trimmed body, not the raw output.
```

- [ ] **Step 2: Update the global instructions**

In `home/dot_claude/CLAUDE.md`, replace everything from the line `# Claude Code permissions` to the end of the file with:

```markdown
# Claude Code permissions

The Bash permission allowlist in `~/.claude/settings.json` is **generated**, not hand-written.
To allow a read-only command, add its subcommand to `home/.chezmoidata/permissions.toml` and `chezmoi apply` — never edit `settings.json` directly (neither the source `.tmpl` nor the live file), and don't reach for the `update-config` skill to do it.
One entry there grants the vanilla, `rtk`, and (for git) `chezmoi git` forms together.
A head must never contain a wildcard: a `*` before the subcommand also matches global options such as `git -c` and `--exec-path`, which run arbitrary commands.
Flags that run programs, write files or read secrets go in that command's `deny_flags`, and allowed `VAR=` prefixes go in its `env_allow`; the `permission-prefilter.py` hook enforces both for every form of the command.
The same hook approves `cargo` builds in trusted directories, and `python3 -c` always prompts (rebuilding that fast-path is issue #135).
Run HTTP requests through the `curl-runner` agent: the hook denies `curl` everywhere else.
See the `chezmoi` skill ("Generated targets") for the full workflow.
```

- [ ] **Step 3: Add the probe script**

Create `scripts/dev/hook-probe.sh`:

```bash
#!/usr/bin/env bash
# Re-check, after a Claude Code upgrade, the undocumented hook behavior the
# permission prefilter relies on:
#   1. global PreToolUse hooks also fire for subagent tool calls
#   2. subagent calls carry agent_type; main-session calls do not
#   3. hooks in an agent's frontmatter fire only inside that agent
# Runs one throwaway headless session on Haiku that may only run `echo`.
# Everything it writes stays in a temporary directory.
set -euo pipefail

for tool in claude jq; do
	command -v "$tool" > /dev/null || {
		echo "error: $tool not on PATH" >&2
		exit 2
	}
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
log="$work/hooklog.jsonl"

cat > "$work/log.sh" << EOF
#!/bin/sh
# Append this hook's stdin JSON, tagged with which hook fired. Emits no decision.
printf '{"tag":"%s","input":%s}\n' "\$1" "\$(cat)" >> "$log"
EOF
chmod +x "$work/log.sh"

hook() { jq -nc --arg cmd "$work/log.sh $1" '{PreToolUse: [{matcher: "Bash", hooks: [{type: "command", command: $cmd}]}]}'; }
jq -n --argjson hooks "$(hook global)" '{hooks: $hooks}' > "$work/settings.json"
agents="$(jq -nc --argjson hooks "$(hook agent-scoped)" '{"probe-agent": {
	description: "Runs exactly one bash command it is given.",
	prompt: "Run exactly the bash command you are given with the Bash tool, then reply done.",
	tools: ["Bash"], hooks: $hooks}}')"

mkdir "$work/cwd"
(cd "$work/cwd" && claude -p \
	"Step 1: run the bash command 'echo main-probe'. Step 2: use the Agent tool with subagent_type probe-agent and ask it to run the bash command 'echo sub-probe'. Then reply done." \
	--settings "$work/settings.json" --agents "$agents" --model haiku \
	--allowedTools "Bash(echo *)" "Agent" < /dev/null > /dev/null)

failed=0
check() {
	if jq -se "$2" "$log" > /dev/null; then
		echo "PASS  $1"
	else
		echo "FAIL  $1"
		failed=1
	fi
}
main='.input.tool_input.command == "echo main-probe"'
sub='.input.tool_input.command == "echo sub-probe"'
check "global hook fires in the main session" "any(.[]; .tag == \"global\" and $main)"
check "main-session calls have no agent_type" "all(.[] | select($main); .input.agent_type == null)"
check "global hook fires inside the subagent" "any(.[]; .tag == \"global\" and $sub)"
check "subagent calls carry agent_type" "any(.[] | select($sub); true) and all(.[] | select($sub); .input.agent_type == \"probe-agent\")"
check "agent-scoped hook fires only in its agent" "any(.[]; .tag == \"agent-scoped\") and all(.[] | select(.tag == \"agent-scoped\"); $sub)"
exit "$failed"
```

Run: `chmod +x scripts/dev/hook-probe.sh && shellcheck scripts/dev/hook-probe.sh && shfmt -i 0 -ci -sr -d scripts/dev/hook-probe.sh`
Expected: no output.

- [ ] **Step 4: Run the probe**

Run: `scripts/dev/hook-probe.sh`
Expected: five `PASS` lines and exit status 0.
It starts one short headless session on Haiku that may only run `echo`.

- [ ] **Step 5: Commit**

```bash
git add home/dot_claude/agents/curl-runner.md home/dot_claude/CLAUDE.md scripts/dev/hook-probe.sh
git commit -m "feat(claude): route curl through curl-runner and add a hook probe script" -m "Assisted-by: AI"
```

---

### Task 6: Verify and open the PR

**Files:**
- No new files.

- [ ] **Step 1: Run every check**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -v && pre-commit run --all-files`
Expected: `OK`, then every hook `Passed`.
If `markdownlint-cli2` cannot start because the local Homebrew `node` is broken, rerun with `SKIP=markdownlint-cli2` and say so in the PR; CI runs it.

- [ ] **Step 2: Check that rtk only adds a prefix**

Run:

```bash
for c in "cargo test | grep x" "rg -n foo" "tree -L 2"; do
  jq -nc --arg c "$c" '{hook_event_name:"PreToolUse",tool_name:"Bash",tool_input:{command:$c}}' |
    rtk hook claude | jq -r '.hookSpecificOutput.updatedInput.command'
done
```

Expected: each command with `rtk ` added in front of its first word and nothing else changed.
If rtk changes anything else, stop and report it: the hook validates the original command.

- [ ] **Step 3: Preview the change to `~/.claude`**

Run: `chezmoi diff --source "$PWD" ~/.claude`
Expected: the new hook files and policy JSON, the rewritten agent and CLAUDE.md section, and an allowlist diff that adds the plain and rtk read-only rules, adds the `chezmoi git branch` deny rules, and removes the curl and `rtk_only_tools` rules.
Do not run `chezmoi apply`; the user applies after reviewing.

- [ ] **Step 4: Open the PR**

Use the `commit-and-pr` skill.
Push the branch and open a PR whose body summarizes the decisions from the spec, lists what was tested, and includes this manual test plan for the user to run after `chezmoi apply`:

1. Start a new session and run `rg --pre=true foo .`: expect a deny that names `--pre`.
2. Run `curl -s http://localhost:1/` in the main session: expect a deny that points to curl-runner; then ask for the same request through curl-runner and expect it to run without a prompt (a connection error is fine).
3. Ask-in-auto-mode test: temporarily add a global PreToolUse hook that returns `ask` for the exact command `echo ask-probe`, start an auto-mode session, run `echo ask-probe`, note whether a prompt appears, then remove the hook.
4. `permissionMode: default` test: ask curl-runner for `curl -s https://example.com` and note whether you are prompted or the auto-mode classifier decides.
5. Run `scripts/dev/hook-probe.sh` after each Claude Code upgrade.

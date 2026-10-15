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
  - `*` and `?` in a word that starts with a letter, digit, `_ . /` or `~`, so
    every match starts with that same text and none can become an option;
    such words are marked `glob` and the caller decides whether to accept them
  - single quotes: anything, taken literally
  - double quotes: anything except `$` and backticks; a backslash escapes
    `$ ` " \\` and newline, and is literal before any other character; a `$`
    right before the closing quote is literal
  - the whole-word stderr redirects `2>&1` and `2>/dev/null`
  - a heredoc whose delimiter is quoted (`<<'EOF'`, `<<-"EOF"`), whose body
    is literal text; scan() sees only the operator, since split_list() keeps
    the body out of the piece it returns

split_list() splits a command list on top-level `&&`, `||`, `;` and newlines.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

_UNQUOTED_OK = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:=,+%@-"
)
_GLOB = frozenset("*?")
_GLOB_LEAD = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./~"
)
_DQ_FORBIDDEN = frozenset("$`")
_DQ_ESCAPABLE = frozenset('$`"\\\n')
_WORD_END = frozenset(" \t|")
REDIRECTS = ("2>&1", "2>/dev/null")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC = re.compile(r"<<(-?)(?:'([A-Za-z0-9_]+)'|\"([A-Za-z0-9_]+)\")(?=[ \t|\n]|$)")


@dataclass
class Word:
    value: str
    start: int
    end: int
    # Leading characters that appeared outside quotes; decides whether
    # `NAME=value` is an environment assignment or a quoted argument.
    unquoted_prefix: str
    glob: bool = False


@dataclass
class Segment:
    env: List[Tuple[str, str]] = field(default_factory=list)
    words: List[Word] = field(default_factory=list)
    redirects: List[str] = field(default_factory=list)

    @property
    def argv(self) -> List[str]:
        return [w.value for w in self.words]

    @property
    def heredoc(self) -> bool:
        return any(r.startswith("<<") for r in self.redirects)


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
            if token.glob:
                return None
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
        elif command.startswith("<<", i):
            heredoc = _HEREDOC.match(command, i)
            if not heredoc:
                raise ValueError("only a heredoc with a quoted delimiter is allowed")
            tokens.append(("redirect", heredoc.group(0)))
            i = heredoc.end()
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
    glob = False
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
        elif c in _GLOB and i > start and command[start] in _GLOB_LEAD:
            glob = True
            value.append(c)
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
    return Word("".join(value), start, i, "".join(prefix), glob), i


def _read_double_quoted(command, i):
    out, n = [], len(command)
    while i < n:
        c = command[i]
        if c == '"':
            return "".join(out), i + 1
        if c == "$" and i + 1 < n and command[i + 1] == '"':
            out.append(c)
            i += 1
            continue
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


# --- command lists --------------------------------------------------------------


@dataclass
class Piece:
    """One command of a list: `command[start:end]`, and the operators around
    it ("" at either end of the list, ";" for `;` and newlines)."""

    start: int
    end: int
    before: str
    after: str


# Outside quotes, these start syntax split_list() does not model: subshells and
# groups, backticks, parameter expansion, comments, and process substitution.
# A comment is refused rather than skipped: zsh without INTERACTIVE_COMMENTS
# runs the text after `#`. A `$(...)` is skipped whole; the piece holding it
# fails scan(), so the caller treats it as unparseable.
_LIST_REFUSED = frozenset("(){}`#")


def split_list(command: str) -> Optional[List[Piece]]:
    """Split `command` on top-level `&&`, `||`, `;` and newlines, or return
    None if it uses syntax this splitter does not model. Heredoc bodies are
    skipped, so no piece contains one. Every piece still goes through scan()."""
    pieces: List[Piece] = []
    start, before, pending = 0, "", []
    i, n = 0, len(command)

    def close(end, op):
        text = command[start:end]
        if text.strip():
            lead = len(text) - len(text.lstrip())
            pieces.append(Piece(start + lead, start + len(text.rstrip()), before, op))
            return True
        # An empty piece next to && or || is a syntax error; skip blank lines.
        return op in (";", "") and before in (";", "")

    while i < n:
        c = command[i]
        if c == "'":
            i = command.find("'", i + 1)
            if i < 0:
                return None
            i += 1
        elif c == '"':
            i = _skip_double_quoted(command, i + 1)
            if i is None:
                return None
        elif c == "\\":
            i += 2
        elif command.startswith("$(", i):
            i = _skip_substitution(command, i + 2)
            if i is None:
                return None
        elif c in _LIST_REFUSED or command.startswith("${", i):
            return None
        elif c == "<" and command.startswith("<<", i) and not command.startswith("<<<", i):
            heredoc = _HEREDOC.match(command, i)
            if not heredoc:
                return None
            pending.append((heredoc.group(2) or heredoc.group(3), bool(heredoc.group(1))))
            i = heredoc.end()
        elif c == "<" and command.startswith("<<<", i):
            i += 3
        elif command.startswith("&&", i) or command.startswith("||", i):
            if pending or not close(i, command[i : i + 2]):
                return None
            before = command[i : i + 2]
            i += 2
            start = i
        elif c == "&":
            # Only part of a redirect such as 2>&1 or &>; a lone & backgrounds.
            if not (i and command[i - 1] == ">") and not command.startswith("&>", i):
                return None
            i += 1
        elif c == "|" and command.startswith("|&", i):
            return None
        elif c == ";":
            if command.startswith(";;", i) or pending or not close(i, ";"):
                return None
            before, i = ";", i + 1
            start = i
        elif c == "\n":
            if not close(i, ";"):
                return None
            i += 1
            for delimiter, strip_tabs in pending:
                i = _skip_heredoc_body(command, i, delimiter, strip_tabs)
                if i is None:
                    return None
            pending = []
            before, start = ";", i
        else:
            i += 1
    if pending or not close(n, ""):
        return None
    return pieces


def _skip_double_quoted(command, i):
    """Index just past the closing quote, or None."""
    n = len(command)
    while i < n:
        c = command[i]
        if c == '"':
            return i + 1
        if c == "`":
            return None
        if command.startswith("$(", i):
            i = _skip_substitution(command, i + 2)
            if i is None:
                return None
            continue
        i += 2 if c == "\\" else 1
    return None


def _skip_substitution(command, i):
    """Index just past the `)` that closes a `$(` whose body starts at `i`,
    or None. Quotes and nested `$(` are followed; a heredoc, a backtick, or
    a `case` (whose patterns end in an unmatched `)`) is refused."""
    n, depth = len(command), 1
    while i < n:
        c = command[i]
        if c == "'":
            i = command.find("'", i + 1)
            if i < 0:
                return None
            i += 1
        elif c == '"':
            i = _skip_double_quoted(command, i + 1)
            if i is None:
                return None
        elif c == "\\":
            i += 2
        elif c == "`" or command.startswith("<<", i) or re.match(r"case\b", command[i:]):
            return None
        elif c == "(":
            depth, i = depth + 1, i + 1
        elif c == ")":
            depth, i = depth - 1, i + 1
            if not depth:
                return i
        else:
            i += 1
    return None


def _skip_heredoc_body(command, i, delimiter, strip_tabs):
    """Index just past the line that ends a heredoc body starting at `i`, or
    None if no line ends it."""
    while i <= len(command):
        end = command.find("\n", i)
        line = command[i:] if end < 0 else command[i:end]
        if (line.lstrip("\t") if strip_tabs else line) == delimiter:
            return len(command) if end < 0 else end + 1
        if end < 0:
            return None
        i = end + 1
    return None

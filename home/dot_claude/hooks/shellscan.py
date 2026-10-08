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

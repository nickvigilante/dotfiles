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
    deny_arg_patterns  regexes; an argument matching one blocks the command
    ask_args    `subcommand [condition ...]` entries that force a manual
                approval; see _asked_arg()
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional

from shellscan import Piece, Segment, scan, split_list

CURL_AGENT = "curl-runner"
ROUTE_TO_CURL_AGENT = (
    "curl is only allowed inside the curl-runner agent. "
    "Use the Agent tool with subagent_type curl-runner for HTTP requests."
)
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# curl as a command word somewhere in a command scan() rejected.
# curl in a command position somewhere in a command scan() rejected: at the
# start, after `; & | ( $( ` or a newline, past VAR= assignments and wrappers
# with their options. A bare mention such as `brew install curl` is not one.
_CURL_WORD = re.compile(
    r"""(?:^|[;&|(`\n])\s*"""
    r"""(?:(?:rtk|sudo|env|exec|nice|nohup|time|timeout|command|builtin|noglob|stdbuf|xargs)"""
    r"""(?:\s+(?:-\S*|\d\S*|[A-Za-z_]\w*=\S*))*\s+"""
    r"""|[A-Za-z_]\w*=\S*\s+)*"""
    r"""['"]?(?:\S*/)?curl\b"""
)
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
    segments = _scan(command, policy)
    crude, rough_args = _rough_split(command)
    heads = [_normalize(s.argv)[0] for s in segments] if segments else []
    is_curl = os.path.basename(crude) == "curl" or any(
        os.path.basename(h) == "curl" for h in heads
    )

    if agent_type == CURL_AGENT:
        return _decide_curl_agent(segments, heads, crude)
    if is_curl or (segments is None and _CURL_WORD.search(command)):
        return Decision("deny", ROUTE_TO_CURL_AGENT)

    if segments is None:
        pieces = split_list(command)
        if pieces is not None:
            return _decide_list(command, pieces, cwd, policy)
    return _decide_one(command, segments, cwd, policy)


def _scan(command: str, policy: Dict) -> Optional[List[Segment]]:
    """scan(), treating a glob as unparseable in a command name, or in the
    arguments of a guarded command whose table does not set `glob_args`: its
    checks read paths and option values that the glob would change."""
    segments = scan(command)
    for segment in segments or []:
        globs = [i for i, w in enumerate(segment.words) if w.glob]
        if not globs:
            continue
        head, _, index = _normalize(segment.argv)
        table = _commands(policy).get(head) or {}
        if globs[0] <= index or (
            head in _guarded_heads(policy) and not table.get("glob_args")
            and not _ask_only(head, table)
        ):
            return None
    return segments


def _decide_one(command: str, segments: Optional[List[Segment]], cwd: str,
                policy: Dict) -> Decision:
    """The decision for one pipeline, or for a command scan() rejected."""
    heads = [_normalize(s.argv)[0] for s in segments] if segments else []
    if segments is None:
        # Check every piece, not just the first: a guarded command later in
        # the pipeline would otherwise be approved by the static allowlist.
        verdict = Decision()
        for piece in [command, *_PIECE_SEPARATORS.split(command)]:
            head, piece_args = _rough_split(piece)
            if head not in _commands(policy) and piece.split()[:1] == ["rtk"]:
                head, piece_args = "rtk", [head, *piece_args]
            if head not in _guarded_heads(policy):
                continue
            # A rough whitespace split can still spot a forbidden flag, and
            # erring toward deny is safe; otherwise ask, since hidden syntax
            # could smuggle one past the check.
            table = _commands(policy).get(head, {})
            if _ask_only(head, table):
                entry = _has_flag(piece_args, table.get("ask_flags", [])) or _asked_arg(
                    head, piece_args, table)
                if entry and not verdict.permission:
                    verdict = Decision("ask", "%s %s needs a manual approval." % (head, entry))
                continue
            flag = _has_flag(piece_args, table.get("deny_flags", []))
            if flag:
                return Decision("deny", "%s %s is blocked." % (head, flag))
            arg = _matching_arg(piece_args, table)
            if arg is not None:
                return Decision("deny", _DENIED_ARG % (head, arg))
            verdict = verdict if verdict.permission else Decision(
                "ask",
                "Could not parse this %s command safely, so its flags "
                "cannot be checked." % head,
            )
        return verdict

    verdict = Decision()
    for segment in segments:
        decision = _check_segment(segment, cwd, policy)
        if decision.permission == "deny":
            return decision
        if decision.permission and not verdict.permission:
            verdict = decision
    if verdict.permission:
        return verdict

    if heads[0] == "cargo":
        return _decide_cargo(segments, cwd, policy)
    if heads[0] == "chezmoi":
        return _chezmoi_skip_secrets(command, segments[0])
    if heads[0] == "git":
        return _decide_git_sync(command, segments, cwd, policy)
    return Decision()


# --- shared helpers -----------------------------------------------------------


# Process wrappers Claude Code strips before matching allow rules, mapped to
# their options that take a separate value. `timeout` also takes a duration.
_WRAPPERS = {
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "nice": {"-n", "--adjustment"},
    "stdbuf": {"-i", "--input", "-o", "--output", "-e", "--error"},
    "nohup": set(),
    "time": set(),
    "command": set(),
    "builtin": set(),
    "noglob": set(),
}


def _normalize(argv: List[str]):
    """Return (head, args, index): the command with a leading `rtk`, the
    process wrappers in _WRAPPERS, and a bare `xargs` removed, the way
    Claude Code removes them before matching allow rules, and with
    `chezmoi git [--]` mapped to `git`. `index` is the head's position."""
    i = 0
    while i < len(argv):
        word = argv[i]
        if word == "rtk":
            i += 1
        elif word == "xargs" and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            i += 1
        elif word in _WRAPPERS:
            if word == "command" and i + 1 < len(argv) and argv[i + 1] in ("-v", "-V"):
                break  # `command -v` looks a name up; it runs nothing
            i += 1
            while i < len(argv) and argv[i].startswith("-"):
                i += 2 if argv[i] in _WRAPPERS[word] else 1
            if word == "timeout":
                i += 1
        else:
            break
    rest = argv[i:]
    if len(rest) >= 2 and rest[0] == "chezmoi" and rest[1] == "git":
        args = rest[2:]
        if args and args[0] == "--":
            args = args[1:]
        return "git", args, i
    return (rest[0] if rest else ""), rest[1:], i


def _through_xargs(argv: List[str]) -> bool:
    """True if the command runs through xargs, which turns piped text into
    arguments nobody checked. Deny checks look through xargs; approvals
    never do."""
    return "xargs" in argv[: _normalize(argv)[2]]


_PIECE_SEPARATORS = re.compile(r"[|;&\n()`]")


def _rough_split(command: str):
    """(head, args) from a whitespace split. Only used when scan() fails, so
    it errs toward recognizing the command."""
    words = [w.strip("'\"") for w in command.split()]
    while words and _ASSIGNMENT.match(words[0]):
        words.pop(0)
    head, args, _ = _normalize(words)
    return head, args


def _commands(policy: Dict) -> Dict:
    return policy.get("permissions", {}).get("commands", {})


def _guarded_heads(policy: Dict) -> set:
    guarded = {"cargo", "chezmoi", "git"}
    for name, table in _commands(policy).items():
        if any(table.get(k) for k in ("deny_flags", "ask_flags", "ask_args",
                                      "deny_arg_patterns", "trusted_roots_only")):
            guarded.add(name)
    return guarded


def _ask_only(head: str, table: Dict) -> bool:
    """True for a table whose only hook keys add prompts (ask_flags,
    ask_args), such as rm's. Its prompts back up the classifier for visible
    destructive forms; unlike deny_flags they are not a parse boundary, so an
    unparseable or globbed command asks only when a matching form shows."""
    if head in ("cargo", "chezmoi", "git"):
        return False
    return not any(table.get(k) for k in ("deny_flags", "deny_arg_patterns",
                                          "trusted_roots_only"))


def _has_flag(args: List[str], flags: List[str]) -> Optional[str]:
    """Return the first of `flags` present in `args`. Long flags match
    `--flag` and `--flag=value`, and also any abbreviation of it such as
    `--upl=x` (git accepts unambiguous prefixes; a prefix that is also another
    option is denied too, which errs safe). A one-letter flag like `-o` also
    matches inside a cluster such as `-ao` or `-ofile`."""
    for arg in args:
        for flag in flags:
            if flag.startswith("--"):
                name = arg.split("=", 1)[0]
                if arg == flag or arg.startswith(flag + "="):
                    return flag
                if len(name) >= 3 and name.startswith("--") and flag.startswith(name):
                    return flag
            elif len(flag) == 2 and flag.startswith("-"):
                if arg.startswith("-") and not arg.startswith("--") and flag[1] in arg[1:]:
                    return flag
            elif arg == flag:
                return flag
    return None


_DENIED_ARG = "%s %r is blocked: it can run code, write files, or read the environment."


def _matching_arg(args: List[str], table: Dict) -> Optional[str]:
    for arg in args:
        if any(re.search(p, arg) for p in table.get("deny_arg_patterns", [])):
            return arg
    return None


def _check_segment(segment: Segment, cwd: str, policy: Dict) -> Decision:
    head, args, index = _normalize(segment.argv)
    table = _commands(policy).get(head)
    if table is None and index and segment.argv[index - 1] == "rtk" and head:
        # rtk's own subcommands (`rtk gain`) live in the `rtk` table.
        head, args, table = "rtk", [head, *args], _commands(policy).get("rtk")
    if table is None:
        return Decision()
    # env_allow protects the static allow rules and the fast paths; a table
    # with neither, such as rm's, only adds prompts and leaves VAR= prefixes
    # to the normal flow.
    env_allow = table.get("env_allow", {})
    checks_env = table.get("args") or not _ask_only(head, table)
    for name, value in segment.env if checks_env else []:
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
    arg = _matching_arg(args, table)
    if arg is not None:
        return Decision("deny", _DENIED_ARG % (head, arg))
    flag = _has_flag(args, table.get("ask_flags", []))
    if flag:
        return Decision("ask", "%s %s needs a manual approval." % (head, flag))
    entry = _asked_arg(head, args, table)
    if entry:
        return Decision("ask", "%s %s can destroy work; it needs a manual approval."
                        % (head, entry))
    if head == "chezmoi":
        return _check_chezmoi_source(args, cwd, policy)
    if table.get("trusted_roots_only"):
        return _check_trusted_root(head, args, table, cwd, policy)
    if head == "git":
        return _check_git_repo_state(segment, args, table, cwd, policy)
    if head == "gitleaks":
        return _check_gitleaks_repo(args, cwd)
    return Decision()


# --- command lists --------------------------------------------------------------

# Builtins that change the shell itself: its directory, variables (PATH,
# GIT_DIR), aliases, functions, options or command lookup. After one of these
# a later piece may run somewhere, or as something, the hook did not check.
# zsh runs the last command of a pipeline in the current shell, so `x | read
# PATH` counts too; every segment is checked.
_STATE_BUILTINS = frozenset({
    ".", "source", "eval", "exec", "cd", "pushd", "popd", "dirs", "export",
    "unset", "set", "setopt", "unsetopt", "shopt", "emulate", "alias", "unalias",
    "typeset", "declare", "local", "readonly", "integer", "float", "functions",
    "hash", "rehash", "enable", "disable", "trap", "autoload", "zmodload", "ulimit",
    "umask", "read", "getopts", "let", "mapfile", "readarray", "vared", "zstyle",
    "zparseopts", "fc", "r",
})


def _is_state_builtin(segment: Segment) -> bool:
    """True for a shell builtin from _STATE_BUILTINS, but not for an rtk
    subcommand of the same name such as `rtk read`."""
    head, _, index = _normalize(segment.argv)
    if segment.argv[0] in _STATE_BUILTINS:
        return True
    return head in _STATE_BUILTINS and "rtk" not in segment.argv[:index]


def _decide_list(command: str, pieces: List[Piece], cwd: str, policy: Dict) -> Decision:
    """Decide each piece of a `&&` / `||` / `;` list on its own, following
    each `cd` so every piece is checked where it will run.

    A guarded piece asks if an earlier piece changed the shell in a way the
    hook cannot follow. The list is allowed only if some piece earned an
    allow (a git fetch/pull or cargo fast path) and every other piece is a
    tracked cd or matches the static allowlist, so the allow never covers a
    command Claude Code would have prompted for."""
    here, known, settles = cwd, True, False
    ask, reasons, edits = None, [], []
    allowed, all_vetted = False, True
    for piece in pieces:
        text = command[piece.start : piece.end]
        if settles and piece.before != "&&":
            # The `&&` chain that held a cd has ended; it may not have run.
            known, settles = False, False
        segments = _scan(text, policy)
        target = _cd_target(segments, here)
        if target is not None:
            here = target
            if "||" in (piece.before, piece.after):
                known = False
            elif piece.before == "&&":
                settles = True
            continue
        if not known and _mentions_guarded(text, policy):
            ask = ask or Decision(
                "ask",
                "An earlier command in this list changes the directory or the shell, "
                "so this command cannot be checked where it runs.",
            )
            continue
        decision = _decide_one(text, segments, here, policy)
        if decision.permission == "deny":
            return decision
        if decision.permission == "ask":
            ask = ask or decision
        if decision.reason:
            reasons.append(decision.reason)
        if decision.updated_command is not None:
            edits.append((piece.start, piece.end, decision.updated_command))
        if decision.permission == "allow":
            allowed = True
        elif not _vetted(segments, policy):
            all_vetted = False
        if segments is None or _changes_shell(segments, here):
            known = False

    updated = None
    if edits:
        updated = command
        for start, end, text in reversed(edits):
            updated = updated[:start] + text + updated[end:]
    if ask:
        return Decision("ask", ask.reason, updated)
    permission = "allow" if allowed and all_vetted else None
    return Decision(permission, "; ".join(reasons), updated)


_DOT_RELATIVE = re.compile(r"\.\.?(?:/|$)")


def _cd_target(segments: Optional[List[Segment]], cwd: str) -> Optional[str]:
    """The directory a plain `cd dir` will move to, if it will succeed, else
    None. Both shells look a relative name up in CDPATH unless it starts
    with `./` or `../`, so other relative names count only without one."""
    if not segments or len(segments) != 1:
        return None
    segment = segments[0]
    # A stderr redirect only hides cd's error, and a missing dir returns None.
    if segment.env or len(segment.words) != 2:
        return None
    cd, path = segment.words
    if cd.value != "cd" or path.glob or path.value.startswith("-"):
        return None
    relative = not path.value.startswith("/")
    if relative and not _DOT_RELATIVE.match(path.value) and os.environ.get("CDPATH"):
        return None
    path = os.path.normpath(os.path.join(cwd, path.value))
    if not os.path.isdir(path) or not os.access(path, os.X_OK):
        return None
    return path


def _changes_shell(segments: List[Segment], cwd: str) -> bool:
    for segment in segments:
        head, args, _ = _normalize(segment.argv)
        if _is_state_builtin(segment):
            return True
        if head in ("printf", "print") and any(a.startswith("-v") for a in args):
            return True
        # zsh's AUTO_CD runs `cd` for a command that is only a directory.
        if not args and os.path.isdir(os.path.join(cwd, head)):
            return True
    return False


def _mentions_guarded(text: str, policy: Dict) -> bool:
    for part in [text, *_PIECE_SEPARATORS.split(text)]:
        head, _ = _rough_split(part)
        if head not in _commands(policy) and part.split()[:1] == ["rtk"]:
            head = "rtk"
        if head in _guarded_heads(policy) and not _ask_only(head, _commands(policy).get(head, {})):
            return True
    return False


def _vetted(segments: Optional[List[Segment]], policy: Dict) -> bool:
    """True if every segment matches a static allow rule (later segments may
    instead be read-only filters) and nothing feeds them a heredoc."""
    if not segments:
        return False
    for position, segment in enumerate(segments):
        if segment.heredoc:
            return False
        if not _statically_allowed(segment, policy) and not (
            position and _filter_ok(segment)
        ):
            return False
    return True


def _rule_matches(rule: str, text: str) -> bool:
    """`*` matches anything; a trailing ` *` also matches no arguments."""
    if rule.endswith(" *") and text == rule[:-2]:
        return True
    return re.fullmatch(re.escape(rule).replace(r"\*", ".*"), text, re.DOTALL) is not None


def _statically_allowed(segment: Segment, policy: Dict) -> bool:
    """True if Claude Code's generated allow rules (settings.json.tmpl) match
    this segment and its deny rules do not."""
    head, args, index = _normalize(segment.argv)
    if _is_state_builtin(segment) or _through_xargs(segment.argv):
        return False
    tables = _commands(policy)
    table = tables.get(head)
    via_rtk = "rtk" in segment.argv[:index]
    if table is None and via_rtk and head:
        head, table = "rtk", tables.get("rtk")
        via_rtk = False
    if table is None:
        return False
    if any(name not in table.get("env_allow", {}) for name, _ in segment.env):
        return False
    rest = segment.argv[index:] if head != "rtk" else ["rtk", *segment.argv[index:]]
    text = " ".join((["rtk"] if via_rtk else []) + rest)
    wrapped = head in policy.get("permissions", {}).get("rtk_wraps", [])
    heads = [] if table.get("rtk_only") else [head]
    heads += ["rtk " + head] if wrapped else []
    heads += table.get("extra_heads", [])
    allow = [h + (" " + a if a else "") for h in heads for a in table.get("args", [])]
    deny = [h + " " + a for h in heads for a in table.get("deny_args", [])]
    return any(_rule_matches(r, text) for r in allow) and not any(
        _rule_matches(r, text) for r in deny
    )


def _asked_arg(head: str, args: List[str], table: Dict) -> Optional[str]:
    """The first `ask_args` entry this command matches, or None.

    An entry is a subcommand followed by conditions, all of which must hold:
    `-x` / `--flag` present (as _has_flag matches it, so `-x` also matches
    inside `-xv`), a plain word or glob such as `+*` matching an argument,
    or `!-n` / `!word` absent. For git the subcommand is the first word after
    git's global options and the conditions apply to what follows it; for
    other commands the subcommand may be any argument, which can only ask
    more often."""
    entries = table.get("ask_args", [])
    if not entries:
        return None
    sub, rest = None, args
    if head == "git":
        i = 0
        while i < len(args) and args[i].startswith("-") and args[i] != "-":
            name, has_value, _ = args[i].partition("=")
            i += 2 if name in _GIT_VALUE_OPTS and not has_value else 1
        sub, rest = (args[i], args[i + 1 :]) if i < len(args) else (None, [])
    for entry in entries:
        words = entry.split()
        if (sub != words[0]) if head == "git" else (words[0] not in args):
            continue
        if all(_ask_condition(word, rest) for word in words[1:]):
            return entry
    return None


def _ask_condition(word: str, args: List[str]) -> bool:
    if word.startswith("!"):
        return not _ask_condition(word[1:], args)
    if word == "--":
        return "--" in args
    if word.startswith("-"):
        return _has_flag(args, [word]) is not None
    return any(fnmatch.fnmatchcase(arg, word) for arg in args)


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
    if segment.env or segment.redirects or _through_xargs(segment.argv):
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


def _check_trusted_root(head: str, args: List[str], table: Dict, cwd: str,
                        policy: Dict) -> Decision:
    """Ask for an allowlisted subcommand outside the trusted roots, where the
    static allow rule would run it under a stranger's toolchain config. An
    option before the subcommand may take a value that looks like one, so
    only a plain word that is not allowlisted is left alone."""
    allowlisted = {a.split()[0] for a in table.get("args", []) if a.strip()}
    rest = args[1:] if args and args[0].startswith("+") else args
    if rest and not rest[0].startswith("-") and rest[0] not in allowlisted:
        return Decision()
    if _trusted(cwd, policy):
        return Decision()
    return Decision(
        "ask",
        "%s reads toolchain config from this directory (.cargo/config.toml, "
        "rust-toolchain.toml), which can run programs; it is auto-approved only "
        "in a trusted dev root." % head,
    )


def _decide_cargo(segments: List[Segment], cwd: str, policy: Dict) -> Decision:
    _, args, _ = _normalize(segments[0].argv)
    if segments[0].heredoc or _through_xargs(segments[0].argv) or not _cargo_args_ok(args):
        return Decision()
    if not all(_filter_ok(s) for s in segments[1:]):
        return Decision()
    if not _trusted(cwd, policy):
        return Decision()
    return Decision("allow", "cargo build/test in a trusted dev root (%s)" % cwd)


# --- git fetch / pull ------------------------------------------------------------

_SYNC_BOOL = {
    "-q", "--quiet", "-v", "--verbose", "-p", "--prune", "-t", "--tags",
    "--no-tags", "--no-recurse-submodules", "--no-rebase",
}
_SYNC_FLAGS = {
    "fetch": _SYNC_BOOL | {"--all", "--dry-run", "--unshallow"},
    "pull": _SYNC_BOOL | {"--ff-only"},
}
# Always added, so repo config cannot start a rebase or fetch submodules whose
# URLs were never checked.
_SYNC_FORCED = {
    "fetch": ["--no-recurse-submodules"],
    "pull": ["--no-rebase", "--no-recurse-submodules"],
}
_REMOTE_NAME = re.compile(r"[A-Za-z0-9._-]+")
_REF = r"[A-Za-z0-9_][A-Za-z0-9._/-]*"
_REFSPEC = re.compile(r"%s(?::%s)?" % (_REF, _REF))
_BRANCH = re.compile(_REF)


def _git_run(cwd: str, *args: str):
    """(returncode, stdout, stderr) of a read-only `git -C cwd ...`, or None
    if git could not run."""
    try:
        # LC_ALL=C: _repo_state_is_clean matches git's English error text.
        done = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True, text=True, timeout=5,
            env=dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C"),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.returncode, done.stdout, done.stderr


def _git_lines(cwd: str, *args: str) -> Optional[List[str]]:
    """stdout lines of a read-only `git -C cwd ...`, or None if it fails."""
    done = _git_run(cwd, *args)
    return done[1].splitlines() if done and done[0] == 0 else None


# Repo-local settings that make git run a program or talk to another host.
# Whoever can write .git/config or .git/hooks controls them, and approving a
# command on top of them would run that code unprompted. core.hooksPath is
# flagged only for fetch/pull; read-only commands just follow it to the hooks
# they could fire.
_RISKY_CONFIG = (
    r"core\.(sshcommand|gitproxy|fsmonitor|askpass|attributesfile"
    r"|alternaterefscommand|pager)"
    r"|credential\..*|protocol\..*|include\..*|includeif\..*|filter\..*"
    r"|remote\..*\.(uploadpack|receivepack|vcs|proxy|proxyauthmethod)"
    r"|http\..*|url\..*"
    r"|diff\.external|diff\..*\.(command|textconv)|pager\..*|gpg\..*"
)
_RISKY_LOCAL_CONFIG = re.compile(_RISKY_CONFIG, re.IGNORECASE)
_RISKY_SYNC_CONFIG = re.compile(_RISKY_CONFIG + r"|core\.hookspath", re.IGNORECASE)
_FETCH_PULL_HOOKS = (
    "reference-transaction", "post-merge", "post-checkout", "pre-auto-gc",
    "fsmonitor-watchman", "post-index-change", "post-rewrite",
)
# `git status` and `git diff` refresh the index, which fires this hook.
_READ_HOOKS = ("post-index-change",)
_MAX_SUBMODULES = 50
_MAX_SUBMODULE_DEPTH = 3
_GITLINK = "160000"


def _config_is_risky(lines: List[str], risky) -> bool:
    for line in lines:
        scope, _, key = line.rpartition("\t")
        if scope in ("", "local", "worktree", "command") and risky.fullmatch(key):
            return True
    return False


def _submodules_are_clean(cwd: str, git_opts, sync: bool, depth: int) -> bool:
    """`git status` runs git inside each populated submodule, under that
    submodule's own config and hooks, wherever its git dir lives."""
    done = _git_run(cwd, *git_opts, "ls-files", "--stage", "-z", "--full-name", "--", ":/")
    if done is None or done[0] != 0:
        return False
    paths = []
    for entry in done[1].split("\0"):
        meta, _, path = entry.partition("\t")
        if meta.split(" ", 1)[0] == _GITLINK:
            paths.append(path)
    if not paths:
        return True
    if depth >= _MAX_SUBMODULE_DEPTH or len(paths) > _MAX_SUBMODULES:
        return False
    top = _git_lines(cwd, *git_opts, "rev-parse", "--show-toplevel")
    if not top:
        return False
    for path in paths:
        sub = os.path.join(top[0], path)
        if os.path.lexists(os.path.join(sub, ".git")) and not _repo_state_is_clean(
            sub, (), sync, depth + 1
        ):
            return False
    return True


def _repo_state_is_clean(cwd: str, git_opts=(), sync: bool = True, depth: int = 0) -> bool:
    """False if repo-local config or a hook could run code during the git
    command, or if any probe fails. `git_opts` are its location options
    (-C, --git-dir, --work-tree), so the check looks at the repo the command
    will use."""
    lines = _git_lines(cwd, *git_opts, "config", "--show-scope", "--list", "--name-only")
    if lines is None:
        return False
    if _config_is_risky(lines, _RISKY_SYNC_CONFIG if sync else _RISKY_LOCAL_CONFIG):
        return False
    has_repo_config = any(
        line.partition("\t")[0] in ("local", "worktree") for line in lines
    )
    done = _git_run(cwd, *git_opts, "rev-parse", "--path-format=absolute",
                    "--git-path", "hooks", "--is-bare-repository")
    if done is None:
        return False
    code, out, stderr = done
    if code != 0:
        # Outside a repository git reads no repo-local config or hooks.
        return not has_repo_config and "not a git repository" in stderr
    paths = out.splitlines()
    if len(paths) != 2:
        return False
    hooks_dir, bare = paths
    hooks = _FETCH_PULL_HOOKS if sync else _READ_HOOKS
    if any(os.path.lexists(os.path.join(hooks_dir, h)) for h in hooks):
        return False
    if bare == "true":
        return True
    return _submodules_are_clean(cwd, git_opts, sync, depth)


_GIT_LOCATION_OPTS = {"-C", "--git-dir", "--work-tree"}
_GIT_VALUE_OPTS = _GIT_LOCATION_OPTS | {
    "-c", "--config-env", "--namespace", "--super-prefix", "--list-cmds", "--attr-source",
}
_GIT_BOOL_OPTS = {
    "-p", "--paginate", "-P", "--no-pager", "--no-replace-objects", "--no-lazy-fetch",
    "--no-optional-locks", "--no-advice", "--bare", "--literal-pathspecs",
    "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--version", "-v",
    "--help", "-h", "--html-path", "--man-path", "--info-path", "--exec-path",
}


def _git_globals(args: List[str]):
    """Parse git's global options: (location options, subcommand, problem).
    `problem` is "deny" for a `-c` / --config-env / --exec-path=DIR that can
    run a program, "ask" for an option this parser does not model, else
    None."""
    location, problem, i = [], None, 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-") or arg == "-":
            return location, arg, problem
        name, has_value, value = arg.partition("=")
        if name in _GIT_VALUE_OPTS and not has_value:
            if i + 1 >= len(args):
                return location, None, "ask"
            value = args[i + 1]
            i += 1
        if name in _GIT_LOCATION_OPTS:
            location += [name, value] if name == "-C" else ["%s=%s" % (name, value)]
        elif name == "-c":
            if _RISKY_SYNC_CONFIG.fullmatch(value.partition("=")[0]):
                problem = "deny"
        elif name == "--config-env" or (name == "--exec-path" and has_value):
            problem = "deny"
        elif name not in _GIT_VALUE_OPTS and (has_value or name not in _GIT_BOOL_OPTS):
            problem = problem or "ask"
        i += 1
    return location, None, problem


def _check_git_repo_state(segment: Segment, args: List[str], table: Dict,
                          cwd: str, policy: Dict) -> Decision:
    """Deny a `-c` that runs a program, and ask before an allowlisted git
    subcommand runs in a repo whose local config or hooks would."""
    location, sub, problem = _git_globals(args)
    if problem == "deny":
        return Decision(
            "deny", "git -c, --config-env and --exec-path can run programs; they are blocked "
            "like the matching GIT_* environment overrides.")
    if problem == "ask":
        return Decision("ask", "git global options this hook cannot check; review them.")
    allowlisted = {a.split()[0] for a in table.get("args", []) if a.strip()}
    if sub not in allowlisted and sub not in _SYNC_FLAGS:
        return Decision()
    base = cwd
    if segment.argv[_normalize(segment.argv)[2]] == "chezmoi":
        base = policy.get("chezmoi_working_tree")
    if not base or not _repo_state_is_clean(base, location, sub in _SYNC_FLAGS):
        return Decision(
            "ask",
            "This repository's local git config or hooks can run a program during "
            "git %s, or could not be checked; review them before running." % sub,
        )
    return Decision()


def _approved_git_url(policy: Dict):
    hook = policy.get("permissions", {}).get("hook", {})
    hosts, owners = hook.get("approved_git_hosts"), hook.get("approved_git_owners")
    if not hosts or not owners:
        return None
    host = "|".join(re.escape(h) for h in hosts)
    owner = "|".join(re.escape(o) for o in owners)
    return re.compile(
        r"(?:https://(?:[^@/\s]+@)?(?:%s)/|ssh://git@(?:%s)/|git@(?:%s):)"
        r"(?:%s)/[A-Za-z0-9._-]+/?" % (host, host, host, owner),
        re.IGNORECASE,
    )


def _remotes_approved(targets: List[str], cwd: str, policy: Dict) -> bool:
    """True if every target (a remote name or URL) expands, after any
    `url.<base>.insteadOf` rewriting, to an approved URL."""
    approved = _approved_git_url(policy)
    if approved is None or not targets:
        return False
    for target in targets:
        lines = _git_lines(cwd, "ls-remote", "--get-url", target)
        if not lines or not approved.fullmatch(lines[0]):
            return False
    return True


def _sync_targets(sub: str, args: List[str], cwd: str) -> Optional[List[str]]:
    """Validate fetch/pull arguments; return the remotes they contact, or None."""
    positionals = []
    for arg in args:
        if arg in _SYNC_FLAGS[sub] or re.fullmatch(r"--depth=\d+", arg):
            continue
        if re.fullmatch(r"-[a-zA-Z]{2,}", arg) and all(
            "-" + ch in _SYNC_FLAGS[sub] for ch in arg[1:]
        ):
            continue
        if arg.startswith("-"):
            return None
        positionals.append(arg)
    if sub == "pull" and "--ff-only" not in args:
        return None
    if positionals:
        if "--all" in args or len(positionals) > (2 if sub == "pull" else 5):
            return None
        remote, specs = positionals[0], positionals[1:]
        pattern = _BRANCH if sub == "pull" else _REFSPEC
        if not all(pattern.fullmatch(spec) and ".." not in spec for spec in specs):
            return None
        return [remote]
    return _git_lines(cwd, "remote")


def _decide_git_sync(command: str, segments: List[Segment], cwd: str, policy: Dict) -> Decision:
    first = segments[0]
    # Only a bare `git`/`rtk git`: `chezmoi git` runs in the source repo.
    if first.argv[:1] != ["git"] and first.argv[:2] != ["rtk", "git"]:
        return Decision()
    if first.env or first.redirects or _through_xargs(first.argv):
        return Decision()
    _, args, index = _normalize(first.argv)
    if not args or args[0] not in _SYNC_FLAGS:
        return Decision()
    if not all(_filter_ok(s) for s in segments[1:]):
        return Decision()
    sub, rest = args[0], args[1:]
    targets = _sync_targets(sub, rest, cwd)
    # _check_segment has already asked if the repo's config or hooks are risky.
    if not targets or not _remotes_approved(targets, cwd, policy):
        return Decision()
    extra = "".join(" " + f for f in _SYNC_FORCED[sub] if f not in rest)
    updated = command
    if extra:
        word = first.words[index + 1]
        updated = command[: word.end] + extra + command[word.end :]
    return Decision(
        "allow", "git %s from an approved remote" % sub, updated if extra else None
    )


def _check_gitleaks_repo(args: List[str], cwd: str) -> Decision:
    """`gitleaks git [path]` runs `git log -p` in the repo it scans. Any
    argument naming a directory might be that path, so check them all."""
    if not args or args[0] != "git":
        return Decision()
    dirs = [cwd] + [
        os.path.join(cwd, a.partition("=")[2] if a.startswith("-") else a)
        for a in args[1:]
    ]
    for path in dirs:
        if os.path.isdir(path) and not _repo_state_is_clean(path, sync=False):
            return Decision(
                "ask",
                "This repository's local git config or hooks can run a program "
                "when gitleaks runs git log; review it before running.",
            )
    return Decision()


# --- chezmoi --------------------------------------------------------------------

_SECRET_RENDERING = {"cat", "diff", "status", "verify"}
_SKIP_SECRETS_ON = {"--skip-secrets", "--skip-secrets=true"}


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
    # The hook adds --skip-secrets; a later --skip-secrets=false would win.
    for arg in args:
        if arg.startswith("--skip-secrets=") and arg not in _SKIP_SECRETS_ON:
            return Decision("deny", "chezmoi %s would render secret-manager templates." % arg)
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
    head, args, index = _normalize(segment.argv)
    if head != "chezmoi" or len(segment.words) < index + 2:
        return Decision()
    sub = segment.words[index + 1]
    if sub.value not in _SECRET_RENDERING or set(args) & _SKIP_SECRETS_ON:
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
# Literal text plus a few read-only variables; `%output{FILE}` would write a
# file and `@FILE` would read one.
_CURL_WRITE_OUT = (
    r"(?:[^%@\\]|\\n|%\{(?:http_code|response_code|time_total|time_connect"
    r"|time_starttransfer|size_download|content_type|url_effective|remote_ip"
    r"|num_redirects)\})*"
)
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
    if first.env or _through_xargs(first.argv) or any(w.glob for w in first.words):
        return Decision()
    if not _curl_ok(args):
        return Decision()
    return Decision("allow", "local read-only curl request in curl-runner")

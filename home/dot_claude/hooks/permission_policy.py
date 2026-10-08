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
    segments = scan(command)
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
        if crude in _guarded_heads(policy):
            # A rough whitespace split can still spot a forbidden flag, and
            # erring toward deny is safe; otherwise ask, since hidden syntax
            # could smuggle one past the check.
            table = _commands(policy).get(crude, {})
            flag = _has_flag(rough_args, table.get("deny_flags", []))
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


def _decide_cargo(segments: List[Segment], cwd: str, policy: Dict) -> Decision:
    _, args, _ = _normalize(segments[0].argv)
    if _through_xargs(segments[0].argv) or not _cargo_args_ok(args):
        return Decision()
    if not all(_filter_ok(s) for s in segments[1:]):
        return Decision()
    if not _trusted(cwd, policy):
        return Decision()
    return Decision("allow", "cargo build/test in a trusted dev root (%s)" % cwd)


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
    if first.env or _through_xargs(first.argv) or not _curl_ok(args):
        return Decision()
    return Decision("allow", "local read-only curl request in curl-runner")

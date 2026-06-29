#!/usr/bin/env python3
"""Claude Code PreToolUse prefilter — auto-approve a narrow set of Bash commands.

Two fast-paths, both *fail safe*: on anything they can't positively prove safe
they print nothing and exit 0, which lets Claude Code's normal permission flow
(static allowlist, then a manual prompt) take over. They only ever *allow* —
they never deny — so they can only remove prompts, never add new blocks.

  1. cargo  — auto-approve `cargo test|clippy|build|run|check` (incl. piped into
              read-only filters) ONLY when the session cwd is under a trusted
              dev root. These compile+run code (build.rs, proc-macros, tests),
              so they are arbitrary code execution and are gated by location.

  2. python — auto-approve `python[3] -c "<body>"` (incl. piped into read-only
              filters) ONLY when the body passes a conservative static check:
              no writes, no deletes, no network, no subprocess/eval, no secret
              or sensitive-path access, no obvious obfuscation. Global (not
              dir-scoped), matching the goal "read-only, non-exfiltrating,
              non-sensitive Python is fine anywhere".

This is a guardrail against accidental side effects, NOT a security sandbox.
It assumes Claude is non-adversarial; a determined attacker could obfuscate
past the static checks. The manual prompt remains the backstop for anything
unusual. Tune the constants below to taste.
"""

import json
import os
import shlex
import sys

# --- Configuration -----------------------------------------------------------

# Directories under which compiling/running your own Rust code is considered
# trusted. cwd must be inside one of these for the cargo fast-path to fire.
TRUSTED_DEV_ROOTS = [
    os.path.expanduser("~/git/nickvigilante"),
    os.path.expanduser("~/rust"),
]

# cargo subcommands that may be auto-approved inside a trusted root.
CARGO_OK_SUBCOMMANDS = {"test", "clippy", "build", "run", "check"}

# Leading command tokens that are read-only enough to appear as downstream
# stages of a pipeline without voiding the fast-path (e.g. `cargo test | grep`).
SAFE_FILTER_COMMANDS = {
    "grep", "egrep", "fgrep", "rg", "head", "tail", "sort", "uniq", "wc",
    "cut", "tr", "sed", "awk", "cat", "tee", "echo", "jq", "tac", "rev",
    "column", "nl", "fold", "less", "true", "false", "xargs",
}

# Substrings that, if present in a `python -c` body, force a passthrough
# (manual prompt). Covers state mutation, network, exec, secrets, obfuscation.
PYTHON_DENY_SUBSTRINGS = [
    # process / shell / dynamic execution
    "system", "popen", "subprocess", "os.exec", "pty", "eval(", "exec(",
    "compile(", "__import__", "getattr(", "setattr(", "globals(", "locals(",
    "vars(", "input(", "breakpoint(",
    # filesystem mutation
    ".write(", ".writelines(", ".write_text(", ".write_bytes(", ".truncate(",
    "shutil", "os.remove", "os.unlink", "os.rmdir", "os.removedirs",
    "os.rename", "os.replace", "os.mkdir", "os.makedirs", "os.chmod",
    "os.chown", "os.link", "os.symlink", "os.fchmod", ".unlink(", ".rmdir(",
    ".rename(", ".replace(", ".mkdir(", ".touch(", "tempfile",
    # write file modes (open(..., 'w'|'a'|'x'|'+'))
    "'w'", '"w"', "'wb'", '"wb"', "'a'", '"a"', "'ab'", '"ab"', "'x'",
    '"x"', "'xb'", "'r+'", "'w+'", "'a+'", "'+b'", "'rb+'",
    # network / exfiltration
    "socket", "urllib", "urlopen", "requests", "httpx", "http.client",
    "httplib", "ftplib", "smtplib", "websocket", "asyncio", "telnetlib",
    "xmlrpc", "ssl.", "paramiko",
    # secrets / sensitive paths / environment
    "environ", "getenv", "putenv", "expanduser", "expandvars", ".ssh",
    ".aws", "gcloud", "credential", ".netrc", "id_rsa", "id_ed25519",
    "secret", "passwd", "password", "keychain", ".npmrc", ".pypirc",
    ".git-credentials", "api_key", "apikey", "/etc/", "cookie", "token",
    # obfuscation primitives
    "\\x", "chr(", "ord(", "codecs", "base64", "fromhex", "decode(",
    "marshal", "pickle", "ctypes", "mmap",
]

# --- Hook plumbing -----------------------------------------------------------


def passthrough():
    """Emit no decision; normal permission flow (allowlist, then prompt) runs."""
    sys.exit(0)


def allow(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


_OPERATOR_TOKENS = {";", "|", "||", "&&", "&", "|&", ";;"}


def split_segments(command):
    """Quote-aware split into pipeline/sequence segments.

    Returns a list of token-lists (one per segment), or None if the command
    can't be parsed safely (unbalanced quotes, heredoc, etc.) — in which case
    callers must fall through to a manual prompt. Using a real lexer means a
    `;` or `|` *inside* a quoted argument (e.g. python -c "a;b") stays part of
    that argument instead of being mistaken for a shell separator.
    """
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return None
    segments, cur = [], []
    for tok in tokens:
        if tok in _OPERATOR_TOKENS:
            if cur:
                segments.append(cur)
                cur = []
        else:
            cur.append(tok)
    if cur:
        segments.append(cur)
    return segments


def leading_tokens(tokens):
    """Token list with env-var assignments and a leading `rtk` wrapper stripped."""
    i = 0
    while i < len(tokens) and "=" in tokens[i] and tokens[i].split("=", 1)[0].isidentifier():
        i += 1
    if i < len(tokens) and tokens[i] == "rtk":
        i += 1
    return tokens[i:]


# --- cargo fast-path ---------------------------------------------------------


def cwd_is_trusted(cwd):
    real = os.path.realpath(cwd)
    for root in TRUSTED_DEV_ROOTS:
        root = os.path.realpath(root)
        if real == root or real.startswith(root + os.sep):
            return True
    return False


def try_cargo(segments, cwd):
    if not segments:
        return
    saw_cargo = False
    for seg in segments:
        toks = leading_tokens(seg)
        if not toks:
            return
        head = os.path.basename(toks[0])
        if head == "cargo":
            sub = next((t for t in toks[1:] if not t.startswith("-")), "")
            if sub not in CARGO_OK_SUBCOMMANDS:
                return
            saw_cargo = True
        elif head in SAFE_FILTER_COMMANDS:
            continue
        else:
            return  # an un-vetted command shares the line — bail
    if not saw_cargo:
        return
    if not cwd_is_trusted(cwd):
        return
    allow("cargo build/test in a trusted dev root (%s)" % cwd)


# --- python fast-path --------------------------------------------------------

def extract_py_c_body(toks):
    """Return the body string of a `python[3] -c <body>` invocation, else None.

    `toks` is an already-normalized token list (env/rtk stripped) whose first
    token is python/python3. Only the `-c` form is accepted: `-m`, stdin (`-`),
    and bare script-file invocations all return None so they keep prompting.
    Because tokens come from a posix lexer, the body is a single token with its
    surrounding quotes already removed.
    """
    if not toks or os.path.basename(toks[0]) not in ("python", "python3"):
        return None
    args = toks[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-c":
            return args[i + 1] if i + 1 < len(args) else None
        if a == "-m" or a == "-":
            return None
        if a.startswith("-"):
            i += 1  # benign interpreter flag (-E, -u, -O, ...) — skip
            continue
        return None  # a non-flag token before -c is a script file — reject
    return None


def body_is_read_only(body):
    low = body.lower()
    for bad in PYTHON_DENY_SUBSTRINGS:
        if bad.lower() in low:
            return False
    return True


def try_python(segments):
    if not segments:
        return
    saw_python = False
    for seg in segments:
        toks = leading_tokens(seg)
        if not toks:
            return
        head = os.path.basename(toks[0])
        if head in ("python", "python3"):
            body = extract_py_c_body(toks)
            if body is None or not body_is_read_only(body):
                return
            saw_python = True
        elif head in SAFE_FILTER_COMMANDS:
            continue
        else:
            return
    if saw_python:
        allow("read-only python -c one-liner (no writes/network/secrets)")


# --- entry -------------------------------------------------------------------


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        passthrough()
    if data.get("tool_name") != "Bash":
        passthrough()
    command = (data.get("tool_input") or {}).get("command", "") or ""
    cwd = data.get("cwd") or os.getcwd()
    segments = split_segments(command)
    if segments is None:
        passthrough()  # unparseable (heredoc/unbalanced quotes) — let it prompt
    try_cargo(segments, cwd)
    try_python(segments)
    passthrough()


if __name__ == "__main__":
    main()

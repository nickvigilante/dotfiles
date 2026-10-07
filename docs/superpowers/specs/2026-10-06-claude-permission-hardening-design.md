# Claude Code permission hardening — design

Date: 2026-10-06.
Status: approved in discussion; implementation plan in `docs/superpowers/plans/2026-10-06-claude-permission-hardening.md`.

## Problem

An audit found that the generated Bash allowlist and the `permission-prefilter.py` hook auto-approve commands that can run arbitrary code, write files, or read secrets.
The main cases, all reproduced:

- The prefilter's pipeline "filters" (`xargs`, `tee`, `sed`, `awk`, `sort -o`, `uniq in out`, `rg --pre`) were checked by name only, and `;`, `&&` and `&` were treated like `|`.
- The prefilter tokenized with `shlex`, which does not expand like bash or zsh, so `$(…)`, backticks, redirects, newlines and `$'…'` slipped through.
- The `python -c` denylist was easy to bypass, and `python3 -c` imports modules from the current directory.
- `VAR=` prefixes and absolute paths were ignored for cargo, and cargo flags such as `--manifest-path`, `--config` and `--target <spec.json>` were not checked.
- `rtk_only_tools` granted `rtk rg *` and `rtk tree *`; the rtk hook rewrites plain `rg` to `rtk rg`, so `rg --pre=CMD` ran `CMD` and `tree -o FILE` wrote files.
- `chezmoi cat/diff/status/verify *` accepted `--config`, `--source`, `--pager` and `-o`, and `chezmoi cat` printed Bitwarden-rendered secrets.
- The curl rules matched `http://localhost:@evil.com/`, extra URLs and data flags, and `-I *` allowed any host.
- `git log/diff/show` accepted `--output`, `--ext-diff` and `--no-index`.

## Verified platform facts (Claude Code 2.1.292)

- When hooks disagree, the most restrictive decision wins (`deny`, `defer`, `ask`, `allow`), and a hook `deny` overrides allow rules in every mode (documented).
- A hook's `deny` reason is shown to the model (documented).
- Global PreToolUse hooks fire for subagent tool calls, and subagent calls carry `agent_type` and `agent_id` while main-session calls carry neither (verified with `scripts/dev/hook-probe.sh`; not documented).
- The rtk hook copies the user's allow rules onto the original command, always allows `grep` (harmless: `rtk grep` runs the system grep), rewrites `rg`, `ls`, `tree`, `wc`, `diff`, `du`, `df`, `ps`, `curl` and `cargo`, rewrites `cat` and `head` to `rtk read`, and never rewrites `chezmoi`.
- Whether a hook `ask` prompts in auto mode is not documented and is part of the manual test plan.

## Decisions

1. **Pipelines:** only `|` joins commands; the first command is the producer (cargo, or curl inside curl-runner); later commands are filters that read only stdin, each with its own allowed flags.
   Kept: `grep egrep fgrep head tail wc sort uniq cut tr tac rev nl column fold jq`, plus `sed -n 'Np'` and `sed -n 'N,Mp'`.
   Dropped: `xargs tee awk less rg cat echo true false` and every other `sed` form.
   `jq` filters may not mention `env` or `$ENV`.
2. **Scanner:** one hand-written scanner replaces `shlex`, using a character allowlist.
   Outside quotes: letters, digits, `_ . / : = , + % @ -`, whitespace, `|`, and `~` at the start of a word before `/` or the word's end; `=` may not start a word (zsh `=cmd` expansion).
   Single quotes: anything.
   Double quotes: anything but `$` and backticks; backslash escapes as in bash and zsh.
   `2>&1` and `2>/dev/null` are allowed as exact whole words on the producer.
3. **Python:** the `python -c` fast-path is removed, so `python3 -c` always prompts; rebuilding it is tracked in issue #135.
4. **cargo:** the command must be the bare word `cargo` (or `rtk cargo`); `VAR=` prefixes come from an `env_allow` list (`RUST_BACKTRACE`, `RUST_LOG`, `CARGO_TERM_COLOR`, `NO_COLOR`); flags come from an allowlist with value patterns; `+toolchain` must be `stable`, `beta` or `nightly` (optionally dated) or `1.N[.N]`; `--profile` is not allowed for now.
5. **Parity and flags:** `rtk_only_tools` is replaced by ordinary command tables, so the plain, `rtk` and `chezmoi git` forms are generated together; `rtk read` is the one `rtk_only` table.
   Tables can declare `deny_flags` (the default response), `ask_flags` (the exception, currently empty), `env_allow`, and `deny_args`.
   When a guarded command cannot be parsed, the hook denies if a rough split shows a forbidden flag and otherwise asks.
6. **chezmoi:** the read rules move into a `chezmoi` table with `deny_flags` for `--config`, `--pager`, `--output`, `--persistent-state`, `--cache`, `--refresh-externals`, `--destination`, `--override-data-file`, `--init` and `--working-tree`; `--source` is allowed only inside the dotfiles working tree; the hook adds `--skip-secrets` to `cat`, `diff`, `status` and `verify`.
7. **curl:** the static curl rules are removed; the single global hook denies curl outside the `curl-runner` agent (identified by `agent_type`) and, inside it, allows one local GET/HEAD/OPTIONS request with allowlisted flags and denies anything that is not curl.
   `curl-runner` gets `permissionMode: default`.
8. **git:** `deny_flags` for `--output`, `--ext-diff`, `--textconv`, `--no-index` and `--contents`, and `env_allow` for `NO_COLOR=1` and `GIT_PAGER=cat`.
9. **Testing:** stdlib `unittest` suites run in CI, including a check that bash and zsh read every accepted command the way the scanner does; a manual test plan covers `ask` in auto mode, `permissionMode: default`, and the probe script.

## Out of scope

- The remaining lower-priority allowlist findings (`brew bundle check --file`, `pnpm audit --fix`, `exec astro check`, `kubectl`/`helm --kubeconfig`).
- Repo-local git config in extracted archives (`core.fsmonitor` on `git status`).
- Promoting `ask_flags` entries before the auto-mode `ask` test has run.

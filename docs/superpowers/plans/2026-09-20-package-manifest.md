# Package Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `home/.chezmoidata/packages.toml` the single declaration of what software a machine gets, with `Brewfile.tmpl` generated from it and a CI check that the rendered package set never silently changes.

**Architecture:** chezmoi already loads `.chezmoidata/*.toml` into template data, so the Brewfile needs no external renderer — this is the same mechanism `permissions.toml` already uses to generate the Claude allowlist. Migration is section by section, each verified by rendering the Brewfile before and after and diffing the sorted package set.

**Tech Stack:** chezmoi v2.72 Go templates, TOML, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-20-unified-package-manifest-design.md` — sections 1, 2 and 3.

## Global Constraints

- Markdown follows one sentence per line; never column-wrap prose.
- Commit messages are Conventional Commits and end with the trailer `Assisted-by: AI`.
- PR bodies end with `---` then `🤖 Built with AI assistance.`
- Never name a model, vendor or product in a commit or PR.
- Branch work happens in a git worktree under `.worktrees/<branch-name>`; never commit to `main`.
- `home/dot_config/dotfiles/Brewfile.tmpl` becomes a generated target. After Task 3 it is never hand-edited; packages are added to `packages.toml`.

## Deviation from the spec: the invariant is the package set, not the bytes

The spec's migration step 2 asks for output byte-identical to what is committed.
That is not worth chasing here.
The existing Brewfile's comment column is hand-aligned per section rather than globally:

```console
$ grep -E '^brew "' Brewfile.tmpl | awk '{i=index($0,"#"); if(i) print i}' | sort -u
22
23
25
26
```

Reproducing that exactly would mean encoding per-section padding quirks into a data file, which is presentation noise in the one place that should hold only data.

This plan asserts instead that the **set of packages rendered is unchanged**, compared as sorted `tap`/`brew`/`cask`/`vscode`/`cargo`/`go`/`uv` lines with comments and padding stripped.
That is the invariant that actually matters — a package silently appearing or vanishing — and it does not break when formatting normalizes.
The rendered diff is still reviewed by eye in each PR.

## Scope

In scope: `packages.toml`, generating `Brewfile.tmpl` from it, and the CI drift check.

Out of scope, deferred to a later plan: generating `images/base/tools.txt` from the same manifest, and expanding the base image to the full `core` and `quality` tiers.
That is where the user-visible payoff lands, but it depends on this manifest existing first.

## File Structure

| File | Responsibility |
| ---- | -------------- |
| `home/.chezmoidata/packages.toml` | The single declaration: one entry per package, its channels, tier and section |
| `home/dot_config/dotfiles/Brewfile.tmpl` | Generated: iterates the manifest, emits Homebrew syntax |
| `tests/brewfile-parity.sh` | Renders the Brewfile for a given data cell and prints its normalized package set |
| `.github/workflows/ci.yml` | Runs the parity check on Linux and macOS |

---

### Task 1: Capture the baseline and add the parity harness

**Files:**
- Create: `tests/brewfile-parity.sh`

**Interfaces:**
- Produces: `tests/brewfile-parity.sh <profile> <display> <secrets>` prints the rendered Brewfile's normalized package set, one entry per line, sorted. Tasks 2, 3 and 4 all consume this exact interface.

- [ ] **Step 1: Write the harness**

Create `tests/brewfile-parity.sh`:

```bash
#!/usr/bin/env bash
# Render Brewfile.tmpl for one data cell and print its package set, normalized.
#
# Normalization strips comments and padding so the output is the semantic
# content only: which entries of which type. Formatting may change freely;
# a package appearing or disappearing may not.
#
# .chezmoi.os is supplied by the running machine and cannot be overridden, so
# macOS-gated sections are only exercised when this runs on macOS. CI runs it
# on both.
set -uo pipefail

CHEZMOI="${CHEZMOI:-chezmoi}"
PROFILE="${1:?usage: brewfile-parity.sh <profile> <display> <secrets>}"
DISPLAY_="${2:?}"
SECRETS="${3:?}"
TMPL="${TMPL:-home/dot_config/dotfiles/Brewfile.tmpl}"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/cfg.toml" <<EOF
[data]
profile = "$PROFILE"
name    = "x"
email   = ""
machine = "laptop"
display = $DISPLAY_
secrets = "$SECRETS"
EOF

"$CHEZMOI" execute-template --config "$TMP/cfg.toml" < "$TMPL" \
  | sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//' \
  | grep -E '^(tap|brew|cask|vscode|cargo|go|uv) ' \
  | sort
```

Then `chmod +x tests/brewfile-parity.sh`.

- [ ] **Step 2: Verify it produces sensible output**

Run: `CHEZMOI=/home/coder/.local/bin/chezmoi ./tests/brewfile-parity.sh personal false none`

Expected: a sorted list beginning `brew "actionlint"` and including `brew "rtk"`, `brew "opentofu"` and `cargo "bws"`, with no comments and no `cask` lines (casks are macOS plus display only).

- [ ] **Step 3: Capture the baseline for every Linux-reachable cell**

```bash
mkdir -p /tmp/brewfile-baseline
for p in work personal; do
  for d in true false; do
    for s in none bitwarden 1password both; do
      CHEZMOI=/home/coder/.local/bin/chezmoi \
        ./tests/brewfile-parity.sh "$p" "$d" "$s" \
        > "/tmp/brewfile-baseline/$p-$d-$s.txt"
    done
  done
done
wc -l /tmp/brewfile-baseline/*.txt | tail -1
```

Expected: 16 files, non-empty. Keep this directory for the rest of the plan; every later task diffs against it.

- [ ] **Step 4: Commit**

```bash
git add tests/brewfile-parity.sh
git commit -m "test: add a Brewfile package-set parity harness

Renders Brewfile.tmpl for one data cell and prints its package set with
comments and padding stripped, so a migration can prove no package silently
appeared or vanished. Formatting is deliberately not asserted: the existing
file's comment column is hand-aligned per section, so byte-identical output
would mean encoding padding quirks into a data file.

Assisted-by: AI"
```

---

### Task 2: Move the ungated sections into the manifest

**Files:**
- Create: `home/.chezmoidata/packages.toml`
- Modify: `home/dot_config/dotfiles/Brewfile.tmpl` — the cross-platform CLI and repo quality-gate sections only

**Interfaces:**
- Consumes: `tests/brewfile-parity.sh` from Task 1.
- Produces: `.packages` in chezmoi template data — an ordered array of tables, each with `key`, `section`, `tiers`, an optional `comment`, and optional channel fields `brew`, `cask`, `apt`, `cargo`, `go`, `uv`.

- [ ] **Step 1: Create the manifest with the ungated packages**

Create `home/.chezmoidata/packages.toml`. Use an array of tables, not a map: Go templates iterate maps in sorted key order, which would scramble the Brewfile's deliberate grouping.

```toml
# Single declaration of what software a machine gets.
#
# This is a generated target's data file, exactly like permissions.toml:
# edit here, never the rendered Brewfile.
#
# Ordering is significant — Go templates iterate a map in sorted key order,
# so packages are an ARRAY of tables to preserve the file's grouping.
#
# Channel fields (brew/cask/apt/cargo/go/uv) describe availability, not
# preference. A package with only `brew` is unavailable on the Pi, and the
# renderer says so rather than dropping it silently.

[[packages]]
key     = "git"
section = "cli"
brew    = "git"
apt     = "git"
comment = "Distributed revision control"
tiers   = ["core"]

[[packages]]
key     = "curl"
section = "cli"
brew    = "curl"
apt     = "curl"
comment = "HTTP client"
tiers   = ["core"]
```

Continue for every entry in the two ungated sections, in the order they appear in `Brewfile.tmpl` today: the cross-platform CLI block through `gnu-getopt`, then the repo quality-gate block.
Copy each `comment` verbatim from the existing line.
Assign `tiers` from the merged spec's table — `core` for the CLI block, `quality` for the gate block.

- [ ] **Step 2: Render those two sections from the manifest**

In `home/dot_config/dotfiles/Brewfile.tmpl`, replace the two hand-written blocks with:

```gotemplate
# ── Cross-platform CLI (every full-toolkit machine) ──────────────────────────
{{ range .packages -}}
{{ if and (eq .section "cli") .brew -}}
{{ printf "%-21s# %s" (printf "brew %q" .brew) .comment }}
{{ end -}}
{{ end }}
# ── Repo quality gate ────────────────────────────────────────────────────────
{{ range .packages -}}
{{ if and (eq .section "quality") .brew -}}
{{ printf "%-21s# %s" (printf "brew %q" .brew) .comment }}
{{ end -}}
{{ end }}
```

Leave every other section untouched for now.

- [ ] **Step 3: Verify the package set is unchanged**

```bash
for f in /tmp/brewfile-baseline/*.txt; do
  n=$(basename "$f" .txt); IFS=- read -r p d s <<< "$n"
  CHEZMOI=/home/coder/.local/bin/chezmoi ./tests/brewfile-parity.sh "$p" "$d" "$s" \
    | diff -u "$f" - || echo "DRIFT in $n"
done
```

Expected: no output at all. Any `DRIFT` line means a package was gained or lost; fix the manifest before continuing rather than accepting the new set.

- [ ] **Step 4: Review the rendered diff by eye**

```bash
CHEZMOI=/home/coder/.local/bin/chezmoi chezmoi execute-template \
  --config <(printf '[data]\nprofile="personal"\nname="x"\nemail=""\nmachine="laptop"\ndisplay=false\nsecrets="none"\n') \
  < home/dot_config/dotfiles/Brewfile.tmpl | sed -n '1,60p'
```

Expected: the two sections read as before. Padding may differ; package names and comments must not.

- [ ] **Step 5: Commit**

```bash
git add home/.chezmoidata/packages.toml home/dot_config/dotfiles/Brewfile.tmpl
git commit -m "refactor(packages): declare the ungated packages in packages.toml

First half of collapsing six independent declaration points into one. The
cross-platform CLI and quality-gate sections now render from
.chezmoidata/packages.toml, the same mechanism permissions.toml already uses
to generate the Claude allowlist.

Packages are an array of tables rather than a map: Go templates iterate maps
in sorted key order, which would scramble the file's deliberate grouping.

Verified by rendering all 16 Linux-reachable data cells before and after and
diffing the normalized package set — no package gained or lost.

Assisted-by: AI"
```

---

### Task 3: Move the gated sections into the manifest

**Files:**
- Modify: `home/.chezmoidata/packages.toml`
- Modify: `home/dot_config/dotfiles/Brewfile.tmpl` — remaining sections

**Interfaces:**
- Consumes: `.packages` from Task 2.
- Produces: optional `profiles`, `os` and `secrets` fields on a package entry, each an array of permitted values. Absent means unrestricted.

- [ ] **Step 1: Extend the manifest schema**

Add the gating fields to the entries that need them. For example:

```toml
[[packages]]
key      = "vale"
section  = "work"
brew     = "vale"
comment  = "Prose linter"
tiers    = ["quality"]
profiles = ["work"]

[[packages]]
key      = "bitwarden-cli"
section  = "secrets"
brew     = "bitwarden-cli"
comment  = "Bitwarden CLI"
tiers    = ["secrets"]
os       = ["darwin"]
secrets  = ["bitwarden", "both"]

[[packages]]
key      = "bws"
section  = "cargo"
cargo    = "bws"
comment  = "Bitwarden Secrets Manager CLI"
tiers    = ["secrets"]
profiles = ["personal"]
```

Preserve the existing `os = ["darwin"]` restriction on `bitwarden-cli` exactly.
The Linux Bitwarden CLI currently comes from the bootstrap, not the Brewfile, and changing that belongs to the deferred image plan, not this one.

- [ ] **Step 2: Render the gated sections**

Replace each remaining hand-written block with a `range` filtered on `section` plus the gating fields. The macOS cask block, for example:

```gotemplate
{{ if and .display (eq .chezmoi.os "darwin") -}}
{{ range $.packages -}}
{{ if and (eq .section "cask") .cask (or (not .profiles) (has $.profile .profiles)) -}}
{{ printf "%-21s# %s" (printf "cask %q" .cask) .comment }}
{{ end -}}
{{ end -}}
{{ end }}
```

Note `$.packages` and `$.profile` inside `range`: `.` is rebound to the current element, so the root context needs `$`. This is the single most common error when writing these blocks.

- [ ] **Step 3: Verify the package set is unchanged**

Run the Task 2 Step 3 loop again.

Expected: no output. This is the step that catches a mis-transcribed gate — for instance, `profiles = ["work"]` on a package that was previously unrestricted silently removes it from every personal machine, and the `personal-*` baselines will show it.

- [ ] **Step 4: Verify the macOS-gated cells on macOS**

The Linux baselines cannot exercise `eq .chezmoi.os "darwin"`, so the cask and macOS-formulae blocks are unverified by Step 3.

Run Task 1 Step 3 and Task 2 Step 3 on a macOS machine, or rely on the CI job added in Task 4, which runs the same harness on `macos-latest`. Do not mark this task complete on Linux evidence alone.

- [ ] **Step 5: Commit**

```bash
git add home/.chezmoidata/packages.toml home/dot_config/dotfiles/Brewfile.tmpl
git commit -m "refactor(packages): declare the gated packages in packages.toml

Brewfile.tmpl is now fully generated. Gating moves from hand-written template
conditionals into optional profiles/os/secrets fields on each entry, so a
package's audience is declared next to the package rather than implied by
which block it happens to sit in.

Verified across all 16 Linux data cells plus the macOS cells in CI; no package
gained or lost.

Assisted-by: AI"
```

---

### Task 4: Fail CI when the package set drifts

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `tests/brewfile-expected/` — one file per data cell

**Interfaces:**
- Consumes: `tests/brewfile-parity.sh`.

- [ ] **Step 1: Commit the expected sets**

```bash
mkdir -p tests/brewfile-expected
for p in work personal; do
  for d in true false; do
    for s in none bitwarden 1password both; do
      CHEZMOI=/home/coder/.local/bin/chezmoi \
        ./tests/brewfile-parity.sh "$p" "$d" "$s" \
        > "tests/brewfile-expected/linux-$p-$d-$s.txt"
    done
  done
done
```

These are the reviewed output of Tasks 2 and 3, not a fresh baseline. A PR that changes a package changes one of these files, which is the point: the diff is visible in review.

- [ ] **Step 2: Add the CI job**

```yaml
  brewfile-parity:
    name: brewfile-parity (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
    env:
      CHEZMOI_VERSION: v2.72.2
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Install chezmoi
        run: |
          set -euo pipefail
          sh -c "$(curl -fsSL get.chezmoi.io)" -- -b "$HOME/.local/bin" "$CHEZMOI_VERSION"
          echo "$HOME/.local/bin" >> "$GITHUB_PATH"

      # macOS is not optional here: .chezmoi.os cannot be overridden from a
      # config file, so the cask and macOS-formulae blocks are only exercised
      # on a macOS runner. A Linux-only check would pass while those blocks
      # were broken.
      - name: Check the rendered package set
        run: |
          set -euo pipefail
          plat=linux; [ "$RUNNER_OS" = "macOS" ] && plat=darwin
          fail=0
          for p in work personal; do
            for d in true false; do
              for s in none bitwarden 1password both; do
                exp="tests/brewfile-expected/$plat-$p-$d-$s.txt"
                if ! ./tests/brewfile-parity.sh "$p" "$d" "$s" | diff -u "$exp" -; then
                  echo "DRIFT: $plat/$p/$d/$s"; fail=1
                fi
              done
            done
          done
          exit "$fail"
```

- [ ] **Step 3: Generate the macOS expectations**

The `darwin-*` files cannot be produced on Linux. Let the job fail once on `macos-latest`, take the rendered output from the failing diff, commit it as `tests/brewfile-expected/darwin-*.txt`, and confirm the job goes green.

Do not hand-write these files; they must be what chezmoi actually renders.

- [ ] **Step 4: Verify the check catches a real change**

Add a throwaway package to `packages.toml`, push, and confirm `brewfile-parity` fails on both runners with the new entry visible in the diff. Then remove it.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml tests/brewfile-expected
git commit -m "ci: fail when the rendered Brewfile package set drifts

Nothing verified that a template edit did not silently add or drop a package.
The expected sets are committed per data cell, so a PR that changes what gets
installed shows that change as a reviewable diff rather than as a surprise on
the next machine to run chezmoi apply.

Runs on macOS as well as Linux: .chezmoi.os cannot be overridden from a config
file, so the cask and macOS-formulae blocks are unexercised on a Linux runner.

Assisted-by: AI"
```

---

## Self-Review

**Spec coverage.** Section 1 (the manifest) is Tasks 2 and 3. Section 2 (tiers) is carried as a `tiers` field on every entry, but nothing consumes it yet — tier *selection* arrives with the image plan, and declaring it now means that plan adds a consumer rather than re-touching every entry. Section 3's Brewfile row is Task 3; its `tools.txt`, Pi apt list and bootstrap list rows are explicitly deferred.

**Deviation recorded.** The byte-identical requirement is replaced with package-set parity, justified above by the existing file's non-uniform alignment.

**Placeholders.** Tasks 2 and 3 say "continue for every entry" rather than listing all 53. That is transcription of an existing file rather than invention, the shape is fully specified by worked examples of each variant, and the parity check in Step 3 catches a transcription error mechanically. The alternative is a 53-entry code block no one would read.

**Type consistency.** `tests/brewfile-parity.sh <profile> <display> <secrets>` has the same signature in Tasks 1, 2, 3 and 4. Field names `key`, `section`, `tiers`, `comment`, `brew`, `cask`, `apt`, `cargo`, `go`, `uv`, `profiles`, `os`, `secrets` are consistent throughout.

**Known gaps.**

- `.chezmoi.os` cannot be set from a config file, so macOS cells depend on a macOS runner. Task 3 Step 4 says not to close the task on Linux evidence.
- `.chezmoiexternal.toml` still gates the `requesty` archive on `.profile` independently. Folding it in is a small follow-up, deliberately not bundled here.

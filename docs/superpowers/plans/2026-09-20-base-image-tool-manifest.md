# Base Image Tool Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate `images/base/tools.txt` from `packages.toml`, then expand the base image to the whole `core` and `quality` tiers, so every workspace starts with the preferred toolset already present.

**Architecture:** The Dockerfile gains an early shallow clone of dotfiles and renders `tools.txt` with `chezmoi execute-template --source`, which loads `.chezmoidata` from an arbitrary checkout. The committed `tools.txt` is then deleted — one manifest, rendered at build time, no cross-repo sync. `install-tools.sh` grows zip and tag-prefixed-release support so `bws` can be baked instead of compiled.

**Tech Stack:** chezmoi v2.72 Go templates, TOML, Docker BuildKit, POSIX shell.

**Spec:** `docs/superpowers/specs/2026-09-20-unified-package-manifest-design.md` — section 3's `tools.txt` row, and section 2's tier table.

**Depends on:** `docs/superpowers/plans/2026-09-20-package-manifest.md`. `packages.toml` must exist and drive the Brewfile before this plan starts.

## Global Constraints

- Markdown follows one sentence per line; never column-wrap prose.
- Commit messages are Conventional Commits and end with the trailer `Assisted-by: AI`.
- PR bodies end with `---` then `🤖 Built with AI assistance.`
- Never name a model, vendor or product in a commit or PR.
- Branch work happens in a git worktree under `.worktrees/<branch-name>`; never commit to `main`.
- Language toolchains stay out of the base image. `rust`, `go` and `node` are project tiers per the spec's table; nothing in this plan adds them.

## The feasibility question, already answered

`chezmoi execute-template --source <path>` loads `.chezmoidata` from that path, verified:

```console
$ echo '{{ if .permissions }}HAS_DATA{{ else }}NO_DATA{{ end }}' > probe.tmpl
$ chezmoi execute-template --source ~/.local/share/chezmoi/home --config cfg.toml < probe.tmpl
HAS_DATA
```

So the image can render a manifest-derived file from a dotfiles checkout without chezmoi being initialized against it.

Unlike the Brewfile, `tools.txt` **can** be reproduced byte-identically: its format is `name|repo|template[|arm64template]` with no alignment or comments on data lines. Task 1 asserts exactly that.

## File Structure

| File | Repo | Responsibility |
| ---- | ---- | -------------- |
| `home/.chezmoidata/packages.toml` | dotfiles | Gains `github` channel fields |
| `home/dot_config/dotfiles/tools.txt.tmpl` | dotfiles | Renders the GitHub-release manifest from `.packages` |
| `images/base/Dockerfile` | templates | Clones dotfiles early, renders `tools.txt`, installs from it |
| `images/base/install-tools.sh` | templates | Gains zip and tag-prefixed-release support |
| `images/base/tools.txt` | templates | **Deleted** in Task 2 |

---

### Task 1: Render the existing tools.txt from the manifest

**Files:**
- Modify: `home/.chezmoidata/packages.toml`
- Create: `home/dot_config/dotfiles/tools.txt.tmpl`

**Interfaces:**
- Consumes: `.packages` from the package-manifest plan.
- Produces: a `github` table on a package entry with keys `repo`, `bin`, `asset`, and optional `asset_arm64`. Tasks 2 and 4 rely on these names.

- [ ] **Step 1: Capture the current tools.txt as the target**

```bash
curl -fsSL -o /tmp/tools-baseline.txt \
  https://raw.githubusercontent.com/nickvigilante/homelab-dev-templates/main/images/base/tools.txt
grep -cE '^[a-z]' /tmp/tools-baseline.txt
```

Expected: `11` — `rg`, `fd`, `eza`, `bat`, `gh`, `delta`, `lazygit`, `fzf`, `gum`, `nvim`, `rtk`.

- [ ] **Step 2: Add github channels to the eleven entries**

In `home/.chezmoidata/packages.toml`, add a `github` table to each of those packages. Copy `repo` and `asset` verbatim from the baseline, and set `bin` to the binary name, which is not always the package key:

```toml
[[packages]]
key     = "ripgrep"
section = "cli"
brew    = "ripgrep"
apt     = "ripgrep"
comment = "Fast grep (rg)"
tiers   = ["core"]
github  = { repo = "BurntSushi/ripgrep", bin = "rg", asset = "ripgrep-{VER}-{ARCH_GNU}-unknown-linux-musl.tar.gz" }

[[packages]]
key     = "rtk"
section = "cli"
brew    = "rtk"
comment = "LLM token-saving CLI proxy (Claude Code Bash hook)"
tiers   = ["core"]
github  = { repo = "rtk-ai/rtk", bin = "rtk", asset = "rtk-{ARCH_GNU}-unknown-linux-musl.tar.gz", asset_arm64 = "rtk-{ARCH_GNU}-unknown-linux-gnu.tar.gz" }
```

`neovim` is the entry whose `bin` is `nvim`, and `git-delta`'s is `delta`. Getting `bin` wrong makes `install-tools.sh` fail with "could not find a binary", which is loud rather than silent.

- [ ] **Step 3: Write the template**

Create `home/dot_config/dotfiles/tools.txt.tmpl`. Reproduce the baseline's comment header verbatim, then emit one line per package that has a `github` channel and sits in a requested tier:

```gotemplate
{{ range .packages -}}
{{ if .github -}}
{{ .github.bin }}|{{ .github.repo }}|{{ .github.asset }}{{ if .github.asset_arm64 }}|{{ .github.asset_arm64 }}{{ end }}
{{ end -}}
{{ end -}}
```

Order the entries in `packages.toml` so this renders the baseline's order.

- [ ] **Step 4: Verify byte-identical output**

```bash
chezmoi execute-template \
  --source "$PWD/home" \
  --config <(printf '[data]\nprofile="personal"\nname="x"\nemail=""\nmachine="ephemeral"\ndisplay=false\nsecrets="none"\n') \
  < home/dot_config/dotfiles/tools.txt.tmpl > /tmp/tools-rendered.txt
diff -u /tmp/tools-baseline.txt /tmp/tools-rendered.txt
```

Expected: no output. Unlike the Brewfile this really is byte-identical, because the format has no alignment to reproduce. Do not proceed past a non-empty diff.

- [ ] **Step 5: Commit**

```bash
git add home/.chezmoidata/packages.toml home/dot_config/dotfiles/tools.txt.tmpl
git commit -m "feat(packages): render the image tool manifest from packages.toml

The base image's tools.txt was a second, independent declaration of what
software a machine gets. It now renders from the same manifest as the
Brewfile, so rtk is declared once rather than in two repositories.

Output is byte-identical to the committed tools.txt: unlike the Brewfile,
this format has no alignment or trailing comments to reproduce.

Assisted-by: AI"
```

---

### Task 2: Render tools.txt during the image build

**Files:**
- Modify: `images/base/Dockerfile:65-66` (repo: `nickvigilante/homelab-dev-templates`)
- Delete: `images/base/tools.txt`

**Interfaces:**
- Consumes: `home/dot_config/dotfiles/tools.txt.tmpl` from Task 1.

- [ ] **Step 1: Clone dotfiles and render before installing**

`tools.txt` is consumed at line 66, long before the existing `chezmoi init --apply` at line 111, so the manifest needs its own early checkout. chezmoi is already on `PATH` from line 36.

Replace:

```dockerfile
COPY tools.txt install-tools.sh /tmp/
```

with:

```dockerfile
# tools.txt is rendered from the dotfiles package manifest rather than kept
# here, so the image and the Brewfile cannot disagree about what a machine
# gets. This is a separate shallow checkout from the `chezmoi init --apply`
# further down: that one runs as `coder` much later, and tools are installed
# as root before it.
RUN git clone --depth=1 --branch "${DOTFILES_REF}" \
      https://github.com/nickvigilante/dotfiles.git /tmp/dotfiles-manifest \
 || git clone --depth=1 https://github.com/nickvigilante/dotfiles.git /tmp/dotfiles-manifest \
 && git -C /tmp/dotfiles-manifest checkout "${DOTFILES_REF}"

RUN printf '[data]\nprofile="personal"\nname="Coder Workspace"\nemail=""\nmachine="ephemeral"\ndisplay=false\nsecrets="none"\n' \
      > /tmp/manifest-data.toml \
 && chezmoi execute-template \
      --source /tmp/dotfiles-manifest/home \
      --config /tmp/manifest-data.toml \
      < /tmp/dotfiles-manifest/home/dot_config/dotfiles/tools.txt.tmpl \
      > /tmp/tools.txt \
 && test -s /tmp/tools.txt

COPY install-tools.sh /tmp/
```

The `--branch` fallback exists because `DOTFILES_REF` may be a commit SHA, which `git clone --branch` rejects.

The `test -s` matters: an empty render would otherwise install nothing and produce a silently toolless image.

- [ ] **Step 2: Point the installer at the rendered file**

Change the install invocation's argument from `/tmp/tools.txt` as copied to `/tmp/tools.txt` as rendered — the path is the same, so only the `COPY` changes. Confirm the `RUN --mount=type=secret` block still passes `/tmp/tools.txt`.

- [ ] **Step 3: Delete the committed manifest**

```bash
git rm images/base/tools.txt
```

- [ ] **Step 4: Verify the image builds and has the tools**

```bash
docker build -t base-manifest-check images/base
docker run --rm base-manifest-check sh -c 'for t in rg fd eza bat gh delta lazygit fzf gum nvim rtk; do printf "%-9s %s\n" "$t" "$(command -v $t || echo MISSING)"; done'
```

Expected: eleven paths under `/usr/local/bin`, no `MISSING`. This is the assertion that the rendered manifest produced the same image as the committed one.

- [ ] **Step 5: Commit**

```bash
git add images/base/Dockerfile
git commit -m "feat(base): render tools.txt from the dotfiles package manifest

Removes the second declaration of what software a machine gets. The image now
renders its tool list from the same packages.toml that drives the Brewfile, so
adding a tool is one edit in one repository.

Uses a separate shallow checkout: tools are installed as root well before the
existing chezmoi init --apply runs as coder, so the manifest has to be
available earlier than that.

Assisted-by: AI"
```

---

### Task 3: Teach the installer zip and tag-prefixed releases

**Files:**
- Modify: `images/base/install-tools.sh`

**Interfaces:**
- Produces: optional `archive = "zip"` and `tag_prefix = "<prefix>"` fields on a `github` table.

- [ ] **Step 1: Write a failing check for bws**

`bws` cannot be installed today for two reasons: its assets are `.zip`, and its releases are tagged `bws-v2.1.0` while `releases/latest` returns the repository's Python SDK release.

Add to `packages.toml`:

```toml
[[packages]]
key     = "bws"
section = "secrets"
cargo   = "bws"
comment = "Bitwarden Secrets Manager CLI"
tiers   = ["secrets"]
github  = { repo = "bitwarden/sdk-sm", bin = "bws", tag_prefix = "bws-v", archive = "zip", asset = "bws-{ARCH_GNU}-unknown-linux-gnu-{VER}.zip" }
```

Re-render and run the installer against the new line; expect it to fail resolving the tag.

- [ ] **Step 2: Resolve a tag by prefix**

In `install-tools.sh`, replace the unconditional `releases/latest` lookup with a prefix-aware one:

```sh
  if [ -n "${tag_prefix:-}" ]; then
    tag=$(fetch "https://api.github.com/repos/${repo}/releases?per_page=100" \
      | grep '"tag_name"' \
      | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/' \
      | grep "^${tag_prefix}" | head -n1)
  else
    tag=$(fetch "https://api.github.com/repos/${repo}/releases/latest" \
      | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')
  fi
```

`ver` must strip the prefix, not just a leading `v`:

```sh
  ver=${tag#"${tag_prefix:-v}"}
```

- [ ] **Step 3: Extract zip archives**

Replace the unconditional `tar -xzf` with:

```sh
  case "${archive:-tar.gz}" in
    zip) unzip -q "${workdir}/${asset}" -d "${workdir}" ;;
    *)   tar -xzf "${workdir}/${asset}" -C "${workdir}" ;;
  esac
```

Add `unzip` to the Dockerfile's apt list, since the base image does not carry it.

- [ ] **Step 4: Verify bws installs on both arches**

```bash
docker build -t base-bws-check images/base
docker run --rm base-bws-check bws --version
docker buildx build --platform linux/arm64 -t base-bws-arm64 images/base
```

Expected: a version string, and a successful arm64 build. `bws` publishes `aarch64-unknown-linux-gnu`, so no `asset_arm64` override is needed.

- [ ] **Step 5: Commit**

```bash
git add images/base/install-tools.sh images/base/Dockerfile
git commit -m "feat(base): support zip archives and tag-prefixed releases

bws could not be baked: its assets are zip rather than tar.gz, and its
releases are tagged bws-v* while releases/latest returns the repository's
Python SDK. It was therefore a cargo build, which OOM-killed a 2 GB workspace
mid-install and is what surfaced this whole line of work.

Both behaviours are opt-in per package, so the existing entries are untouched.

Assisted-by: AI"
```

---

### Task 4: Expand the image to the full core and quality tiers

**Files:**
- Modify: `home/.chezmoidata/packages.toml`
- Modify: `images/base/Dockerfile` — apt layer

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Add github channels for the remaining tier members**

Per the spec's tier table, `core` and `quality` still lack: `jq`, `ncdu`, `duf`, `age`, `tree`, `htop`, `wget`, `sd`, `dust`, `bottom`, `hyperfine`, `glow`, `mprocs`, `tldr`, `actionlint`, `shellcheck`, `shfmt`, `taplo`, `yamllint`, `markdownlint-cli2`, `pre-commit`.

Give each either a `github` table or an `apt` name, whichever the project actually ships. `jq`, `wget`, `tree`, `htop`, `ncdu` and `tldr` are in Ubuntu's repositories and belong in the apt layer; the rest publish release binaries.

`yamllint`, `pre-commit` and `markdownlint-cli2` are not Go or Rust binaries — they come from `uv` and `npm`. Declare them with `uv` or `npm` channel fields and install them in the Dockerfile's existing `uv tool install` step rather than through `tools.txt`.

- [ ] **Step 2: Render the apt layer from the manifest too**

Add `home/dot_config/dotfiles/apt-packages.txt.tmpl` emitting one apt name per line for packages in the requested tiers, and have the Dockerfile render and consume it the same way as `tools.txt`.

This removes the third declaration point — the Dockerfile's inline apt list — and is what finally collapses the `git`/`curl`/`wget`/`gnupg` triplication the spec opens with.

- [ ] **Step 3: Verify the image has every core and quality tool**

```bash
docker build -t base-full-check images/base
docker run --rm base-full-check sh -c 'for t in rg fd eza bat gh delta lazygit fzf gum nvim rtk jq ncdu duf age tree htop wget sd dust btm hyperfine glow mprocs tldr actionlint shellcheck shfmt taplo; do printf "%-14s %s\n" "$t" "$(command -v $t || echo MISSING)"; done'
```

Expected: no `MISSING`.

- [ ] **Step 4: Verify the toolchains are absent**

```bash
docker run --rm base-full-check sh -c 'for t in rustc cargo go node; do printf "%-7s %s\n" "$t" "$(command -v $t || echo "absent (correct)")"; done'
```

Expected: all four absent. They are project tiers; a base image carrying a Rust toolchain is the thing this design explicitly rejects.

- [ ] **Step 5: Record the image size change**

```bash
docker images base-full-check --format '{{.Size}}'
```

Record it in the PR body. If it has grown past roughly 2 GB, something from a toolchain tier has leaked in; find it before merging.

- [ ] **Step 6: Commit**

```bash
git add home/.chezmoidata/packages.toml images/base/Dockerfile
git commit -m "feat(base): bake the full core and quality tiers

Every workspace now starts with the preferred toolset present rather than
installing it at runtime, where it died with the container: Linuxbrew lives
under /home/linuxbrew, outside the PVC, so a restart wiped all 109 formulae
and Homebrew itself.

The apt layer renders from the manifest too, which removes the last
independent declaration point and collapses the git/curl/wget/gnupg
triplication.

Toolchains stay out: rust, go and node are project tiers, asserted absent by
the build check.

Assisted-by: AI"
```

---

## Self-Review

**Spec coverage.** Section 3's `tools.txt` row is Tasks 1 and 2; its `os/linux/bootstrap.apt` row is Task 4 Step 2. Section 2's tier table drives Task 4 Step 1, and Task 4 Step 4 asserts the toolchain exclusion it specifies. The Pi apt list stays out: the Pi does not use this image, and folding it in is a dotfiles-only change better done alongside the Brewfile work.

**Placeholders.** Task 4 Step 1 names all 21 remaining packages but does not give each a literal manifest entry, because the correct channel depends on what each project actually publishes and must be checked per package. Every *shape* is given by worked examples in Tasks 1 and 3, and Step 3 verifies the result mechanically.

**Type consistency.** The `github` table's keys — `repo`, `bin`, `asset`, `asset_arm64`, `archive`, `tag_prefix` — are spelled identically in Tasks 1, 3 and 4 and match the shell variables `install-tools.sh` reads.

**Known gaps.**

- Task 2's early clone fetches dotfiles over HTTPS unauthenticated. That is fine while the repository is public; if it is ever made private, this build step breaks and needs a token.
- Task 4 Step 2 renders an apt list but the Dockerfile's apt layer runs before chezmoi is installed at line 36. The render must move after that line, or chezmoi must be installed earlier. Resolve this when implementing rather than assuming the current ordering holds.

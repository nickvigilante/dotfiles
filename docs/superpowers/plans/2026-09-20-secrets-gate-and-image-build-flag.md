# Secrets Gate and Image-Build Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `chezmoi apply` aborting on machines without a Bitwarden vault, and make the image-build flag build-scoped so a future runtime apply is possible.

**Architecture:** Two independent repos, four tasks, no shared code. The dotfiles change is a template-gate fix guarded by a render matrix that runs in CI. The templates changes are a Dockerfile scope fix and a documentation correction.

**Tech Stack:** chezmoi v2.72 Go templates, Docker BuildKit, GitHub Actions, POSIX shell.

**Spec:** `docs/superpowers/specs/2026-09-20-unified-package-manifest-design.md` (sections 5 and 4)

## Global Constraints

- Markdown follows one sentence per line; never column-wrap prose.
- Commit messages are Conventional Commits and end with the trailer `Assisted-by: AI`.
- PR bodies end with `---` then `🤖 Built with AI assistance.`
- Never name a model, vendor or product in a commit or PR.
- Branch work happens in a git worktree under `.worktrees/<branch-name>`; never commit to `main`.
- `chezmoi` is at `/home/coder/.local/bin/chezmoi` in this workspace; use `chezmoi` if it is on `PATH`.

## Scope

In scope: the secrets gate, its CI guard, the `ENV`→`ARG` change, and the stale auto-push claim in the README.

Out of scope, each getting its own plan:

- The `packages.toml` manifest, renderer and generated consumers.
- Tiers, the `toolset` parameter, and runtime `chezmoi apply` in `startup.sh`.
- Template delivery automation.
  `coder.vigihome.net` resolves only to `192.168.50.135` and `100.92.2.25`, so GitHub-hosted runners cannot reach it and `template-push.yml` needs a connectivity decision first.

## File Structure

| File | Repo | Responsibility |
| ---- | ---- | -------------- |
| `home/.chezmoiignore` | dotfiles | Decides whether the kubeconfig template renders at all |
| `tests/chezmoiignore-matrix.sh` | dotfiles | Asserts the gate's behavior across the data matrix |
| `.github/workflows/ci.yml` | dotfiles | Runs the matrix on every PR |
| `images/base/Dockerfile` | homelab-dev-templates | Scopes `DOTFILES_IMAGE_BUILD` to build time |
| `templates/Base/README.md` | homelab-dev-templates | Documents how a template actually reaches Coder |

---

### Task 1: Guard and fix the secrets gate

**Files:**
- Create: `tests/chezmoiignore-matrix.sh`
- Modify: `home/.chezmoiignore:14-16`

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/chezmoiignore-matrix.sh <path-to-template>`, exit 0 when every cell matches, 1 otherwise. Task 2 runs this exact command.

- [ ] **Step 1: Write the failing test**

Create `tests/chezmoiignore-matrix.sh`:

```bash
#!/usr/bin/env bash
# Render .chezmoiignore across the (profile, machine, secrets) matrix and
# assert whether ~/.kube/homelab.yaml is IGNORED (listed) or DEPLOYED (absent).
#
# The kubeconfig template calls the `bitwarden` template function, so a cell
# that renders it on a machine with no Bitwarden vault aborts `chezmoi apply`
# outright and takes the whole environment build down with it.
set -uo pipefail

CHEZMOI="${CHEZMOI:-chezmoi}"
TMPL="${1:?usage: chezmoiignore-matrix.sh /path/to/.chezmoiignore}"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
fail=0

render() { # profile machine secrets cluster_admin
  cat > "$TMP/cfg.toml" <<EOF
[data]
profile = "$1"
name    = "x"
email   = ""
machine = "$2"
display = false
secrets = "$3"
EOF
  WORKSPACE_CLUSTER_ADMIN="${4:-}" "$CHEZMOI" execute-template \
    --config "$TMP/cfg.toml" < "$TMPL" 2>/dev/null \
    | grep -c '^\.kube/homelab\.yaml$'
}

check() { # label profile machine secrets cluster_admin want
  local label="$1" want="$6" got n
  n=$(render "$2" "$3" "$4" "$5")
  [ "$n" -ge 1 ] && got=IGNORED || got=DEPLOYED
  if [ "$want" = "$got" ]; then
    printf '  PASS  %-46s %s\n' "$label" "$got"
  else
    printf '  FAIL  %-46s want %s, got %s\n' "$label" "$want" "$got"
    fail=1
  fi
}

echo "== workstations keep the kubeconfig =="
check "personal/laptop/bitwarden"        personal laptop    bitwarden ""  DEPLOYED
check "personal/desktop/both"            personal desktop   both      ""  DEPLOYED

echo
echo "== no Bitwarden vault, no kubeconfig =="
check "personal/ephemeral/none"          personal ephemeral none      ""  IGNORED
check "personal/laptop/none"             personal laptop    none      ""  IGNORED
check "personal/laptop/1password"        personal laptop    1password ""  IGNORED

echo
echo "== workspaces only with an explicit opt-in =="
check "personal/ephemeral/bitwarden"     personal ephemeral bitwarden ""  IGNORED
check "personal/ephemeral/bitwarden +CA" personal ephemeral bitwarden 1   DEPLOYED

echo
echo "== never on work machines or cluster nodes =="
check "work/laptop/bitwarden"            work     laptop    bitwarden ""  IGNORED
check "personal/server/bitwarden"        personal server    bitwarden ""  IGNORED

echo
[ "$fail" -eq 0 ] && echo "ALL PASS" || echo "FAILURES"
exit "$fail"
```

Then `chmod +x tests/chezmoiignore-matrix.sh`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `CHEZMOI=/home/coder/.local/bin/chezmoi ./tests/chezmoiignore-matrix.sh home/.chezmoiignore`

Expected: exit 1, with exactly these four failures:

```text
  FAIL  personal/ephemeral/none                        want IGNORED, got DEPLOYED
  FAIL  personal/laptop/none                           want IGNORED, got DEPLOYED
  FAIL  personal/laptop/1password                      want IGNORED, got DEPLOYED
  FAIL  personal/ephemeral/bitwarden                   want IGNORED, got DEPLOYED
```

If a different set fails, stop — the template or the data schema has changed since this plan was written.

- [ ] **Step 3: Fix the gate**

In `home/.chezmoiignore`, replace exactly these three lines:

```gotemplate
{{ if or (ne .profile "personal") (eq .machine "server") (env "DOTFILES_IMAGE_BUILD") -}}
.kube/homelab.yaml
{{ end -}}
```

with:

```gotemplate
{{- $vault   := or (eq .secrets "bitwarden") (eq .secrets "both") -}}
{{- $trusted := or (and (eq .profile "personal") (ne .machine "server") (ne .machine "ephemeral")) (env "WORKSPACE_CLUSTER_ADMIN") -}}
{{ if not (and $vault $trusted) -}}
.kube/homelab.yaml
{{ end -}}
```

Leave the existing comment block above it in place, and append to it:

```text
# The gate is positive: the file deploys only where a Bitwarden vault is
# actually configured, because the template calls `bitwarden` specifically —
# secrets = "1password" fails exactly as secrets = "none" does. Ephemeral
# machines are excluded unless their template opts in by setting
# WORKSPACE_CLUSTER_ADMIN, which confines cluster-admin to one designated
# template rather than every workspace.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `CHEZMOI=/home/coder/.local/bin/chezmoi ./tests/chezmoiignore-matrix.sh home/.chezmoiignore`

Expected: exit 0, `ALL PASS`, nine PASS lines.

- [ ] **Step 5: Verify no other target regressed**

Run: `chezmoi status`

Expected: no line mentioning `.kube/homelab.yaml`, and no template error. A `bitwarden` executable-not-found error means the gate is still selecting the file.

- [ ] **Step 6: Commit**

```bash
git add tests/chezmoiignore-matrix.sh home/.chezmoiignore
git commit -m "fix(chezmoi): deploy the kubeconfig only where a Bitwarden vault exists

The ignore rule gated on .profile, .machine and DOTFILES_IMAGE_BUILD but
never on .secrets, so a machine configured with secrets = \"none\" still
rendered private_dot_kube/private_homelab.yaml.tmpl. That template calls the
bitwarden function unconditionally, so chezmoi apply aborted before reaching
the shell config, and the run_after package installer never ran at all.

The gate is now positive: deploy only where a Bitwarden vault is configured,
since secrets = \"1password\" fails identically to none. Ephemeral machines
are excluded unless their template opts in via WORKSPACE_CLUSTER_ADMIN, which
confines a cluster-admin credential to one designated template.

Adds a render matrix over (profile, machine, secrets, cluster-admin) that
fails on four cells before this change and passes on all nine after.

Assisted-by: AI"
```

---

### Task 2: Run the matrix in CI

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `tests/chezmoiignore-matrix.sh` from Task 1.
- Produces: a `chezmoi-matrix` job, required on every PR.

- [ ] **Step 1: Add the job**

In `.github/workflows/ci.yml`, add a sibling to the existing `lint` job. Keep `CHEZMOI_VERSION` identical to the value the `lint` job already pins, so the two cannot drift:

```yaml
  chezmoi-matrix:
    name: chezmoi-matrix
    runs-on: ubuntu-latest
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

      - name: Render .chezmoiignore across the data matrix
        run: ./tests/chezmoiignore-matrix.sh home/.chezmoiignore
```

- [ ] **Step 2: Verify the workflow parses**

Run: `actionlint .github/workflows/ci.yml`

Expected: no output, exit 0. If `actionlint` is not installed, this is covered by the repo's own `actionlint` CI job on the PR.

- [ ] **Step 3: Verify the job would fail on a regression**

Temporarily revert the gate to its pre-Task-1 form, run the script, confirm exit 1, then restore the fix:

```bash
git stash push -m "matrix-regression-check" home/.chezmoiignore
./tests/chezmoiignore-matrix.sh home/.chezmoiignore   # expect exit 1
git stash pop
./tests/chezmoiignore-matrix.sh home/.chezmoiignore   # expect exit 0
```

The stash stack is shared across worktrees, so use the named push above and `git stash list` to confirm you pop your own entry.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: render .chezmoiignore across the data matrix on every PR

Nothing rendered the templates across (profile, machine, secrets) before, so
the personal/ephemeral/none cell shipped broken and took a whole workspace
environment down before anyone noticed.

Assisted-by: AI"
```

---

### Task 3: Scope the image-build flag to build time

**Files:**
- Modify: `images/base/Dockerfile:92` (repo: `nickvigilante/homelab-dev-templates`)

**Interfaces:**
- Consumes: nothing.
- Produces: `DOTFILES_IMAGE_BUILD` absent from the running container's environment.

- [ ] **Step 1: Confirm the flag currently leaks to runtime**

Run:

```bash
docker build -t dotfiles-flag-check images/base
docker run --rm dotfiles-flag-check sh -c 'echo "DOTFILES_IMAGE_BUILD=${DOTFILES_IMAGE_BUILD:-<unset>}"'
```

Expected: `DOTFILES_IMAGE_BUILD=1` — the leak this task removes.

- [ ] **Step 2: Change ENV to ARG**

In `images/base/Dockerfile`, replace:

```dockerfile
ENV DOTFILES_IMAGE_BUILD=1
```

with:

```dockerfile
# ARG, not ENV: this flag must scope to the build only. As ENV it persists
# into the running container, where a runtime `chezmoi apply` would inherit
# it, skip the package installer and ignore the kubeconfig. ARG values are
# still exposed to RUN instructions, so the chezmoi invocation below sees it.
ARG DOTFILES_IMAGE_BUILD=1
```

- [ ] **Step 3: Verify the flag still reaches the build**

Run:

```bash
docker build --progress=plain -t dotfiles-flag-check images/base 2>&1 | grep -i 'DOTFILES_IMAGE_BUILD set'
```

Expected: the line `DOTFILES_IMAGE_BUILD set; package installation is handled by the image's own Dockerfile. Skipping.` from `run_after_install-packages.sh`. Its absence means the flag stopped reaching `chezmoi` and the build would try to run Homebrew.

- [ ] **Step 4: Verify the flag no longer reaches runtime**

Run:

```bash
docker run --rm dotfiles-flag-check sh -c 'echo "DOTFILES_IMAGE_BUILD=${DOTFILES_IMAGE_BUILD:-<unset>}"'
```

Expected: `DOTFILES_IMAGE_BUILD=<unset>`.

- [ ] **Step 5: Verify no kubeconfig was baked**

Run:

```bash
docker run --rm dotfiles-flag-check sh -c 'ls -la /home/coder/.kube/ 2>&1 || echo "no .kube directory"'
```

Expected: no `homelab.yaml`. This is the security-critical assertion — a published image must never carry a cluster-admin credential.

- [ ] **Step 6: Commit**

```bash
git add images/base/Dockerfile
git commit -m "fix(base): scope DOTFILES_IMAGE_BUILD to the build with ARG

ENV persists into the running container, so a runtime chezmoi apply would
inherit the build-time flag, skip the package installer and ignore the
kubeconfig — silently no-opping the runtime apply the template is moving to.

ARG values are still exposed to RUN instructions, so the chezmoi invocation
below it is unaffected; verified by the installer still reporting that it
skipped, and by the flag reading <unset> inside a running container.

Assisted-by: AI"
```

---

### Task 4: Stop the README claiming automation that does not exist

**Files:**
- Modify: `templates/Base/README.md:19-23` (repo: `nickvigilante/homelab-dev-templates`)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Confirm the claim is false**

Run: `ls .github/workflows/`

Expected: `image-build.yml` and `lint.yml` only. The README names `.github/workflows/template-push.yml`, which does not exist.

- [ ] **Step 2: Correct the text**

Replace:

```text
Merging to `main` on the repo does this automatically via
`.github/workflows/template-push.yml` — manual push is only for local
```

with:

```text
Merging to `main` does NOT push the template to Coder today: there is no
`template-push.yml` workflow, and a GitHub-hosted runner could not reach
`coder.vigihome.net` anyway, since it resolves only to a LAN address and a
Tailscale one. After merging, push manually from a machine on the tailnet.

Bumping the image is a second manual step: `image` in `main.tf` pins a full
SHA, so a freshly built image is not used until that string is updated.
```

- [ ] **Step 3: Verify no other file repeats the claim**

Run: `grep -rn 'template-push' --include='*.md' .`

Expected: only `docs/design.md`, which correctly describes it as planned (Task 7). Any other hit needs the same correction.

- [ ] **Step 4: Commit**

```bash
git add templates/Base/README.md
git commit -m "docs(base): correct the template delivery instructions

The README described merging to main as pushing the template automatically
via .github/workflows/template-push.yml. That workflow was planned as Task 7
and never built, so every merge silently delivered nothing.

Also records the second manual step, since main.tf pins the image by full SHA
and a newly built image goes unused until that string is updated.

Assisted-by: AI"
```

---

## Self-Review

**Spec coverage.** Section 5 (the secrets gate) is Task 1, with Task 2 making it durable. Section 4's `ENV`→`ARG` requirement is Task 3; the rest of section 4, `startup.sh`, is explicitly deferred with the connectivity finding recorded. Sections 1, 2 and 3 are out of scope by the Scope note. Section 6's render matrix is Task 2 for the `.chezmoiignore` half; the `tools.txt` drift check belongs to the manifest plan.

**Placeholders.** None. Every step carries the literal file content, command, and expected output.

**Type consistency.** `tests/chezmoiignore-matrix.sh` takes one positional argument and honors `CHEZMOI`; Task 2 invokes it exactly that way. `WORKSPACE_CLUSTER_ADMIN` is spelled identically in the gate, the test, and the spec.

**Known gap.** Task 3's steps assume a local Docker daemon. This workspace has a `docker` group but no verified daemon, so those steps may need running on a machine that has one, or leaning on the repo's `image-build.yml` CI, which builds both arches on every PR.

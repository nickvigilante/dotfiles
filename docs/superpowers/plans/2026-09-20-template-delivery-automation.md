# Template Delivery Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make merging to `main` actually deliver a template to the Coder deployment, and validate every PR against the live server first.

**Architecture:** Two workflows with deliberately different trust models. PR validation runs on a GitHub-hosted runner that joins the tailnet as an ephemeral node and pushes a non-activated template version, so the Coder provisioner validates it server-side. Delivery runs on a self-hosted runner inside the k3s cluster, triggered only by `push` to `main`, and activates the version. Both authenticate as a dedicated Coder service account rather than a personal session token.

**Tech Stack:** GitHub Actions, actions-runner-controller (`gha-runner-scale-set`), Tailscale GitHub Action v3, Coder CLI v2.37, Helm, k3s.

**Spec:** `docs/superpowers/specs/2026-09-20-unified-package-manifest-design.md` — delivery was added to scope after the spec was written; this plan is its record.

## Global Constraints

- Markdown follows one sentence per line; never column-wrap prose.
- Commit messages are Conventional Commits and end with the trailer `Assisted-by: AI`.
- PR bodies end with `---` then `🤖 Built with AI assistance.`
- Never name a model, vendor or product in a commit or PR.
- Branch work happens in a git worktree under `.worktrees/<branch-name>`; never commit to `main`.
- **The self-hosted runner workflow must never gain a `pull_request` trigger.** Both repos are public, so a fork PR would execute arbitrary code inside the k3s cluster. This is the single constraint the whole design rests on.

## Why two runners

Both repos are `PUBLIC` and `coder.vigihome.net` resolves only to `192.168.50.135` and `100.92.2.25`, neither routable from a GitHub-hosted runner.

| | Validation | Delivery |
| --- | --- | --- |
| Runner | GitHub-hosted + Tailscale | Self-hosted in k3s |
| Trigger | `pull_request` | `push` to `main` only |
| Coder action | `--activate=false` | activates |
| Fork PRs | secrets withheld, step skips | cannot reach it at all |

Fork PRs receive no secrets, so the Tailscale step fails closed and forks get `lint` only.
That is the intended behavior, not a gap.

## File Structure

| File | Responsibility |
| ---- | -------------- |
| `.github/workflows/template-validate.yml` | PR-time server-side validation via a non-activated version |
| `.github/workflows/template-push.yml` | Activates the template on merge to `main` |
| `docs/runner-setup.md` | How the self-hosted runner is provisioned and why it is push-only |
| `templates/Base/README.md` | Documents the delivery path that now exists |

---

### Task 1: Create the Coder service account and repository secrets

**Files:**
- None — this task is deployment and repository configuration.

**Interfaces:**
- Produces: repo secrets `CODER_URL`, `CODER_SESSION_TOKEN`, `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`. Tasks 2 and 4 consume these exact names.

- [ ] **Step 1: Create a dedicated Coder user**

Run from a machine logged into Coder as an owner:

```bash
coder users create --username ci-template-push --email ci-template-push@vigihome.net
```

Do not reuse your personal account. A token issued for `nickv` carries owner permissions into CI.

- [ ] **Step 2: Grant it only the template-admin role**

```bash
coder organizations members edit-roles ci-template-push organization-template-admin
```

Verify:

```bash
coder organizations members list | grep ci-template-push
```

Expected: the row shows `organization-template-admin` and nothing else. This role was confirmed to exist on the deployment as one of six: it carries 23 organization permissions, zero site permissions, and zero user permissions.

- [ ] **Step 3: Issue a token for that user**

```bash
coder tokens create --user ci-template-push --name github-actions --lifetime 8760h
```

Record the printed token. It is shown once.

- [ ] **Step 4: Create a Tailscale OAuth client**

In the Tailscale admin console, create an OAuth client with the `auth_keys` scope and tag `tag:ci`.

Then add an ACL grant so `tag:ci` can reach only the Coder server, not the whole tailnet:

```json
{
  "src": ["tag:ci"],
  "dst": ["100.92.2.25:443"],
  "ip":  ["tcp:443"]
}
```

This scoping is the reason the validation runner is safer than a LAN-resident one, which would reach everything by default.

- [ ] **Step 5: Add the four repository secrets**

```bash
gh secret set CODER_URL --repo nickvigilante/homelab-dev-templates --body "https://coder.vigihome.net"
gh secret set CODER_SESSION_TOKEN --repo nickvigilante/homelab-dev-templates
gh secret set TS_OAUTH_CLIENT_ID --repo nickvigilante/homelab-dev-templates
gh secret set TS_OAUTH_SECRET --repo nickvigilante/homelab-dev-templates
```

The three without `--body` read from stdin so the value stays out of shell history.

- [ ] **Step 6: Verify the token works and is not over-privileged**

```bash
CODER_SESSION_TOKEN=<token> CODER_URL=https://coder.vigihome.net coder templates list
CODER_SESSION_TOKEN=<token> CODER_URL=https://coder.vigihome.net coder users list
```

Expected: the first succeeds and lists `Base`. The second **fails** with a permission error — if it succeeds, the role grant in Step 2 did not take and the token can administer users.

---

### Task 2: Validate every PR against the live Coder server

**Files:**
- Create: `.github/workflows/template-validate.yml`

**Interfaces:**
- Consumes: the four secrets from Task 1.
- Produces: a `template-validate` check on PRs touching `templates/**`.

- [ ] **Step 1: Write the workflow**

```yaml
name: template-validate

# PR-only. Delivery lives in template-push.yml and runs on a self-hosted
# runner; this one stays on a GitHub-hosted runner precisely because it is
# the trigger fork PRs can reach.
on:
  pull_request:
    branches: [main]
    paths: ['templates/**']

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  validate:
    name: validate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false

      # Fork PRs receive no secrets, so this step fails and the job stops
      # before touching the tailnet. Forks get the lint workflow only.
      - name: Join the tailnet
        uses: tailscale/github-action@v3
        with:
          oauth-client-id: ${{ secrets.TS_OAUTH_CLIENT_ID }}
          oauth-secret: ${{ secrets.TS_OAUTH_SECRET }}
          tags: tag:ci

      - name: Install the Coder CLI
        run: curl -fsSL https://coder.com/install.sh | sh -s -- --method standalone

      - name: Confirm the deployment is reachable
        env:
          CODER_URL: ${{ secrets.CODER_URL }}
        run: curl -fsS --max-time 10 "$CODER_URL/healthz"

      # --activate=false makes the Coder provisioner run the Terraform import
      # server-side and reject anything malformed, without making the version
      # live. CI therefore never needs cluster credentials of its own.
      - name: Push a non-activated version
        env:
          CODER_URL: ${{ secrets.CODER_URL }}
          CODER_SESSION_TOKEN: ${{ secrets.CODER_SESSION_TOKEN }}
        run: |
          set -euo pipefail
          coder templates push Base \
            --directory templates/Base \
            --name "pr-${{ github.event.number }}-$(git rev-parse --short HEAD)" \
            --activate=false \
            --yes
```

- [ ] **Step 2: Verify the workflow parses**

Run: `actionlint .github/workflows/template-validate.yml`

Expected: no output, exit 0.

- [ ] **Step 3: Verify it catches a broken template**

On a scratch branch, introduce a deliberate error — change the `kubernetes_deployment_v1` `image` to `ghcr.io/nickvigilante/homelab-dev-templates:definitely-not-a-tag` — open a PR, and confirm `template-validate` fails while `lint` passes.

This is the check's entire justification: `tofu validate` cannot catch it, because the tag is syntactically fine.

- [ ] **Step 4: Confirm the inactive versions are harmless**

```bash
coder templates versions list Base
```

Expected: the `pr-*` versions are listed, and the active version is unchanged. Delete accumulated ones periodically; they cost nothing but clutter.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/template-validate.yml
git commit -m "ci: validate template changes against the live Coder server

tofu validate cannot catch what the Coder provisioner rejects: a bad image
tag, a parameter the server refuses, a provider version mismatch. Pushing a
version with --activate=false makes the provisioner run the import
server-side without making it live, so a PR is checked against the real
deployment.

Runs on a GitHub-hosted runner joined to the tailnet as an ephemeral node,
because coder.vigihome.net resolves only to a LAN and a CGNAT address. Fork
PRs receive no secrets, so the tailnet step fails closed and forks are left
with the lint workflow.

Assisted-by: AI"
```

---

### Task 3: Provision the self-hosted runner in k3s

**Files:**
- Create: `docs/runner-setup.md`

**Interfaces:**
- Produces: a runner scale set named `arc-runner-set`. Task 4 targets it with `runs-on: arc-runner-set`.

- [ ] **Step 1: Install the controller**

```bash
helm install arc \
  --namespace arc-systems --create-namespace \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller
```

- [ ] **Step 2: Create a GitHub App or PAT for runner registration**

A fine-grained PAT scoped to `nickvigilante/homelab-dev-templates` with `Administration: read & write` is sufficient. Store it as `$GH_RUNNER_TOKEN` in your shell, not in a file.

- [ ] **Step 3: Install the runner scale set**

```bash
helm install arc-runner-set \
  --namespace arc-runners --create-namespace \
  --set githubConfigUrl="https://github.com/nickvigilante/homelab-dev-templates" \
  --set githubConfigSecret.github_token="$GH_RUNNER_TOKEN" \
  --set minRunners=0 \
  --set maxRunners=1 \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
```

`minRunners=0` means no runner pod exists between jobs. ARC creates a fresh pod per job and destroys it after, so no state carries between runs — which a long-lived Deployment runner would not give you.

- [ ] **Step 4: Verify the runner registers**

```bash
kubectl get pods -n arc-systems
gh api repos/nickvigilante/homelab-dev-templates/actions/runners --jq '.runners[].name'
```

Expected: the controller pod is `Running`, and the runner scale set appears. With `minRunners=0` the listener is present and runner pods appear only during a job.

- [ ] **Step 5: Verify the runner can reach Coder**

```bash
kubectl run coder-reach-check --rm -it --restart=Never \
  --namespace arc-runners --image=curlimages/curl -- \
  curl -fsS --max-time 10 https://coder.vigihome.net/healthz
```

Expected: `OK`. A failure here means cluster DNS is not resolving the LAN address, and Task 4 will fail the same way.

- [ ] **Step 6: Document it**

Create `docs/runner-setup.md` recording: the two Helm commands above, that `minRunners=0` gives a fresh pod per job, and — most importantly — **why the delivery workflow is `push`-only**. Write that reason out in full; it is the constraint a future change is most likely to break without noticing:

```markdown
## Why template-push.yml has no pull_request trigger

This repository is public. A workflow triggered by `pull_request` runs code
from the PR's branch, including from forks. Because this runner lives inside
the k3s cluster, a `pull_request` trigger here would let any stranger execute
arbitrary code on the cluster control plane, alongside every workspace PVC.

PR-time validation lives in `template-validate.yml`, which runs on a
GitHub-hosted runner. There is never a reason to add `pull_request` here.
```

- [ ] **Step 7: Commit**

```bash
git add docs/runner-setup.md
git commit -m "docs: record the self-hosted runner setup and its push-only constraint

Documents the ARC install, why minRunners=0 gives a fresh pod per job, and
why the delivery workflow must never gain a pull_request trigger: the repo is
public and the runner lives in the cluster, so a fork PR would execute inside
it.

Assisted-by: AI"
```

---

### Task 4: Deliver the template on merge

**Files:**
- Create: `.github/workflows/template-push.yml`

**Interfaces:**
- Consumes: `CODER_URL` and `CODER_SESSION_TOKEN` from Task 1, the `arc-runner-set` from Task 3.

- [ ] **Step 1: Write the workflow**

```yaml
name: template-push

# DELIBERATELY push-only. See docs/runner-setup.md. This job runs on a
# self-hosted runner inside the k3s cluster, and the repository is public, so
# a pull_request trigger would execute fork code on the cluster control
# plane. PR validation is template-validate.yml on a GitHub-hosted runner.
on:
  push:
    branches: [main]
    paths: ['templates/**']

permissions:
  contents: read

concurrency:
  group: template-push
  cancel-in-progress: false

jobs:
  push:
    name: push
    runs-on: arc-runner-set
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Install the Coder CLI
        run: curl -fsSL https://coder.com/install.sh | sh -s -- --method standalone

      - name: Activate the template
        env:
          CODER_URL: ${{ secrets.CODER_URL }}
          CODER_SESSION_TOKEN: ${{ secrets.CODER_SESSION_TOKEN }}
        run: |
          set -euo pipefail
          coder templates push Base \
            --directory templates/Base \
            --name "main-$(git rev-parse --short HEAD)" \
            --yes

      - name: Report the active version
        env:
          CODER_URL: ${{ secrets.CODER_URL }}
          CODER_SESSION_TOKEN: ${{ secrets.CODER_SESSION_TOKEN }}
        run: coder templates versions list Base | head -5
```

`concurrency` without `cancel-in-progress` means two rapid merges queue rather than racing to activate different versions.

- [ ] **Step 2: Verify the workflow parses**

Run: `actionlint .github/workflows/template-push.yml`

Expected: no output, exit 0.

- [ ] **Step 3: Assert the trigger is push-only**

Run: `grep -c 'pull_request' .github/workflows/template-push.yml`

Expected: `0`. Treat any other value as a failed task, not a style nit.

- [ ] **Step 4: Verify end to end**

Merge a no-op change under `templates/` — a comment in `main.tf` is enough — and confirm the workflow runs on `arc-runner-set` and the active version changes:

```bash
coder templates versions list Base
```

Expected: a new `main-<sha>` version, marked active.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/template-push.yml
git commit -m "ci: push the template to Coder on merge to main

Merging previously delivered nothing. The README claimed a template-push.yml
existed; it never did, so every template change since has required a manual
push that was easy to forget.

Runs on the in-cluster self-hosted runner, which can reach the deployment
where a GitHub-hosted runner cannot. Push-only by design: the repo is public
and this runner is inside the cluster, so a pull_request trigger would
execute fork code there.

Assisted-by: AI"
```

---

### Task 5: Document the delivery path that now exists

**Files:**
- Modify: `templates/Base/README.md`

**Interfaces:**
- Consumes: nothing.

- [ ] **Step 1: Replace the delivery section**

The preceding plan corrected this text to say delivery is manual. It is now automated, so replace that paragraph with:

```markdown
Merging to `main` with changes under `templates/` pushes and activates the
template via `.github/workflows/template-push.yml`, which runs on the
self-hosted runner inside the cluster (see `docs/runner-setup.md`).

Pull requests are validated first by `.github/workflows/template-validate.yml`,
which pushes a non-activated version so the Coder provisioner checks it
server-side. Fork PRs skip that check, since they receive no secrets.

Bumping the image is still manual: `image` in `main.tf` pins a full SHA, so a
freshly built image is not used until that string is updated.
```

- [ ] **Step 2: Verify no stale claim remains**

Run: `grep -rn 'manual push\|does NOT push' --include='*.md' .`

Expected: no hits in `templates/Base/README.md`.

- [ ] **Step 3: Commit**

```bash
git add templates/Base/README.md
git commit -m "docs(base): document the automated delivery path

Delivery is automated now, so the manual instructions added while it was not
are themselves stale. Records both workflows and that fork PRs skip
validation by design.

Assisted-by: AI"
```

---

## Self-Review

**Spec coverage.** Delivery was added to scope verbally after the spec was written, so this plan is its record rather than an implementation of an existing section. The image SHA bump stays manual and is called out in Task 5; automating it belongs with the manifest work, where the build and the template reference can move together.

**Placeholders.** None. Every command, workflow and expected output is literal. `organization-template-admin` was confirmed against the live deployment; `coder templates push --activate` was confirmed against the CLI; the Tailscale action's `oauth-client-id`, `oauth-secret` and `tags` inputs and its `auth_keys` scope requirement were confirmed from Tailscale's documentation.

**Type consistency.** Secret names `CODER_URL`, `CODER_SESSION_TOKEN`, `TS_OAUTH_CLIENT_ID` and `TS_OAUTH_SECRET` are spelled identically in Tasks 1, 2 and 4. The runner scale set is `arc-runner-set` in both Task 3's Helm release and Task 4's `runs-on`.

**Known gaps.**

- Task 1 Step 6 asserts `coder users list` fails for the service token. If the deployment's role model permits user listing at organization scope, that assertion needs relaxing to a write operation instead.
- Task 3 Step 5 assumes cluster DNS resolves `coder.vigihome.net` to the LAN address. If it does not, use the in-cluster service instead and accept that the TLS name will not match, or add a hosts entry to the runner pod spec.

# Unified package manifest and runtime dotfiles apply

Status: proposed.
Date: 2026-09-20.
Repos affected: `nickvigilante/dotfiles`, `nickvigilante/homelab-dev-templates`.

## Problem

A Coder workspace built from this stack does not reproduce the laptop environment.
Investigation of a live workspace found the environment almost entirely unbuilt: no `.zshenv`, no `.zshrc`, no `.zprofile`, no `.oh-my-zsh`, and none of the ~100 Brewfile formulae including `rtk` and `git-delta`.

The proximate cause is a single unguarded template.
`home/private_dot_kube/private_homelab.yaml.tmpl` calls the `bitwarden` template function unconditionally, and the `.chezmoiignore` rule that excludes it does not consult `.secrets`.
On a machine configured with `secrets = "none"` there is no `bw` binary, so `chezmoi apply` aborts:

```text
chezmoi: .kube/homelab.yaml: template: private_dot_kube/private_homelab.yaml.tmpl:9:4:
executing at <bitwarden "item" "Homelab Kubeconfig">:
error calling bitwarden: bw get item 'Homelab Kubeconfig': exec: "bw": executable file not found in $PATH
```

Because `run_after_install-packages.sh.tmpl` is a `run_after_` script, it never executes after a failed apply, so no packages install either.
One unguarded secret template takes down the entire environment build.

Two structural problems sit underneath that.

First, image-baked dotfiles never reach a workspace.
`images/base/Dockerfile` runs `chezmoi init --apply` at `USER coder` with `WORKDIR /home/coder`, but `templates/Base/main.tf` mounts the home PVC at `mount_path = "/home/coder"` with no `init_container`, and `startup.sh` is a stub.
Kubernetes PVCs do not copy image content in on first mount the way Docker named volumes do, so every baked file under `$HOME` is masked at runtime.
Tools installed to `/usr/local/bin` survive; configuration under `$HOME` does not.

Second, there is no single place that decides what software a machine gets.
Six independent declaration points exist today, each gated on a different variable.

| Declaration point | Gated on |
| ----------------- | -------- |
| `home/dot_config/dotfiles/Brewfile.tmpl` | `.profile`, `.chezmoi.os`, `.display`, `.secrets` |
| `home/run_after_install-packages.sh.tmpl` | `.machine == "pi"`, `.chezmoi.arch`, `DOTFILES_IMAGE_BUILD` |
| `os/raspberry-pi/packages.apt` | reached only via `.machine == "pi"` |
| `os/linux/bootstrap.apt` | every Linux machine, untemplated |
| `home/.chezmoiexternal.toml` | `.profile == "personal"` |
| `images/base/tools.txt` | image build only |

`git`, `curl`, `wget`, and `gnupg` are each declared in three of these.
`.machine` gates no package content at all, which is why `ephemeral` currently means nothing to the Brewfile.

## Goals

- One manifest decides what software every machine and template gets.
- Per-template package subsets, selected declaratively rather than by editing a list.
- Dotfiles reliably reach a Coder workspace.
- A machine configured without a vault applies cleanly.

## Non-goals

- Replacing Homebrew, apt, or the GitHub-release installer.
  The manifest describes packages; existing installers still install them.
- Migrating the `docker` and `scratch` templates.
  This design must not block that, but it is out of scope.
- Automating the image SHA bump in `templates/Base/main.tf`.

## Design

### 1. The manifest

`home/.chezmoidata/packages.toml` becomes the single source of truth.
This follows the precedent already established by `.chezmoidata/permissions.toml`, which generates the Claude Code allowlist in `dot_claude/settings.json.tmpl`.
The documented rule for that file applies here unchanged: edit the data, never the generated output.

Each package is declared once, carrying every channel it is available through and the tiers it belongs to.

```toml
[packages.ripgrep]
brew   = "ripgrep"
apt    = "ripgrep"
github = { repo = "BurntSushi/ripgrep", bin = "rg", asset = "ripgrep-{TAG}-{ARCH_GNU}.tar.gz" }
tiers  = ["core"]

[packages.rtk]
brew  = "rtk"
tiers = ["core"]

[packages.ollama]
installer = "https://ollama.com/install.sh"
tiers     = ["ml"]
profiles  = ["personal"]
```

Channel fields are optional and describe availability, not preference.
A package with only `brew` is unavailable on the Pi, and the renderer reports that rather than silently dropping it.

### 2. Tiers

A tier is a named package set.
Tiers are what make `.machine` meaningful and what deliver per-template subsets from one file.
A machine or template declares the tiers it wants, and every consumer renders accordingly.

The governing principle is cost versus generality.
A package earns a place in `core` — and therefore in the base image every workspace pulls — by being small and useful across most work.
A language toolchain is neither: it is large, and it is only useful when the project in front of you is written in that language.
Rust is the clearest case at roughly 1.5 GB, doubled across a multi-arch build, for something most workspaces never invoke.

| Tier | Contents | Delivered by |
| ---- | -------- | ------------ |
| `bootstrap` | apt prerequisites needed before anything else installs | Dockerfile apt layer |
| `core` | small, generally useful CLI — `jq`, `ncdu`, `duf`, `age`, `rg`, `fd`, `bat`, `delta`, `rtk`, `gh`, `fzf`, `gum`, `tree`, `htop`, `wget`, `sd`, `dust`, `bottom`, `hyperfine`, `glow`, `mprocs`, `tldr` | base image |
| `quality` | repo gates — `actionlint`, `shellcheck`, `shfmt`, `taplo`, `yamllint`, `markdownlint-cli2`, `pre-commit` | base image |
| `rust` | `rust`, `cargo-edit` | project template only |
| `go` | `go`, `gopls`, `golangci-lint` | project template only |
| `node` | `node`, `prettier` | project template only |
| `infra` | `opentofu`, `coder` | infra template only |
| `secrets` | `bws`, `bitwarden-cli`, `1password-cli` | gated on `.secrets` |
| `gui`, `work`, `personal` | profile-scoped, largely macOS | workstations only |

`.chezmoi.toml.tmpl` gains a `tiers` field, defaulted from `.machine` and `.profile` so existing machines need no manual answer.
A workstation selects every tier and keeps today's behavior.

The Coder template exposes a `toolset` parameter mapping to a tier list, so a Rust workspace gets the `rust` tier without a separate base image and without every other workspace paying for it.

Claude Code is deliberately absent from this table.
It arrives today through the `claude-code` Coder registry module in `modules.tf`, which also wires up `claude_code_oauth_token`; baking the binary would drop that wiring, so the module stays the delivery mechanism unless that changes.

### 3. Generated consumers

Four outputs render from the manifest.
None are hand-edited.

| Output | Rendered from |
| ------ | ------------- |
| `home/dot_config/dotfiles/Brewfile.tmpl` | `brew` and `cask` fields, tiers for this machine |
| `images/base/tools.txt` | `github` fields, tiers the image bakes |
| `os/raspberry-pi/packages.apt` | `apt` fields, pi tiers |
| `os/linux/bootstrap.apt` | `apt` fields, `bootstrap` tier |

The Dockerfile already clones dotfiles at `DOTFILES_REF`, so `install-tools.sh` reads the manifest from that checkout.
No new inter-repo dependency is introduced and no sync job is required.

Channel selection is a property of the machine, not of a separate list.
The Pi renders its packages to apt because Linuxbrew is unsupported on armv6 and poorly bottled on aarch64; a Coder workspace renders the same packages to brew, which works there.
`run_after_install-packages.sh.tmpl` keeps its Pi branch as an installer detail, but that branch stops being a disjoint package universe and becomes one channel over the shared manifest.
This is what collapses the `git`, `curl`, `wget`, and `gnupg` triplication.

### 4. Runtime apply

`templates/Base/startup.sh` stops being a stub and runs `chezmoi apply` on every workspace start.
Tools stay baked into the image, so startup stays fast; configuration lands at runtime, where the PVC cannot mask it.
A dotfiles change then reaches existing workspaces on restart without an image rebuild.

This requires a fix to the Dockerfile.
`ENV DOTFILES_IMAGE_BUILD=1` persists into the running container, so a runtime apply would inherit the build-time gate, skip the package installer, and ignore the kubeconfig.
Change it to `ARG DOTFILES_IMAGE_BUILD=1` so the flag is build-scoped.

`startup.sh` must not trap the user in a broken workspace.
A failed apply reports loudly and leaves the workspace usable rather than aborting the agent.

### 5. The secrets gate

The kubeconfig template requires Bitwarden specifically, so `secrets = "1password"` fails identically to `secrets = "none"`.
The gate should be positive: deploy the file only where a Bitwarden vault is actually configured.

Cluster access is also narrowed from "every personal machine" to "machines that are supposed to have it".
Workstations keep the kubeconfig as before, and a Coder workspace receives it only when its template explicitly opts in by setting `WORKSPACE_CLUSTER_ADMIN` in the agent environment.

```gotemplate
{{- $vault   := or (eq .secrets "bitwarden") (eq .secrets "both") -}}
{{- $trusted := or (and (eq .profile "personal") (ne .machine "server") (ne .machine "ephemeral"))
                   (env "WORKSPACE_CLUSTER_ADMIN") -}}
{{ if not (and $vault $trusted) -}}
.kube/homelab.yaml
{{ end -}}
```

An image build satisfies neither term, since it sets `machine = ephemeral` and no such env var, so the existing `DOTFILES_IMAGE_BUILD` term becomes redundant for this file.
It is kept anyway as defense in depth, because a published image leaking a cluster-admin credential is the worst outcome in this design.

Coder workspaces are intended to administer the k3s cluster, so ephemeral machines are not excluded wholesale.
Instead exactly one template grants it, which keeps cluster access available without making every workspace an admin.

This matters because the home PVC is backed by k3s local-path storage under `/var/lib/rancher/k3s/storage/`.
A kubeconfig written there persists on a cluster node's own disk, outlives the container that used it, and is readable by every process in the workspace, including agents and any code a cloned repository runs.
Confining that to a single designated template bounds the exposure to workspaces deliberately created for cluster work.

One follow-up is logged rather than resolved here.
Issuing each workspace a scoped ServiceAccount token from the template, instead of the cluster-admin note from Bitwarden, would remove the standing admin credential entirely.
That is a larger change than this design and is tracked separately.

### 6. Testing

Nothing today renders the templates across data combinations, which is how the failing cell shipped.

- A CI matrix runs `chezmoi apply --dry-run` over `(profile × machine × secrets × display)`.
  The `personal / ephemeral / none` cell fails today and would have caught this.
- A drift check regenerates `tools.txt` and the Brewfile from `packages.toml` and fails if either differs from what is committed.
- A smoke test asserts `/usr/local/bin` contains the expected tier binaries after an image build.

## Migration

1. Land the secrets gate fix and the `ARG` change.
   These are independent and unblock workspaces immediately.
2. Add `packages.toml` and the renderer, generating outputs byte-identical to the current committed files.
   Verify by diff, so the refactor proves itself before behavior changes.
3. Switch consumers to the generated outputs and add the drift check.
4. Introduce tiers and the `toolset` parameter.
5. Fill in `startup.sh` and remove the image-time `chezmoi init --apply`.

## Resolved decisions

- Ephemeral machines are not excluded from the kubeconfig wholesale.
  One designated template grants cluster access via `WORKSPACE_CLUSTER_ADMIN`; every other workspace is excluded.
- Language toolchains stay out of the base image.
  `rust`, `go` and `node` are project tiers, selected by the template that needs them, so a workspace that never compiles Rust never pays 1.5 GB for it.
- The Pi folds into the same manifest rather than keeping a disjoint apt list.
  Its channel selection falls out of the per-package `apt` and `brew` fields, so `git` is declared once and rendered to whichever channel the machine uses.

## Open questions

- Where does `bitwarden-cli` land once it is a manifest entry, given `install_bw` currently special-cases Linux?
  Expected to dissolve into the generated Brewfile at stage 2, which is why the pending `install_bw` change is deferred until then.
- Should the designated cluster template later move to a scoped ServiceAccount token instead of a cluster-admin credential?

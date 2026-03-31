#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""
install_packages.py — Cross-platform package installer driven by packages.yaml

Called by chezmoi run scripts to install packages from packages/packages.yaml
using the appropriate package manager for the current system.

Usage (via uv):
  uv run --script scripts/install_packages.py --packages packages/packages.yaml \\
      --profile personal --machine laptop --os darwin

Usage (dry-run to preview what would be installed):
  uv run --script scripts/install_packages.py ... --dry-run
"""

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not available. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def run(cmd: list[str], check: bool = False) -> int:
    """Run a command, print it, return exit code."""
    print(f"  + {' '.join(cmd)}")
    result = subprocess.run(cmd)
    return result.returncode


def cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def detect_linux_distro() -> str:
    """Return the Linux distro ID from /etc/os-release (e.g. 'ubuntu', 'fedora')."""
    os_release = Path("/etc/os-release")
    if os_release.exists():
        for line in os_release.read_text().splitlines():
            if line.startswith("ID="):
                return line.split("=", 1)[1].strip('"').lower()
    return ""


def is_raspberry_pi() -> bool:
    """True if we're running on Raspberry Pi hardware."""
    for path in ["/proc/cpuinfo", "/proc/device-tree/model"]:
        p = Path(path)
        if p.exists():
            try:
                if "Raspberry Pi" in p.read_text():
                    return True
            except OSError:
                pass
    return False


# ─── Package source resolution ────────────────────────────────────────────────

def get_source(pkg: dict, manager: str) -> str | dict | None:
    """Return the source entry for a given package manager, or None."""
    return pkg.get("sources", {}).get(manager)


def applies_to(pkg: dict, profile: str, machine: str) -> bool:
    """True if this package should be installed for the given profile and machine."""
    profiles = pkg.get("profiles")
    machines = pkg.get("machines")
    if profiles and profile not in profiles:
        return False
    if machines and machine not in machines:
        return False
    return True


def has_system_source(pkg: dict, has_apt: bool, has_dnf: bool) -> bool:
    """True if the package has a source for an available system package manager."""
    sources = pkg.get("sources", {})
    if has_apt and "apt" in sources:
        return True
    if has_dnf and "dnf" in sources:
        return True
    return False


# ─── Install batches ──────────────────────────────────────────────────────────

def install_homebrew(packages: list[str], casks: list[str]) -> None:
    if packages:
        run(["brew", "install"] + packages)
    if casks:
        run(["brew", "install", "--cask"] + casks)


def install_apt(packages: list[str]) -> None:
    if not packages:
        return
    run(["sudo", "apt-get", "update", "-qq"])
    run(["sudo", "apt-get", "install", "-y"] + packages)


def install_dnf(packages: list[str], groups: list[str]) -> None:
    if groups:
        run(["sudo", "dnf", "groupinstall", "-y"] + groups)
    if packages:
        run(["sudo", "dnf", "install", "-y"] + packages)


def install_choco(packages: list[str]) -> None:
    if packages:
        run(["choco", "install", "-y"] + packages)


# ─── Post-install: completions ────────────────────────────────────────────────

def run_post_install(packages: list[dict], profile: str, machine: str,
                     current_os: str) -> None:
    if current_os == "windows":
        return

    completion_dir = Path.home() / ".local" / "share" / "zsh" / "completions"

    for pkg in packages:
        if not applies_to(pkg, profile, machine):
            continue

        completion_cmd = (
            pkg.get("post_install", {})
               .get("completion", {})
               .get("zsh")
        )
        if not completion_cmd:
            continue

        # Check the primary binary exists before trying to generate completions
        binary = shlex.split(completion_cmd)[0]
        if not cmd_exists(binary):
            continue

        pkg_id = pkg["id"]
        dest = completion_dir / f"_{pkg_id}"

        try:
            completion_dir.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                shlex.split(completion_cmd),
                capture_output=True, text=True, check=True
            )
            dest.write_text(result.stdout)
            print(f"  ✓ Wrote zsh completion: {dest}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"  ! Could not generate completion for {pkg_id}: {e}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Install packages from packages.yaml")
    parser.add_argument("--packages", required=True,
                        help="Path to packages.yaml")
    parser.add_argument("--profile", required=True,
                        choices=["personal", "work"],
                        help="Chezmoi profile (personal or work)")
    parser.add_argument("--machine", required=True,
                        choices=["laptop", "desktop", "server", "pi"],
                        help="Machine role")
    parser.add_argument("--os", required=True,
                        help="OS type: darwin | linux | windows")
    parser.add_argument("--os-id", default="",
                        help="Linux distro ID (e.g. ubuntu, fedora)")
    parser.add_argument("--prefer-system-packages", action="store_true",
                        help="On Linux, prefer apt/dnf over Homebrew when both are available")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be installed without doing it")
    args = parser.parse_args()

    packages_path = Path(args.packages)
    if not packages_path.exists():
        print(f"ERROR: packages file not found: {packages_path}", file=sys.stderr)
        sys.exit(1)

    with open(packages_path) as f:
        manifest = yaml.safe_load(f)

    all_packages: list[dict] = manifest.get("packages", [])

    # Platform detection
    current_os = args.os        # 'darwin' | 'linux' | 'windows'
    os_id = args.os_id.lower()  # 'ubuntu' | 'fedora' | 'raspbian' | ''

    if current_os == "linux" and not os_id:
        os_id = detect_linux_distro()

    is_pi     = args.machine == "pi" or is_raspberry_pi()
    is_macos  = current_os == "darwin"
    is_win    = current_os == "windows"
    is_linux  = current_os == "linux"

    has_brew  = cmd_exists("brew")
    has_apt   = cmd_exists("apt-get")
    has_dnf   = cmd_exists("dnf")
    has_choco = cmd_exists("choco")

    print(f"\n==> Platform : {current_os} ({os_id or '—'})")
    print(f"==> Machine  : {args.machine}  Profile: {args.profile}")
    print(f"==> Managers : "
          f"brew={'✓' if has_brew else '✗'}  "
          f"apt={'✓' if has_apt else '✗'}  "
          f"dnf={'✓' if has_dnf else '✗'}  "
          f"choco={'✓' if has_choco else '✗'}")
    if args.prefer_system_packages:
        print("==> Mode     : prefer system packages (apt/dnf over homebrew)")
    print()

    # Buckets
    brew_pkgs:  list[str] = []
    brew_casks: list[str] = []
    apt_pkgs:   list[str] = []
    apt_groups: list[str] = []
    dnf_pkgs:   list[str] = []
    dnf_groups: list[str] = []
    choco_pkgs: list[str] = []

    for pkg in all_packages:
        if not applies_to(pkg, args.profile, args.machine):
            continue

        sources = pkg.get("sources", {})

        # ── Raspberry Pi ──────────────────────────────────────────────────────
        if is_pi:
            # Use pi_apt if present, otherwise fall back to apt
            src = sources.get("pi_apt") or sources.get("apt")
            if src:
                name = src["name"] if isinstance(src, dict) else src
                if isinstance(src, dict) and src.get("group"):
                    apt_groups.append(name)
                else:
                    apt_pkgs.append(name)
            continue

        # ── macOS ────────────────────────────────────────────────────────────
        if is_macos:
            src = sources.get("homebrew")
            if src is None:
                continue
            if isinstance(src, dict):
                if src.get("cask"):
                    brew_casks.append(src["name"])
                else:
                    brew_pkgs.append(src["name"])
            else:
                brew_pkgs.append(src)
            continue

        # ── Windows ──────────────────────────────────────────────────────────
        if is_win:
            src = sources.get("choco")
            if src:
                choco_pkgs.append(src if isinstance(src, str) else src["name"])
            continue

        # ── Linux (non-Pi) ───────────────────────────────────────────────────
        if is_linux:
            has_homebrew_src = "homebrew" in sources
            has_sys_src = has_system_source(pkg, has_apt, has_dnf)

            # Packages with no homebrew entry always go through system manager
            use_system = (not has_homebrew_src) or \
                         (args.prefer_system_packages and has_sys_src)

            if not use_system and has_brew and has_homebrew_src:
                src = sources["homebrew"]
                if isinstance(src, dict):
                    if src.get("cask"):
                        # Casks not supported on Linux — fall through to system
                        use_system = True
                    else:
                        brew_pkgs.append(src["name"])
                        continue
                else:
                    brew_pkgs.append(src)
                    continue

            # System package manager
            if has_apt and "apt" in sources:
                src = sources["apt"]
                name = src["name"] if isinstance(src, dict) else src
                apt_pkgs.append(name)
            elif has_dnf and "dnf" in sources:
                src = sources["dnf"]
                if isinstance(src, dict):
                    if src.get("group"):
                        dnf_groups.append(src["name"])
                    else:
                        dnf_pkgs.append(src["name"])
                else:
                    dnf_pkgs.append(src)

    # ── Dry run ───────────────────────────────────────────────────────────────
    if args.dry_run:
        print("==> DRY RUN — would install:")
        if brew_pkgs:    print(f"  brew install        : {brew_pkgs}")
        if brew_casks:   print(f"  brew install --cask : {brew_casks}")
        if apt_pkgs:     print(f"  apt install         : {apt_pkgs}")
        if apt_groups:   print(f"  apt groups          : {apt_groups}")
        if dnf_pkgs:     print(f"  dnf install         : {dnf_pkgs}")
        if dnf_groups:   print(f"  dnf groupinstall    : {dnf_groups}")
        if choco_pkgs:   print(f"  choco install       : {choco_pkgs}")
        if not any([brew_pkgs, brew_casks, apt_pkgs, apt_groups,
                    dnf_pkgs, dnf_groups, choco_pkgs]):
            print("  (nothing to install)")
        return

    # ── Install ───────────────────────────────────────────────────────────────
    if brew_pkgs or brew_casks:
        print("==> Installing via Homebrew...")
        install_homebrew(brew_pkgs, brew_casks)

    if apt_pkgs or apt_groups:
        print("==> Installing via apt...")
        install_apt(apt_pkgs + apt_groups)

    if dnf_pkgs or dnf_groups:
        print("==> Installing via dnf...")
        install_dnf(dnf_pkgs, dnf_groups)

    if choco_pkgs:
        print("==> Installing via Chocolatey...")
        install_choco(choco_pkgs)

    # Post-install hooks (completion generation, etc.)
    print("\n==> Running post-install hooks...")
    run_post_install(all_packages, args.profile, args.machine, current_os)

    print("\n==> Package installation complete.")


if __name__ == "__main__":
    main()

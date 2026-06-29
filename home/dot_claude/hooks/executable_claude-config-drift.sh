#!/usr/bin/env bash
# SessionStart hook: nudge once a session if ~/.claude has drifted from the
# chezmoi source, so I can run /chezmoi-sync to reconcile.
#
# Deliberately scoped to ~/.claude — this avoids unrelated templated targets
# such as the Bitwarden-rendered ~/.kube/homelab.yaml, whose render fails
# without a vault unlock and would otherwise noise up (or error) the check.
# Never fails the session: any error just means "no nudge".
set -uo pipefail

command -v chezmoi >/dev/null 2>&1 || exit 0

# Presence check only — use `chezmoi status` (not `diff`): `chezmoi diff` on a
# directory argument prints nothing, while `status` reports per-file drift in
# either direction. Any status line means there's something to reconcile.
if chezmoi status ~/.claude 2>/dev/null | grep -q .; then
  echo "⚠️  ~/.claude has drifted from the chezmoi source. Run /chezmoi-sync to review and reconcile (once a session)."
fi

exit 0

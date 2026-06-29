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

# Presence check only — surface that drift exists, not the diff itself.
if chezmoi diff ~/.claude 2>/dev/null | grep -q .; then
  echo "⚠️  ~/.claude has drifted from the chezmoi source. Run /chezmoi-sync to review and reconcile (once a session)."
fi

exit 0

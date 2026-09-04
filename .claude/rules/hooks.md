---
paths:
  - "hooks/**"
---

# Hooks

Sourced from `CONVENTIONS.md` §"Shell scripts and hooks". (`CONVENTIONS.md:102-111`)

- Every `hooks/*.sh` must be executable; CI fails the build on one that is not.
  (`.github/workflows/validate.yml:216-225`)
- `shellcheck` runs over `hooks/*.sh` **and** `scripts/compound-v-*.sh`; both must be clean.
  (`.github/workflows/validate.yml:227-230`)
- Every hook registration carries `"shell": "bash"` — the documented optional field — so these bash
  scripts are not handed to PowerShell on a Windows box with no Git Bash. (`hooks/hooks.json:2`)
- A hook that can block the turn carries a `|| true` suffix in its registration: a syntax error is
  fatal before any in-script trap can run, so the registration itself must neutralize it.
  (`hooks/hooks.json:3`)
- The `PreToolUse` lane guard deliberately carries no `|| true` — a non-zero `PreToolUse` exit is not
  a deny, so copying the `Stop` idiom there would be cargo-culting. (`hooks/hooks.json:4`)
- Shell-command inspection is a supplement, never a replacement: a deny that can be walked around
  (`eval`, an interpreter one-liner, a variable holding the path) leaves the git-derived scope gate as
  the authority. (`hooks/lane-guard.sh:17-23`)
- Without a run's `lane-map.json` the guard resolves no job, fails open, and silently allows every
  write — which is why the guard is a floor and not the enforcement.
  (`skills/compound-v/state-machine.md:166`)

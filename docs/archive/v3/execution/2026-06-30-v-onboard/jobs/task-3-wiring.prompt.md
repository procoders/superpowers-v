# Job task-3-wiring — /v:init suggestion + fail-silent staleness banner line

Plan Task 7. WRITE-allowed: commands/v-init.md, hooks/session-banner.sh, tests/test-session-banner-staleness.sh. The banner line MUST fail silent under `set -euo pipefail`; the bash test must pass; neither selftest may break. Authority: plan "### Task 7" + archaeology constraint 6 (banner fail-silent idiom).

# Probe spec — does the native pre-flight workflow work?

A deliberately small, real question for the three auditors to audit, so the
workflow itself can be watched end to end.

**The change under consideration:** add a `--json` flag to
`scripts/compound-v-dashboard.py resume` so the SessionStart banner and the
PostCompact hook can consume structured output instead of parsing a rendered line.

That is the whole spec. It touches existing code (the dashboard and two hooks), it
has a user-facing surface (what the banner shows), and it names a dependency
(Python's argparse and the hooks' `jq` parsing) — so all three auditors have
something real to say, and each has a different thing to say.

# Task B — docs/routing.svg redrawn for the three tiers

Compound V run `2026-09-03-v3.4.7-readme-clarity`, job `routing-svg`.

SHARED TIER SENTENCES (use these words in prose and in the diagram, so they cannot disagree): DIRECT — a trivial, unambiguous edit: one worker edits, tests the floor, commits; no model routing happens (it is an ordinary commit by whichever model is already in the session). SCOPED — a bounded change: only the tests that reference what changed run, not the whole suite; the Opus reviewer still gates done. SCOPED+ — a small edit on a sensitive path: SCOPED plus a mandatory deep review and a cross-model (Codex) second opinion, with the human accepting. FULL — anything real: recon, three pre-flights (code archaeology, domain expert, library check), plan, manifest, parallel dispatch in isolated worktrees, a three-pass review. MODELS — Opus plans, judges and reviews; Sonnet executes junior slices and the two scanning agents; Codex is an opt-in worker (kernel-sandboxed) and the second opinion; Antigravity and Cursor are opt-in lower-trust workers. THE ONE RULE (Oleg, 2026-09-03): documentation must be clear and simple. Plain words, short sentences, one idea per paragraph, every claim true of the code in HEAD; anything measured, historical or defensive is linked (AGENTS.md, CHANGELOG.md, TROUBLESHOOTING.md), never repeated. Redraw docs/routing.svg per Task B of docs/superpowers/plans/2026-09-03-v3.4.7-readme-clarity.md. Read the current SVG once for size and style, then write a new one: a request enters the triage hook → three boxes DIRECT / SCOPED (+SCOPED+) / FULL → one line 'every write checked by the git-derived scope gate; an Opus review gates done'; legend for the models. Validate with python xml.etree before returning. Touch only docs/routing.svg. Read the pre-flight audits named in this manifest's audits block first (their §7 MUSTs bind). Run python with -B; register your lane with a literal --cwd. You are unattended: decide and return; if you approach your turn budget, commit what is complete and return a summary that says what is not. DIRECT gets NO model box (pre-flight 1A: a DIRECT decision never reaches the routing table). Rewrite the SVG's <title> and <desc> too — the XML text-node check reads them.

## You are unattended

No one reads this session while it runs and no one will answer a question:
a turn that ends by asking for confirmation, approval or a preference does
NOTHING, and the job is then recorded as an absent implementation. Decide
with the spec, the plan and this prompt; when they are silent, choose the
smallest change that meets the acceptance, do it, run the checks, and return.

## Write-allowed (your lane — anything else is a scope violation)

- `docs/routing.svg`

## Read-allowed (advisory — git cannot enforce reads)

- `**`

## Acceptance (your definition of done)

- docs/routing.svg is valid XML with a viewBox and no external references; its text nodes name the triage hook, DIRECT, SCOPED (with SCOPED+), FULL, what runs in each, and the models (Opus judge/review, Sonnet junior slices and scans, Codex opt-in worker or second opinion), plus one line on the scope gate and the Opus review; nothing about a 'fast path' or an 'advisor'; renders legibly at 900 px wide (system font, ≥12 px text). <title>/<desc> rewritten; DIRECT carries no model.

Turn cap: 50 (default for tier standard; default light 30 / standard 50 / deep 80). Plan to finish inside it.

## What you must NOT report

Do not report `blocked`, `files_changed` or `violations`. Those are
enforcement fields, they are derived from git by the caller, and a
constrained party filling in its own enforcement fields is the
fabricated-evidence pattern.

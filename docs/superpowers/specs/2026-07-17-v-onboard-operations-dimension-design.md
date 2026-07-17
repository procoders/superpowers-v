# /v:onboard — Operations / Deployment coverage dimension (design)

> Fixes a coverage blind spot in the `/v:onboard` pipeline: it never documents the
> CI/CD + DevOps layer of a project. Adds an explicit **Operations / Deployment**
> dimension that produces a cited `docs/superpowers/architecture/operations.md`.
> Authority doc: [`skills/compound-v/onboarding.md`](../../../skills/compound-v/onboarding.md).
> Base design of record: [`2026-06-30-v-onboard-design.md`](2026-06-30-v-onboard-design.md).

## 1. Problem

`/v:onboard` builds a citation-verified architecture KB but silently skips the
operations layer. Confirmed against the code:

- **PACK includes the raw material.** `scripts/compound-v-onboard.py` `_exclude_reason`
  drops only vendored / generated / binary paths — so `docker/**`, `.github/workflows/*`,
  Terraform, and deploy scripts all reach EXTRACT. The material is available, not excluded.
- **DETECT never inventories it.** `onboarding.md` §1 inventories existing instruction
  files, stack, git remote, UI presence (`detect-ui`), style configs, cross-tool signal,
  and nested instruction files — but **not** CI/CD pipelines, Dockerfiles/compose, or
  deploy scripts.
- **EXTRACT has no home for it.** Claim types are `architecture | business-logic |
  tech-context | convention`; nothing prompts deployment/infra/CI-CD coverage. The fixed
  arch doc set is `architecture.md` / `business-logic.md` / `tech-context.md`.
- **`.github` appears only as untrusted `copilot-instructions` and as a high-impact
  taxonomy path** — never as a documentation dimension.

**Net effect:** unless the operator hand-adds an ops step, Docker topology, GitHub Actions
deploy, production domain, and runbooks are silently dropped from the generated KB —
becoming confident partial truth downstream (the exact failure PACK's "silently dropped
relevant file" caveat warns about).

## 2. Scope

- **In:** the `/v:onboard` pipeline only — DETECT, EXTRACT, a new conditional
  `operations.md`, the WRITE surface, and the refresh/staleness manifest; a deterministic
  `detect-ops` subcommand + selftest; the spec artifacts table.
- **Out:** the brainstorm→execute pre-flights (`code-archaeologist`, `domain-expert`,
  `doc-validator`) are a separate subsystem and are **not** touched. No infra
  provisioning, no secret extraction into the doc (the existing `scan-output` blocking
  gate already refuses credentials in generated files). No `verify-citations` change —
  the claim `type` field is free-form data there.

## 3. Decisions (resolved during brainstorm)

1. **Gating = deterministic `detect-ops` subcommand**, mirroring `detect-ui` — not a
   prose-only DETECT glob. Consistent with how `detect-ui` gates `DESIGN.md`.
2. **A 5th claim type `operations`** (not a `tech-context` reuse) — operations claims
   target `operations.md`. Cleanest `type → doc` mapping; free-form `type` means no
   `verify-citations` change.
3. **Onboarding pipeline only** — no new pre-flight agent.
4. **The "include DevOps?" ask lives at the HUMAN GATE (§6)**, not at DETECT.
   `operations.md` is generated then presented as its own explicit per-artifact confirm.
   A fully autonomous / unattended run (auto-approve / `--permission-mode dontAsk` —
   today the headless marathon, or any future autonomous onboarding cycle) auto-approves
   it, exactly as the gate already handles every other artifact. No separate
   autonomous-mode wiring is needed.

## 4. Design

### 4.1 `detect-ops` (deterministic, `scripts/compound-v-onboard.py`)

Mirrors `detect_ui`, but ops has sub-categories, so it returns a small dict rather than a
bare bool:

```
detect_ops(repo) -> {
  "present":    bool,          # true iff any category non-empty
  "ci_cd":      [paths...],
  "containers": [paths...],
  "deploy":     [paths...],
}
```

Signal set (documented in-code; matched against `_git_tracked(repo)` + well-known paths):

- **CI/CD:** `.github/workflows/*.yml|*.yaml`, `.gitlab-ci.yml`, `.circleci/config.yml`,
  `Jenkinsfile`, `azure-pipelines.yml`, `.travis.yml`, `bitbucket-pipelines.yml`.
- **Containers / infra:** `Dockerfile` (+ `Dockerfile.*`, nested `**/Dockerfile`),
  `docker-compose*.yml|.yaml`, `compose.yml|.yaml`, `*.tf` / `*.tfvars`, and k8s
  heuristics (`k8s/` dir, `kustomization.yaml`, Helm `Chart.yaml`). k8s detection is a
  filename/dir heuristic and is documented as such — honest about its limits, like the
  DESIGN.md linter caveats.
- **Deploy / PaaS:** `Procfile`, `fly.toml`, `vercel.json`, `netlify.toml`, `render.yaml`,
  `serverless.yml`, `app.yaml`, `deploy*.sh`.

CLI wiring (mirrors `detect-ui`):

- `add_parser("detect-ops")` with `--repo` (default `.`) and `--json`.
- `main()`: `detect-ops` prints `ops` / `no-ops` by default; with `--json`, prints the
  grouped inventory dict. Exit 0.
- **Selftest** in the existing selftest block: `detect_ops(...)["present"] is True` on a
  fixture containing a `.github/workflows/ci.yml` (or `Dockerfile`); `... is False` on a
  bare tree — matching the shape of the existing `detect_ui` true/false selftests.

### 4.2 `onboarding.md` authority-doc edits

- **§1 DETECT** — add an **Operations / Deployment** bullet: run
  `python3 scripts/compound-v-onboard.py detect-ops --repo . --json`; inventory the three
  categories. Silent inventory, like `detect-ui` — the inclusion *ask* is at the gate, not
  here. This is the deterministic gate for the `operations.md` branch.
- **§3 EXTRACT** — claim `type` enum becomes
  `architecture | business-logic | tech-context | convention | operations`. Operations
  claims carry `target_doc_section` pointing at `operations.md`. Load-bearing rules still
  bite: a deploy-secret path, a production/branch deploy gate, or a fail-closed CI check is
  **load-bearing** (`security` / `fail-closed`) and blocks on unsupported per the existing
  two-tier gate.
- **New "operations.md" section** (parallel to the CONVENTIONS.md / DESIGN.md section) —
  `operations.md` is generated **only when `detect-ops` is `ops`**; on a repo with no ops
  files it is **skipped** (verify this negative path on a non-ops dogfood, mirroring the
  DESIGN.md negative-path note). Read-then-cite from real workflow / Docker / deploy files.
  Covers: container topology, CI/CD stages, deploy target + production domain, runbook
  pointers. Never extracts a credential into the doc — `scan-output` (§7) still refuses.
- **§6 HUMAN GATE** — `operations.md` is presented as its **own explicit per-artifact
  confirm**, framed with the detected inventory: *"DevOps/deployment tooling detected:
  `<ci_cd / containers / deploy inventory>` — include `operations.md`?"* Decline → the doc
  is dropped and nothing is written for it. Under a fully autonomous / unattended run the
  gate auto-approves it, same as every other artifact — this is the "take them into account
  without asking in an autonomous cycle" behavior, and it needs no new code path.
- **§7 WRITE surface** — add `docs/superpowers/architecture/operations.md` to the approved
  v1 write set. It is a normal cited architecture doc: provenance header, output secret
  gate, commit-before-index all apply unchanged.
- **Refresh / §9 manifest** — `operations.md` is a normal cited arch doc, so it rides the
  existing `.onboard-manifest.json` cited-evidence staleness machinery with no new gate.

### 4.3 Spec `2026-06-30-v-onboard-design.md`

- Add an artifacts-table row:
  `operations.md | docs/superpowers/architecture/ | ops files present, confirmed | citation hybrid (§7)`.
- Note `operations.md` as the **conditional fourth** architecture doc (the durable set is
  three-always + `operations.md`-when-ops), consistent with the Cline Memory Bank framing.

## 5. Files touched

| File | Change |
|---|---|
| `scripts/compound-v-onboard.py` | `detect_ops()` + `detect-ops` CLI parser/output + selftest |
| `skills/compound-v/onboarding.md` | §1 DETECT bullet, §3 EXTRACT type, new operations.md section, §6 gate confirm, §7 write surface, refresh note |
| `docs/superpowers/specs/2026-06-30-v-onboard-design.md` | artifacts-table row + conditional-fourth prose |

No `verify-citations` / claims-schema change. No pre-flight change.

## 6. Verification

- `detect_ops` selftest passes (present-true on fixture, present-false on bare) inside the
  existing `python3 scripts/compound-v-onboard.py selftest` run; whole selftest stays green.
- `detect-ops --json` returns the grouped inventory on a real ops repo (e.g. the Laravel+Vue
  dogfood with `docker/**` + `.github/workflows/ci.yml`); `no-ops` on a bare tree.
- Manual pipeline read-through: an ops repo surfaces the gate confirm and, on approval,
  writes a cited `operations.md`; a non-ops repo skips it (negative path).

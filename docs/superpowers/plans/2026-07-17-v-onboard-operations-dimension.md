# /v:onboard Operations/Deployment Dimension — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit Operations/Deployment coverage dimension to `/v:onboard` so CI/CD, container, and deploy files produce a cited `docs/superpowers/architecture/operations.md`.

**Architecture:** A deterministic `detect-ops` subcommand (mirroring `detect-ui`) inventories CI/CD + container + deploy files. The `onboarding.md` authority doc grows a 5th claim type (`operations`), a conditional `operations.md` doc section, and an explicit per-artifact confirm at the HUMAN GATE. No `verify-citations`/claims-schema change — the claim `type` field is free-form there.

**Tech Stack:** Python 3 stdlib (`os`, `argparse`, `json`), Markdown authority docs. The script has a built-in `--selftest` harness (no pytest).

## Global Constraints

- **No new runtime deps** — `compound-v-onboard.py` is pure Python 3 stdlib. Copy that constraint verbatim.
- **`detect_ops` must work on a non-git temp dir** — the `--selftest` harness runs against `tempfile.mkdtemp()` trees that are not git repos, so detection walks the filesystem (excluding `VENDOR_DIRS`), not `git ls-files`.
- **No `verify-citations` / claims-schema change** — the `type` field is free-form data in that gate; adding the `operations` value touches prose only.
- **Onboarding pipeline only** — do not touch the brainstorm pre-flights (`code-archaeologist` / `domain-expert` / `doc-validator`).
- **The ask lives at the HUMAN GATE (§6)**, not DETECT — `operations.md` is generated then confirmed per-artifact; an unattended/auto-approve run approves it with no new code path.
- **Commit after each task.** Work is on branch `feat/v-onboard-operations-dimension` in the plugin repo (`/Users/koristuvac/.claude/plugins/marketplaces/procoders`).

---

### Task 1: `detect-ops` subcommand + selftest

**Files:**
- Modify: `scripts/compound-v-onboard.py` (add `_ops_category` + `detect_ops` after `detect_ui` at line 217; add selftest checks after the `detect_ui` checks near line 893; add parser after line 1155; add `main()` branch after line 1200)

**Interfaces:**
- Consumes: `VENDOR_DIRS` (line 21), the selftest `check(name, cond)` helper (line 807).
- Produces:
  - `detect_ops(repo: str) -> dict` returning `{"present": bool, "ci_cd": [str], "containers": [str], "deploy": [str]}` (paths repo-relative, `/`-separated, sorted).
  - CLI `detect-ops --repo <dir> [--json]`: prints `ops`/`no-ops` by default; the JSON dict with `--json`. Exit 0.

- [ ] **Step 1: Write the failing selftest checks**

Insert immediately **after** line 893 (`check("detect_ui false on bare", ...)`):

```python
    # detect_ops: CI/CD + container + deploy inventory (walks fs, not git — selftest dirs aren't repos).
    d5b = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d5b, ".github", "workflows"))
        with open(os.path.join(d5b, ".github", "workflows", "ci.yml"), "w") as fh: fh.write("on: push\n")
        with open(os.path.join(d5b, "Dockerfile"), "w") as fh: fh.write("FROM alpine\n")
        with open(os.path.join(d5b, "fly.toml"), "w") as fh: fh.write("app='x'\n")
        r_ops = detect_ops(d5b)
        check("detect_ops present true on ci+docker", r_ops["present"] is True)
        check("detect_ops finds ci_cd workflow", ".github/workflows/ci.yml" in r_ops["ci_cd"])
        check("detect_ops finds container Dockerfile", "Dockerfile" in r_ops["containers"])
        check("detect_ops finds deploy fly.toml", "fly.toml" in r_ops["deploy"])
    finally:
        shutil.rmtree(d5b, ignore_errors=True)
    check("detect_ops present false on bare", detect_ops(tempfile.mkdtemp())["present"] is False)
```

- [ ] **Step 2: Run selftest to verify it fails**

Run: `python3 scripts/compound-v-onboard.py --selftest`
Expected: FAIL/traceback — `NameError: name 'detect_ops' is not defined` (function not yet added).

- [ ] **Step 3: Add `_ops_category` + `detect_ops`**

Insert immediately **after** line 217 (the closing `return False` of `detect_ui`, before the blank line preceding `_design_result_ok`):

```python


def _ops_category(rel: str):
    """Classify a repo-relative path as an operations file, or None. Deterministic signal set;
    k8s detection is a filename/dir heuristic (documented as such — it cannot see manifest content)."""
    low = rel.lower()
    base = low.rsplit("/", 1)[-1]
    # --- CI/CD ---
    if low.startswith(".github/workflows/") and low.endswith((".yml", ".yaml")):
        return "ci_cd"
    if low in (".gitlab-ci.yml", ".circleci/config.yml", ".travis.yml",
               "azure-pipelines.yml", "bitbucket-pipelines.yml"):
        return "ci_cd"
    if base == "jenkinsfile":
        return "ci_cd"
    # --- containers / infra ---
    if base == "dockerfile" or base.startswith("dockerfile."):
        return "containers"
    if (base.startswith("docker-compose") or base.startswith("compose.")) \
            and low.endswith((".yml", ".yaml")):
        return "containers"
    if low.endswith((".tf", ".tfvars")):
        return "containers"
    if base in ("kustomization.yaml", "chart.yaml") or low.startswith("k8s/") or "/k8s/" in low:
        return "containers"
    # --- deploy / PaaS ---
    if base in ("procfile", "fly.toml", "vercel.json", "netlify.toml",
                "render.yaml", "serverless.yml", "app.yaml"):
        return "deploy"
    if base.startswith("deploy") and base.endswith(".sh"):
        return "deploy"
    return None


def detect_ops(repo: str) -> dict:
    """Inventory CI/CD + container/infra + deploy files. Walks the filesystem (excluding VENDOR_DIRS)
    so it works on non-git trees too. `present` is True iff any category matched."""
    found = {"ci_cd": [], "containers": [], "deploy": []}
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in VENDOR_DIRS]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), repo).replace(os.sep, "/")
            cat = _ops_category(rel)
            if cat:
                found[cat].append(rel)
    for k in ("ci_cd", "containers", "deploy"):
        found[k].sort()
    found["present"] = any(found[k] for k in ("ci_cd", "containers", "deploy"))
    return found
```

- [ ] **Step 4: Run selftest to verify detection passes**

Run: `python3 scripts/compound-v-onboard.py --selftest`
Expected: all `detect_ops` checks PASS; the harness still ends green (the CLI branch is exercised in Step 6, so the whole suite passing is fine now).

- [ ] **Step 5: Add the CLI parser**

Insert immediately **after** line 1155 (`sp = sub.add_parser("detect-ui"); sp.add_argument("--repo", default=".")`):

```python
    sp = sub.add_parser("detect-ops"); sp.add_argument("--repo", default="."); sp.add_argument("--json", action="store_true")
```

- [ ] **Step 6: Add the `main()` dispatch branch**

Insert immediately **after** line 1200 (the `return 0` closing the `detect-ui` branch):

```python
    if args.cmd == "detect-ops":
        result = detect_ops(os.path.abspath(args.repo))
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("ops" if result["present"] else "no-ops")
        return 0
```

- [ ] **Step 7: Verify the CLI end-to-end**

Run:
```bash
python3 scripts/compound-v-onboard.py detect-ops --repo . --json
python3 scripts/compound-v-onboard.py detect-ops --repo .
python3 scripts/compound-v-onboard.py --selftest
```
Expected: the `--json` call prints a dict with `"present": true` and this plugin repo's own `.github/workflows/*` under `ci_cd`; the plain call prints `ops`; `--selftest` prints its summary line and exits 0.

- [ ] **Step 8: Commit**

```bash
git add scripts/compound-v-onboard.py
git commit -m "feat(v-onboard): add deterministic detect-ops subcommand + selftest"
```

---

### Task 2: `onboarding.md` — DETECT, EXTRACT, operations.md section, GATE, WRITE, refresh

**Files:**
- Modify: `skills/compound-v/onboarding.md` (§1 DETECT bullet; §3 EXTRACT type enum; new "operations.md" subsection under the CONVENTIONS/DESIGN section; §6 GATE confirm; §7 WRITE surface; §Refresh manifest note)

**Interfaces:**
- Consumes: `detect_ops` CLI from Task 1 (`python3 scripts/compound-v-onboard.py detect-ops --repo . --json`).
- Produces: authority-doc contract that a conditional `docs/superpowers/architecture/operations.md` is generated (gated on `detect-ops`), confirmed at §6, and written/refreshed like any cited arch doc.

- [ ] **Step 1: Add the DETECT Operations/Deployment bullet (§1)**

In `skills/compound-v/onboarding.md`, in the `### 1. DETECT` list, insert a new bullet immediately **after** the UI-presence bullet (the one ending "…decides whether the DESIGN.md branch runs (step 9 / §DESIGN below)."):

```markdown
- **Operations / Deployment presence** via `python3 scripts/compound-v-onboard.py detect-ops
  --repo . --json` → `{present, ci_cd[], containers[], deploy[]}`. Inventories CI/CD
  (`.github/workflows/*`, `.gitlab-ci.yml`, `.circleci/config.yml`, `Jenkinsfile`,
  `azure-pipelines.yml`, `.travis.yml`, `bitbucket-pipelines.yml`), container/infra
  (`Dockerfile*`, `docker-compose*`/`compose.*`, `*.tf`/`*.tfvars`, and k8s heuristics —
  `k8s/`, `kustomization.yaml`, Helm `Chart.yaml`), and deploy/PaaS (`Procfile`, `fly.toml`,
  `vercel.json`, `netlify.toml`, `render.yaml`, `serverless.yml`, `app.yaml`, `deploy*.sh`).
  Silent inventory like `detect-ui` — the *include-it?* ask lives at the GATE (§6), not here.
  `present: true` is what gates the operations.md branch (§operations.md below). k8s detection
  is a filename/dir heuristic and is stated as such at the gate.
```

- [ ] **Step 2: Extend the EXTRACT claim-type enum (§3)**

In `### 3. EXTRACT`, change the `type` enum line. Find:

```markdown
`type`
(`architecture | business-logic | tech-context | convention`), `citations[{path,startLine,endLine}]`,
```

Replace with:

```markdown
`type`
(`architecture | business-logic | tech-context | convention | operations`), `citations[{path,startLine,endLine}]`,
```

Then, immediately **after** the paragraph that ends "…and `target_doc_section`." add:

```markdown
`operations` claims (CI/CD, container topology, deploy target, runbook pointers) target
`operations.md` and are emitted **only when DETECT's `detect-ops` reported `present: true`**. The
load-bearing rule still bites: a deploy-secret path, a production/branch deploy gate, or a
fail-closed CI check is **load-bearing** (`security` / `fail-closed`) and blocks on unsupported
per the two-tier gate (§4) like any other load-bearing claim. `type` is free-form to
`verify-citations`, so this adds no schema change.
```

- [ ] **Step 3: Add the operations.md doc section**

In the `## CONVENTIONS.md and DESIGN.md` section, append a new bullet at the end of the list (after the `DESIGN.md` bullet and its WCAG sub-paragraph):

```markdown
- **`operations.md`** (`docs/superpowers/architecture/`, ops repos) is generated **only when
  `detect-ops` reported `present: true`.** On a repo with no CI/CD, container, or deploy files it
  is **skipped** (verify this negative path on a non-ops dogfood, mirroring the DESIGN.md negative
  path). Read-then-cite from the real workflow / Docker / compose / Terraform / deploy files
  DETECT inventoried — never from the model's prior. Cover: container topology (services, ports,
  volumes), CI/CD stages (build → test → deploy triggers and branch/environment gates), the deploy
  target + production domain, and runbook pointers. **No credential is ever extracted into the
  doc** — the blocking `scan-output` gate (§7) refuses a generated file that contains one, and a
  deploy-secret reference is documented by *path*, not value.
```

- [ ] **Step 4: Add the §6 GATE per-artifact confirm**

In `### 6. HUMAN GATE`, immediately **after** the paragraph that ends "…**Nothing is written before explicit approval** — no auto-apply, ever." add:

```markdown
When `detect-ops` reported `present: true`, present `operations.md` as its **own explicit
per-artifact confirm**, framed with the detected inventory: *"DevOps/deployment tooling detected —
`<ci_cd / containers / deploy counts + paths>` — include `operations.md`?"* Declining drops the doc
and writes nothing for it; this is the *"ask the user whether to take DevOps into account"* decision.
A fully autonomous / unattended run (auto-approve / `--permission-mode dontAsk` — today the headless
marathon, or any future autonomous onboarding cycle) approves it like every other artifact, so ops
is taken into account **without asking** — no separate code path is needed.
```

- [ ] **Step 5: Add operations.md to the §7 WRITE surface**

In `### 7. WRITE`, in the "Write **only** what was approved" paragraph, find the write-surface list:

```markdown
`docs/superpowers/architecture/*`, root `CONVENTIONS.md`, root `DESIGN.md` (UI repos), `AGENTS.md`,
```

The glob `docs/superpowers/architecture/*` already covers `operations.md`; add an explicit parenthetical so the conditional is unmissable. Replace that line with:

```markdown
`docs/superpowers/architecture/*` (including `operations.md` — **only when the ops gate was approved**,
§6), root `CONVENTIONS.md`, root `DESIGN.md` (UI repos), `AGENTS.md`,
```

- [ ] **Step 6: Note operations.md in the Refresh/manifest contract**

In the `## Refresh — cited-evidence staleness` section, at the end of the first bullet (the `--refresh` re-extract bullet), append one sentence:

```markdown
  `operations.md` is a normal cited arch doc, so it rides this same `.onboard-manifest.json`
  cited-evidence staleness machinery with no new gate.
```

- [ ] **Step 7: Verify the edits landed coherently**

Run:
```bash
grep -n "detect-ops" skills/compound-v/onboarding.md
grep -n "operations.md" skills/compound-v/onboarding.md
grep -n "convention | operations" skills/compound-v/onboarding.md
```
Expected: `detect-ops` appears in §1 DETECT (and §operations.md); `operations.md` appears in §1, EXTRACT, the doc section, §6, §7, and Refresh; the enum line shows the new `operations` value. Read the five edited regions once to confirm no dangling references and that the DESIGN.md-parallel phrasing reads cleanly.

- [ ] **Step 8: Commit**

```bash
git add skills/compound-v/onboarding.md
git commit -m "docs(v-onboard): wire operations.md dimension into onboarding pipeline"
```

---

### Task 3: Spec artifacts table + conditional-fourth prose

**Files:**
- Modify: `docs/superpowers/specs/2026-06-30-v-onboard-design.md` (artifacts table near line 51; "three architecture files" prose near line 57)

**Interfaces:**
- Consumes: nothing (documentation-of-record update).
- Produces: the base spec's artifacts table lists `operations.md` and its prose names it the conditional fourth arch doc — keeping the design of record consistent with the shipped behavior.

- [ ] **Step 1: Add the artifacts-table row**

In `docs/superpowers/specs/2026-06-30-v-onboard-design.md`, find the table row (line 51):

```markdown
| `architecture.md`, `business-logic.md`, `tech-context.md` | `docs/superpowers/architecture/` | always | citation hybrid (§7) |
```

Insert a new row immediately **after** it:

```markdown
| `operations.md` | `docs/superpowers/architecture/` | ops files present, confirmed at gate | citation hybrid (§7) |
```

- [ ] **Step 2: Update the "three architecture files" prose**

Find (line 57–59):

```markdown
The three `architecture/` files follow Cline's Memory Bank model (systemPatterns,
productContext, techContext), trimmed to the durable set. The fast-changing
`progress.md`/`activeContext.md` are **out of v1**.
```

Replace with:

```markdown
The three always-on `architecture/` files follow Cline's Memory Bank model (systemPatterns,
productContext, techContext), trimmed to the durable set, plus a **conditional fourth
`operations.md`** — generated only when `detect-ops` finds CI/CD / container / deploy files and
the maintainer confirms it at the gate. The fast-changing `progress.md`/`activeContext.md` are
**out of v1**.
```

- [ ] **Step 3: Verify**

Run:
```bash
grep -n "operations.md" docs/superpowers/specs/2026-06-30-v-onboard-design.md
```
Expected: two hits — the table row and the prose. Read both to confirm the table stays aligned and the prose reads cleanly.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-06-30-v-onboard-design.md
git commit -m "docs(v-onboard): record operations.md as conditional fourth arch doc"
```

---

## Self-Review

**Spec coverage** (against `2026-07-17-v-onboard-operations-dimension-design.md`):
- §4.1 `detect-ops` (signals, dict shape, CLI, selftest) → Task 1. ✓
- §4.2 DETECT bullet → T2 S1; EXTRACT 5th type → T2 S2; operations.md section → T2 S3; §6 gate confirm → T2 S4; §7 write surface → T2 S5; refresh note → T2 S6. ✓
- §4.3 spec table row + conditional-fourth prose → Task 3. ✓
- §2 "no `verify-citations` change / no pre-flight change" → honored (no such steps; stated in Global Constraints). ✓
- §6 verification (selftest green, `--json` on ops repo, negative path documented) → T1 S7, and the negative path is written into the onboarding.md operations.md section (T2 S3). ✓

**Placeholder scan:** no TBD/TODO; every code step shows full code; doc steps show exact find/replace text. ✓

**Type consistency:** `detect_ops` returns `{"present", "ci_cd", "containers", "deploy"}` in Task 1 and every later reference (T1 selftest, T1 CLI, T2 DETECT bullet, T2 gate confirm) uses those exact keys and the `ops`/`no-ops` CLI strings. `_ops_category` returns exactly `"ci_cd" | "containers" | "deploy" | None`, matching the `found` dict keys. ✓

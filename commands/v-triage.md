---
description: Classify one change request before any work starts — resolve, score, and write plus COMMIT the pre-eval triage record, then print the tier (DIRECT | SCOPED | FULL) with the predicates that decided it. `--land` is the UNATTENDED DIRECT auto-route landing gate — it re-checks predicates 7, 8 and 9 and commits behind an expected-HEAD compare-and-swap; an attended DIRECT change is an ordinary commit and does not use it.
---

You are running **`/v:triage`** — the **entry point** to Compound V's sizing engine.

`scripts/compound-v-preeval.py` and its five siblings are ~10,400 lines of deterministic scoring
that, until this command existed, **nothing ever called**: `docs/superpowers/pre-eval/` had never
appeared in this repository's git history and no run had ever been bound to a record. Every other
v3.0 mechanism — the validator's `triage` block, the Stop-hook coverage gate, the outcome stream,
the circuit breaker — consumes a record that only Phase T produces.

The argument is `{{args}}`.

## You are not the only producer any more (v3.4)

`hooks/triage-prompt-nudge.sh` fires on `UserPromptSubmit` and runs **the same subcommand Phase T
runs below**, so a change request that arrives as an ordinary prompt is usually already sized and
already has a record — written, bound to the session, and **uncommitted**, because a hook must not
run git. Before scoring, check whether that record exists and covers this work:

```bash
ls -t docs/superpowers/pre-eval/*.json 2>/dev/null | head -5
```

If one carries this session's id, **do not mint a second**: commit it (step T3) and go. A record per
prompt is how the outcome stream the circuit breaker reads stops meaning anything. Run Phase T when
the hook did not fire — a slash-command invocation, a second request in the same session, or any
session the hook was not registered in.

As of **v3.4.1 a request needing T3 is no longer one of those cases**: the hook finishes the classify
itself with the headless one-shot (see T2) and records a real tier. It falls back to its reminder
only when no classifier could be RUN at all — no `claude`/`codex` CLI on the machine, or one that
hung past the cap — and that reminder is the signal to run Phase T here.

## Two modes

| Invocation | What it does | When |
|---|---|---|
| `/v:triage <request>` | **Phase T** — resolve localization, classify, score, write **and commit** the record, print the tier and predicates 1-6. | Before any work starts, when no record already covers the request. |
| `/v:triage --land <pre_eval_id>` | **Phase L** — the **UNATTENDED** DIRECT auto-route landing gate. Re-checks predicates 7, 8 and 9 against the realised diff and commits behind an expected-HEAD compare-and-swap. | Only when a DIRECT change is landing with **no human in the loop**. |

### An attended DIRECT change is an ordinary commit

**Phase L is not the normal way to commit a DIRECT change, and it is not a general commit helper.**
DIRECT means "implement in place, run the floor, commit on the branch". When a human is in the
session — the overwhelmingly common case — that commit is an **ordinary `git commit`**: make the
edit, run the test floor, commit it together with the triage record, and let review and the human
be the enforcement they already are.

Phase L exists for the one case that has neither: an **unattended** landing, where no person and no
reviewer is downstream of the commit. DIRECT dispatches no reviewer, so for that case predicates
7-9 are the only enforcement there is, which is why the gate is as heavy as it is — a full test
contract including `full_command`, a post-diff re-validation against the pre-edit taxonomy snapshot,
a lock ref, an expected-HEAD compare-and-swap, and a re-validation of the tree itself. Paying that
cost on a change a human is watching buys nothing and refuses a great deal: a repository that
declares no `full_command` cannot pass predicate 7 at all, and an attended DIRECT change routed
through `--land` would be demoted to SCOPED for a reason that does not apply to it.

So:

- **Attended DIRECT** → implement, run the floor, `git add` the change **and** the record, `git
  commit`. Do not invoke `--land`.
- **Unattended DIRECT** (an autonomous loop, `/v:epic`, a scheduled run) → `--land`, or nothing
  commits.

SCOPED and FULL are unchanged in both cases: they still require a human offer and acceptance, then
`/v:orchestrate` and `/v:dispatch`.

## The vocabulary rule

**Never re-spell a decision string or a tier token.** `DECISION_FASTPATH` / `DECISION_SCOPED` /
`DECISION_FULL` and the `DECISION_TO_TIER` map live in `scripts/compound-v-preeval.py`; Phase T
reads them by calling the engine's own `triage` subcommand, and Phase L imports the module. A
duplicated wire vocabulary is how the two halves of this release drift apart, and the one ratified
exception (a sibling analyser consuming the value as JSON off a record, with a selftest asserting
equality) does not apply here.

The same rule governs the `sensitive` set: it comes from the taxonomy via
`compound-v-taxonomy.match_auto_route()`, **never** from a list written here. `MANDATORY_SENSITIVE`
in that module is the code-level floor that keeps a taxonomy which forgets the two policy files from
re-opening the self-widening hole; this command adds nothing to it.

---

## The nine auto-route predicates (spec §A4), and where each is evaluated

| # | Predicate | Evaluated | Re-evaluated inside the CAS window |
|---|---|---|---|
| 1 | Tier is `DIRECT` and **no override fired** | Phase T, from the record's `decision` + `override_fired` | — |
| 2 | Exactly one resolved path, and it is a **literal** | Phase T, via the engine's own `_is_single_literal_path` | yes, as *path identity* inside predicate 8 |
| 3 | Taxonomy present and **digest-matched**; never a fail-closed `unknown` band | Phase T, against the record's pinned snapshot | yes |
| 4 | Path matches the taxonomy's `auto_route_allow` | Phase T, via `match_auto_route` | yes |
| 5 | Path matches **no** entry in the `sensitive` set | Phase T, via `match_auto_route` (taxonomy + mandatory floor) | yes |
| 6 | **No test file touched** | Phase T (resolved path), Phase L (realised path) | yes |
| 7 | **The floor has been run and passed**, and `full_command` is declared and part of it | Phase L | yes (the floor result is bound to a diff digest; a moved diff re-runs it, against a throwaway index) |
| 8 | **Full post-diff re-validation** against the immutable pre-edit taxonomy snapshot: path identity, allowlist, sensitive set, no test file, line budget, taxonomy digest unchanged | Phase L | yes — and a **third** time against the exact tree handed to `commit-tree` |
| 9 | **Circuit breaker armed** (`compound-v-triage-outcomes.py breaker`, exit 3 = disarmed) | Phase L | yes |

Predicates 1-6 decide *membership*, and Phase T reports them for every record — a DIRECT change
that is attended still gets the six, as evidence, and then commits ordinarily. Predicates 7-9
decide the **unattended landing**, and they are the only enforcement that case has: DIRECT
dispatches **no reviewer**, so a review cannot be the enforcement point for a tier that would
otherwise commit with nobody watching. Any failure **demotes to SCOPED before the commit**, and the
demotion is recorded on the outcome stream.

### Why predicate 7 demands `full_command`, not just the floor

The floor is an early-feedback optimization; it does not restore what the full suite guaranteed
(ADR 0003). An attended change survives that gap because a human and a reviewer are downstream of
it — which is precisely why an attended DIRECT change does not come through this gate at all. An
unattended landing has neither, so it must clear the bar the class is trading on:
`test_contract.full_command`. **A repository that declares no `full_command` cannot auto-route at
all**, and that is the intended fail-closed outcome, not a defect to route around — and not a
reason to push an attended change through `--land` to "check the box", which would only demote it.

### Why the recheck sits behind a compare-and-swap

"Atomic recheck at commit time" is a property, not a sentence. Two sessions can both read the
breaker as armed, one of them disarm it, and the second commit on authorization that is already
stale. A plain re-read cannot see that. Phase L therefore takes **two** git-level guarantees, both
probed live before this command shipped:

- **A lock ref** — `git update-ref refs/compound-v/triage-landing-lock <sha> ""`. The empty
  old-value means *the ref must not exist*, so the create is a real mutex: a second session's
  acquire fails with `cannot lock ref … reference already exists`. Only one session is ever inside
  the [recheck → commit] window, which is what makes the breaker read non-stale.
- **An expected-HEAD compare-and-swap on the commit itself** — the commit object is built with
  `git write-tree` + `git commit-tree`, and HEAD is moved with `git update-ref HEAD <new>
  <expected>`. If anything moved HEAD since the recheck, git refuses (`cannot lock ref 'HEAD': is at
  X but expected Y`) and **nothing lands**. A `git commit` cannot express that condition.

- **A final re-validation of the tree itself** — the two guarantees above cover HEAD and the
  [recheck → commit] window; neither covers the *index*, which stays mutable for as long as
  anything in the process can still run. Predicate 7's own test commands are the clearest example:
  `full_command` is arbitrary project code in this worktree, and a `git add` inside it writes
  straight into the object `commit-tree` is about to commit. So the floor runs with
  `GIT_INDEX_FILE` pointed at a **throwaway copy** — a suite that stages into the tree it is
  validating moves only the copy, is detected by comparing the copy back against the tree it
  started from, and the landing is refused rather than repaired. And because a determined command
  can step around the variable and write to the real index anyway, predicate 8 is re-run once more
  against the tree object `write-tree` produced, which must also **be** the diff predicates 7 and 8
  were computed against. A tree nobody validated cannot ride in underneath a HEAD that never moved.

`commit-tree` commits exactly what is in the index, so Phase L stages **only** the one authorised
path and refuses if the staged set is anything else. Unrelated dirt in the working tree is left
untouched and uncommitted.

---

## Phase T — decide

### T1. Preconditions

```bash
git rev-parse --show-toplevel
```

```bash
printf '%s\n' "${CLAUDE_CODE_SESSION_ID:-}"
```

Read what that prints before running T2 — it is what the record binds, and its consequences are
under "On the session id" below.

### T2. Score, bind, write the record — one call

The whole of Phase T is a subcommand of the engine. Put the request text in
`V_TRIAGE_REQUEST` (never on argv: a request is arbitrary text, it has to survive shell
quoting, and argv is visible to every process on the machine) and run this from the repo root:

```bash
V_TRIAGE_REQUEST='<the request text>' python3 scripts/compound-v-preeval.py triage \
  --request-env V_TRIAGE_REQUEST --repo . \
  --session-id "${CLAUDE_CODE_SESSION_ID:-}" --base-commit "$(git rev-parse HEAD)" --json
```

It prints one JSON object: `pre_eval_id`, `tier`, `decision`, `needs_t3`, `record_ref`,
`predicates` (spec §A4's 1-6, each with a `pass` and a `why`), `declared_paths`, plus `member`
(all six hold), `refused_paths`, `disabled` and the binding echoed back.

**This is the same call `hooks/triage-prompt-nudge.sh` makes** — see `triage_request`'s docstring
in the engine, which names both callers. That is the point of it being a subcommand rather than
prose: the scoring, the binding, the declared-path vocabulary and the six predicates have one
implementation, it is covered by `compound-v-preeval.py --selftest`, and a second producer is one
line rather than a copy.

Add `--t3-category <plumbing|user-facing-minor|user-facing-major|unknown>` on the re-invocation
after a `needs_t3` result. Add `--taxonomy PATH` only to point at a non-default taxonomy.

**Two results are not a tier, and each has one right response:**

- `"disabled": true` — `pre_eval.enabled` is false. The stage is a no-op, **nothing was written**,
  and this change is FULL by the operator's own configuration. Say so; do not hand-write a record.
- `"needs_t3": true` — the deterministic layers cannot band the request without a light classify.
  Answer the returned `t3_prompt` with one of the returned `t3_categories` and re-invoke with
  `--t3-category <enum>`. The re-invocation resumes the same `pre_eval_id` (discovered by request
  fingerprint) rather than minting a second. Any error, timeout, or non-enum reply is `unknown`,
  which is FULL.

  **The headless one-shot is the default route** (v3.4.1, finding 50). Write the returned
  `t3_prompt` to a file and run:

  ```bash
  python3 scripts/compound-v-classify-request.py --classify-headless \
    --prompt-file "$PROMPT_FILE" --cwd . --timeout 15
  ```

  It prints `{"category", "backend", "timed_out", "exit_code", "model"}`: one nested
  `claude -p --tools ""` on the resolved `claude`/`light` model (never Haiku), falling back to the
  read-only `codex` route, both under `compound-v-run-with-timeout.py` with stdin closed. Pass the
  `category` straight back as `--t3-category`. Prefer it because it is the same route
  `hooks/triage-prompt-nudge.sh` takes, so an attended `/v:triage` and the hook that fires without
  anyone asking reach the same answer by the same path.

  **`backend: "none"` is not an answer.** It means no classifier CLI was available on this machine
  — as does `timed_out: true`. Neither is a classification, and neither may be recorded as
  `--t3-category unknown`: that would put a made-up band on a real record. Fall back to the Task
  route below. A model that RAN and replied `unknown` is different and *is* an answer: re-invoke
  with it and take the FULL that follows.

  **The Task route is the fallback**, and the only route on a harness with no `claude`/`codex` CLI:
  run **one** `light`-tier Task (Sonnet, never Haiku) with the `t3_prompt`, then
  `--parse` its reply into the enum:

  ```bash
  python3 scripts/compound-v-classify-request.py --parse --reply '<the Task reply>'
  ```

**On the session id.** `CLAUDE_CODE_SESSION_ID` is the harness session id as a Bash call in this
session sees it, and it is what the record binds. **If it is empty, say so and continue** — the
record is still written and still classifies, but with `session_id: null` it covers nothing for the
Stop-hook triage gate (`hooks/epic-goal-stop.sh` compares it exactly, and an empty value can never
match). That is the fail-closed direction; do not substitute a pid or an invented uuid. The engine
binds what it is given and refuses to invent, so passing an empty value is safe.

**On `refused_paths`.** A non-empty list means the localizer resolved a path the triage gate cannot
read back (a leading `/`, a `..` segment, a control character). Those are dropped from
`declared_paths` — report them, because coverage the record claims and does not have is worse than
coverage it never claimed.

### T3. Commit the record

The engine deliberately **never runs git**, and neither does the UserPromptSubmit hook; committing
is this command's job, and it is not optional. An uncommitted record is invisible to the Stop-hook
triage gate (which reads committed files back with `jq`) and is destroyed by `git worktree remove`
the moment a branch is merged or discarded — the v2.6.4 data-loss shape.

**This step also applies to a record the hook wrote.** If you skipped T2 because
`hooks/triage-prompt-nudge.sh` had already sized this session's request, its record is sitting
uncommitted; commit it here with the same two commands.

```bash
git add docs/superpowers/pre-eval/<pre_eval_id>.json docs/superpowers/pre-eval/<pre_eval_id>.intent.json docs/superpowers/pre-eval/<pre_eval_id>.localization.json docs/superpowers/pre-eval/<pre_eval_id>.taxonomy-snapshot.yaml docs/superpowers/memory/triage-outcomes.jsonl
```

```bash
git commit -m "triage(<TIER>): <short request> [<pre_eval_id>]"
```

Some of those artifacts are absent by design — there is no snapshot when the repository has no
taxonomy, and no localization artifact when localization failed. `git add` the ones that exist.

### T4. Report

Print the tier, the predicate list exactly as T2 emitted it, and the next step:

- **DIRECT, attended** (a human is in this session — the usual case) → implement it, run the test
  floor, and commit it as an **ordinary commit**. Do not invoke `--land`; a human and a review are
  downstream of you, which is the enforcement that class is trading on.
- **DIRECT, unattended and `"member": true`** → make the change, then `/v:triage --land <id>`. It
  enforces predicates 7, 8 and 9 and commits, or demotes to SCOPED and records the demotion.
- **DIRECT, unattended and `"member": false`** → it cannot auto-route. Stop and get a human, or
  route it through `/v:orchestrate` as SCOPED.
- **SCOPED** → offer it; on acceptance `/v:orchestrate` (manifest, run dir, scope gate, floor, one combined SPEC+QUALITY review; recon and the three pre-flights are skipped).
- **SCOPED+** (`"tier": "SCOPED"` with `"flavor": "scoped_plus"`) → a small edit on a **sensitive**
  path. Offer it; on acceptance `/v:orchestrate` with `triage.flavor: scoped_plus`, where a deep
  review and a cross-model second opinion are **mandatory**, not offered. SCOPED+ is not a fourth
  tier token — it is SCOPED plus a flavor, and the size being small is exactly why the review does
  not shrink with it.
- **FULL** → offer it; on acceptance the unchanged pipeline.

---

## Phase L — the UNATTENDED landing gate

Run **after** the edit and **instead of** `git commit`, and **only when nobody is watching** — see
"An attended DIRECT change is an ordinary commit" above. It refuses anything that is not a DIRECT
record, demotes on any predicate failure, and records the demotion. Set `V_TRIAGE_DRY_RUN=1` to
evaluate 7, 8 and 9 and stop before the CAS window.

```bash
V_TRIAGE_ID='<pre_eval_id>' V_TRIAGE_MESSAGE='<commit message>' python3 - <<'PY'
import hashlib, importlib.util, json, os, shutil, subprocess, sys, tempfile

REPO = os.path.abspath(os.environ.get("V_TRIAGE_REPO", "."))
DRY = os.environ.get("V_TRIAGE_DRY_RUN") == "1"
LOCK = "refs/compound-v/triage-landing-lock"

def _load(basename, modname):
    path = os.path.join(REPO, "scripts", basename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

pe = _load("compound-v-preeval.py", "cv_preeval")
tx = _load("compound-v-taxonomy.py", "cv_taxonomy")
fr = _load("compound-v-fastpath-run.py", "cv_fastpath_run")
vm = _load("compound-v-validate-manifest.py", "cv_validate_manifest")
cfgmod = _load("compound-v-project-config.py", "cv_project_config")
outc = _load("compound-v-triage-outcomes.py", "cv_triage_outcomes")

def git(*args, **kw):
    """``index=<abspath>`` runs the command against THAT index file instead of the
    repository's own. The candidate-index discipline below is built on it."""
    env = None
    if kw.get("index"):
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = kw["index"]
    return subprocess.run(["git", "-C", REPO] + list(args),
                          capture_output=True, text=True, env=env)

pid = (os.environ.get("V_TRIAGE_ID") or "").strip()
msg = (os.environ.get("V_TRIAGE_MESSAGE") or "").strip()
if not pe.PRE_EVAL_ID_RE.match(pid):
    sys.exit("REFUSED: --land needs a valid pre_eval_id, got %r" % pid)
if not msg and not DRY:
    sys.exit("REFUSED: --land needs a commit message")

pdir = os.path.join(REPO, "docs", "superpowers", "pre-eval")
with open(os.path.join(pdir, pid + ".json"), "r", encoding="utf-8") as fh:
    rec = json.load(fh)

failures = []
def check(cond, why):
    if not cond:
        failures.append(why)
    return cond

# ---- the record itself is intact and is a DIRECT record --------------------------- #
if rec.get("digest"):
    check(tx.record_digest(rec, exclude_field="digest") == rec["digest"],
          "the record's own integrity digest does not verify")
check(rec.get("decision") == pe.DECISION_FASTPATH,
      "record decision is %r, not %s — only a DIRECT record may land here"
      % (rec.get("decision"), pe.DECISION_FASTPATH))
check(rec.get("override_fired") is None,
      "override #%s fired — any fired override forces %s"
      % (rec.get("override_fired"), pe.DECISION_TO_TIER[pe.DECISION_FULL]))

# ---- the IMMUTABLE pre-edit taxonomy snapshot ------------------------------------- #
# Predicates 4, 5 and the line budget are re-evaluated against the taxonomy AS IT WAS
# BEFORE the edit, and its digest must be unchanged. Without both halves, a change
# authorised to edit docs/release-note.md could instead edit ONLY the taxonomy — widening
# auto_route_allow to scripts/** — and still look like one small non-sensitive file.
snap_path = os.path.join(pdir, pid + ".taxonomy-snapshot.yaml")
taxonomy = pinned = None
if os.path.isfile(snap_path):
    with open(snap_path, "rb") as fh:
        snap_bytes = fh.read()
    pinned = tx.taxonomy_digest_bytes(snap_bytes)
    taxonomy = tx.load_taxonomy(text=snap_bytes.decode("utf-8"))
check(taxonomy is not None and pinned == rec.get("taxonomy_digest"),
      "no pinned taxonomy snapshot, or it does not content-address to the record's "
      "taxonomy_digest")

live_path = os.path.join(REPO, pe.DEFAULT_TAXONOMY_REL)
live = tx.taxonomy_digest_file(live_path) if os.path.isfile(live_path) else None
check(live is not None and live == pinned,
      "the taxonomy on disk (%s) differs from the snapshot this record pinned (%s) — the "
      "authorization would be reading rules the change itself may have rewritten"
      % (live, pinned))

_TEST_SEGMENTS = ("test", "tests", "spec", "specs", "__tests__", "testing")
def is_test_path(p):
    segs = p.split("/")
    if any(s.lower() in _TEST_SEGMENTS for s in segs[:-1]):
        return True
    base = segs[-1]
    if base in ("conftest.py",):
        return True
    stem = base.split(".")[0].lower()
    if stem.startswith(("test_", "test-")) or stem.endswith(("_test", "-test")):
        return True
    return any((".%s." % k) in base.lower() for k in ("test", "spec"))

resolved = (rec.get("localization") or {}).get("resolved_paths") or []
check(pe._is_single_literal_path(resolved),
      "the record does not resolve to exactly one literal path: %r" % (resolved,))
authorised = resolved[0] if pe._is_single_literal_path(resolved) else None

if failures:
    print("LANDING REFUSED before any staging:")
    for f in failures:
        print("  - %s" % f)
    raise SystemExit(1)

# ---- stage ONLY the authorised path ----------------------------------------------- #
# `commit-tree` commits the whole index, so the index must contain exactly this change
# and nothing else. Anything else staged is a refusal, not something to quietly drop.
git("add", "--", authorised)
staged = [p for p in git("diff", "--cached", "--name-only", "-z").stdout.split("\0") if p]

def revalidate(tree=None):
    """Predicate 8, in full, against the immutable pre-edit snapshot. Returns
    (ok, [reasons], realised_diff_digest). Called before the lock, AGAIN inside it, and
    a THIRD time against the exact tree object handed to `commit-tree`.

    `tree` is what closes the gap between "the index was valid" and "the tree being
    committed is valid". The compare-and-swap guards HEAD and only HEAD; the index stays
    mutable for as long as anything in this process can still run — the floor's own test
    commands included. With `tree` given, every clause below reads `git diff HEAD <tree>`,
    which is byte-identical to `--cached` when the two agree and is the only phrasing
    bound to the bytes actually being committed."""
    why = []

    def diff(*flags):
        if tree is None:
            return git("diff", "--cached", *flags)
        return git("diff", *(list(flags) + ["HEAD", tree]))

    st = [p for p in diff("--name-only", "-z").stdout.split("\0") if p]
    # PATH IDENTITY: the realised path must EQUAL the resolved one. "One literal path"
    # alone permits substituting a different file of the same shape.
    if st != [authorised]:
        why.append("realised path set %r != the authorised path [%r]" % (st, authorised))
    now = tx.taxonomy_digest_file(live_path) if os.path.isfile(live_path) else None
    if now != pinned:
        why.append("the taxonomy changed under this landing (%s != %s)" % (now, pinned))
    budget = tx.DEFAULT_AUTO_ROUTE_MAX_LINES
    for p in st:
        ar = tx.match_auto_route(taxonomy, p)   # predicates 4 + 5, from the taxonomy
        budget = ar["max_lines"]
        if not ar["eligible"]:
            why.append("%s: %s" % (p, "; ".join(ar["reasons"])))
        if is_test_path(p):
            why.append("%s is a test file (predicate 6)" % p)
    total = 0
    for row in diff("--numstat", "--no-renames", "-z").stdout.split("\0"):
        if not row:
            continue
        parts = row.split("\t", 2)
        if len(parts) != 3:
            continue
        add, dele, path = parts
        if add == "-" or dele == "-":
            why.append("%s is binary — not accountable against the line budget" % path)
            continue
        total += int(add) + int(dele)
    if total > budget:
        why.append("%d changed lines is over the %d-line auto_route_max_lines budget"
                   % (total, budget))
    blob = diff("--no-color").stdout
    digest = "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return (not why), why, digest

ok8, why8, realised_digest = revalidate()

# ---- predicate 7: the floor, and full_command for an unattended landing ------------ #
# ONE floor, not a second one: this is the shipped `run_test_floor` fed by the shipped
# resolver. The contract is the project's declared one — there is no manifest at DIRECT.
def load_contract():
    explicit = os.environ.get("V_TRIAGE_TEST_CONTRACT")
    if explicit:
        with open(explicit, "r", encoding="utf-8") as fh:
            doc = vm.load_yaml(fh.read()) or {}
        tc = doc.get("test_contract")
        return tc if isinstance(tc, dict) else None
    try:
        cfg = cfgmod.load_project_config(REPO)
    except ValueError:
        return None
    tc = cfg.get("test_contract")
    return tc if isinstance(tc, dict) else None

# ---- the floor runs against a DISPOSABLE CANDIDATE INDEX ------------------------- #
# `commit-tree` commits the INDEX, and `full_command` is arbitrary project code running
# in this worktree — nothing about it is trusted and nothing stops a test from `git add`
# ing more work into the very tree this landing is about to commit. Pointing
# GIT_INDEX_FILE at a throwaway COPY means whatever the tests stage lands there instead;
# comparing that copy's tree with the real one afterwards is how a suite that edited the
# tree it was validating gets DETECTED rather than smuggled in. A test suite that moves
# the tree it is validating has not validated anything, so this is a refusal, not a
# repair.
def run_floor(bind_digest):
    """Predicate 7's floor, index-isolated. Returns the floor result with
    `bound_diff_digest` set and `mutated` set to a reason when the tests moved a tree."""
    tmpd = tempfile.mkdtemp(prefix="v-triage-candidate-index-")
    cand = os.path.join(tmpd, "index")
    try:
        real_index = git("rev-parse", "--git-path", "index").stdout.strip()
        if not os.path.isabs(real_index):
            real_index = os.path.join(REPO, real_index)
        shutil.copyfile(real_index, cand)
        before = git("write-tree").stdout.strip()
        # `run_test_floor` runs each command through the timeout supervisor with the
        # process environment inherited, so this is how the variable reaches them.
        prev = os.environ.get("GIT_INDEX_FILE")
        os.environ["GIT_INDEX_FILE"] = cand
        try:
            res = fr.run_test_floor(REPO, "HEAD", changed_paths=list(staged),
                                    test_commands=slice_["resolved_commands"])
        finally:
            if prev is None:
                os.environ.pop("GIT_INDEX_FILE", None)
            else:
                os.environ["GIT_INDEX_FILE"] = prev
        after_cand = git("write-tree", index=cand).stdout.strip()
        after_real = git("write-tree").stdout.strip()
        res["bound_diff_digest"] = bind_digest
        res["candidate_tree"] = after_cand
        if not (before and after_cand and after_real):
            res["mutated"] = "the candidate index could not be resolved to a tree"
        elif after_cand != before:
            res["mutated"] = ("the test commands staged changes into the tree they were "
                              "validating (%s -> %s)" % (before[:12], after_cand[:12]))
        return res
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)

def floor_verdict(res):
    """(ok7, why7) from a `run_floor` result. A mutated tree fails predicate 7 even
    when every configured command exited 0."""
    good = (bool(res.get("passed")) and not res.get("merge_blocked")
            and not res.get("mutated"))
    if good:
        return True, []
    reasons = list(res.get("reasons") or [])
    if res.get("mutated"):
        reasons.append(res["mutated"])
    return False, reasons or ["the floor did not pass"]

contract = load_contract()
slice_ = floor = None
ok7, why7 = False, []
if not contract:
    why7.append("no test_contract is declared (.claude/compound-v.json `test_contract`, "
                "or V_TRIAGE_TEST_CONTRACT=<manifest.yaml>) — an unattended landing "
                "requires full_command and there is none")
else:
    try:
        # scope 'full' is what an unattended landing owes: the floor PLUS full_command.
        # The resolver raises rather than resolving 'full' to nothing, so a contract with
        # no full_command fails here — which is exactly predicate 7's extra clause.
        # no_prior_run: there is no job_result at DIRECT, and 'full' never consults the
        # previously-failing set, so the assertion is inert as well as true.
        slice_, _notes = fr.resolve_from_manifest(
            {"test_contract": contract}, scope="full", worktree=REPO,
            baseline="HEAD", no_prior_run=True)
        floor = run_floor(realised_digest)
        ok7, _why = floor_verdict(floor)
        why7.extend(_why)
    except fr.TestContractError as e:
        why7.append("test contract did not resolve (fail-closed): %s" % e)

# ---- predicate 9: the breaker, through its own exit-code contract ------------------ #
# Called WITHOUT --no-latch: consulting the breaker before a landing is exactly the
# moment it should latch itself off if the rolling rate has crossed the ceiling.
def breaker():
    r = subprocess.run([sys.executable,
                        os.path.join(REPO, "scripts",
                                     "compound-v-triage-outcomes.py"),
                        "breaker", "--repo", REPO], capture_output=True, text=True)
    armed = r.returncode == 0
    return armed, r, ([] if armed
                      else ["circuit breaker DISARMED (exit %d): %s"
                            % (r.returncode,
                               r.stdout.strip().replace("\n", " ")[:300])])

# ---- reverts of PAST landings, recorded BEFORE this one is authorised ----------- #
# A DIRECT landing dispatches no reviewer and opens no run directory, so until now it
# appended no `actual` at all: ten landings that were every one reverted left ten
# `predicted` events, ZERO negatives, a 0/10 rate and an armed breaker. That is the
# blind spot the numerator was widened to remove, reopened for the one negative outcome
# that only arrives AFTER the commit. `sweep_landings` derives it from git — a revert
# names the commit it reverts — and records it against the landed sha, which is the
# outcome key the receipt below binds. It runs on BOTH sides of the lock for the same
# reason the breaker is read twice: the pre-lock read is advisory, and the in-lock one
# is what the commit is authorised by.
sweep = outc.sweep_landings(repo=REPO)
if sweep.get("appended"):
    print("swept %d reverted landing(s) onto the outcome stream: %s"
          % (sweep["appended"],
             ", ".join(r["commit"][:12] for r in sweep["reverted"])))

ok9, br, why9 = breaker()

def report(tag):
    print("%s predicates:" % tag)
    print("  7. [%s] floor run and passed (+ full_command) — %s"
          % ("PASS" if ok7 else "FAIL",
             "; ".join(why7) or "tier %s, %d command(s)"
             % ((floor or {}).get("tier_used"),
                len((slice_ or {}).get("resolved_commands") or []))))
    print("  8. [%s] full post-diff re-validation — %s"
          % ("PASS" if ok8 else "FAIL",
             "; ".join(why8) or "path identity, allowlist, sensitive set, no test file, "
                                "line budget, taxonomy digest all hold"))
    print("  9. [%s] circuit breaker armed — %s"
          % ("PASS" if ok9 else "FAIL", "; ".join(why9) or "armed"))

report("pre-lock")

def demote(reasons):
    """Any failure demotes to SCOPED before the commit, and the demotion is RECORDED.
    A later `predicted` at a strictly higher tier is how the outcome stream already
    represents this, and `_direct_history` counts it as a negative in the breaker's
    numerator — so no run_id has to be invented for a tier that has no run directory."""
    outc.append_predicted(
        pid, decision=pe.DECISION_SCOPED,
        difficulty_band=rec["difficulty"]["band"], impact_band=rec["impact"]["band"],
        taxonomy_sha=rec.get("taxonomy_digest"),
        localization={"resolved_paths": resolved},
        demoted_from=pe.DECISION_TO_TIER[pe.DECISION_FASTPATH],
        demotion_reason="; ".join(reasons)[:1000])
    git("reset", "--quiet", "HEAD", "--", authorised)
    print("")
    print("DEMOTED to %s and recorded on the outcome stream. Nothing was committed; the "
          "edit is still in the working tree. Route it through /v:orchestrate."
          % pe.DECISION_TO_TIER[pe.DECISION_SCOPED])

if not (ok7 and ok8 and ok9):
    demote(why7 + why8 + why9)
    raise SystemExit(2)

if DRY:
    print("")
    print("DRY RUN — predicates 7, 8 and 9 all pass; the CAS window was not entered.")
    git("reset", "--quiet", "HEAD", "--", authorised)
    raise SystemExit(0)

# ================== THE CAS WINDOW ================================================== #
# Everything above is advisory: between it and the commit another session can move HEAD
# or disarm the breaker. The lock ref is a create-if-absent mutex (an empty old value
# means "must not exist"), so only one session is ever between the recheck and the commit.
expected = git("rev-parse", "HEAD").stdout.strip()
acq = git("update-ref", LOCK, expected, "")
if acq.returncode != 0:
    print("LANDING REFUSED: another session holds %s — %s" % (LOCK, acq.stderr.strip()))
    print("If no session is running, clear the stale lock deliberately: "
          "git update-ref -d %s" % LOCK)
    raise SystemExit(3)

landed = None
try:
    # Predicate 8 in full, again, now that nobody else can be inside this window.
    ok8, why8, digest_now = revalidate()
    # Predicate 7 is re-verified by BINDING rather than by a blind re-run: the floor
    # result carries the diff digest it was computed against, so an identical digest
    # proves the floor ran against exactly this tree. A moved digest invalidates it and
    # the floor is re-run here, inside the window.
    if ok8 and digest_now != (floor or {}).get("bound_diff_digest"):
        floor = run_floor(digest_now)
        ok7, why7 = floor_verdict(floor)
    sweep = outc.sweep_landings(repo=REPO)
    ok9, br, why9 = breaker()
    report("in-lock")

    if not (ok7 and ok8 and ok9):
        demote(why7 + why8 + why9)
        raise SystemExit(2)

    tree = git("write-tree").stdout.strip()
    if not tree:
        print("LANDING REFUSED: the index could not be written to a tree")
        raise SystemExit(1)
    # THE LAST WORD IS THE TREE, NOT THE INDEX. Everything above validated an index, and
    # the compare-and-swap below guards HEAD — neither says anything about the bytes
    # `commit-tree` is handed. This re-runs predicate 8 against exactly those bytes and
    # additionally requires them to BE the diff predicates 7 and 8 were computed against,
    # so a tree nobody validated cannot ride in underneath a HEAD that never moved.
    okT, whyT, digest_tree = revalidate(tree=tree)
    if not (okT and digest_tree == digest_now):
        demote(whyT + ([] if digest_tree == digest_now else
                       ["the tree handed to commit-tree (%s) is not the diff predicates "
                        "7 and 8 were computed against (%s)" % (digest_tree, digest_now)]))
        raise SystemExit(2)
    new = git("commit-tree", tree, "-p", expected, "-m", msg).stdout.strip()
    if not new:
        print("LANDING REFUSED: could not build the commit object")
        raise SystemExit(1)
    # THE COMPARE-AND-SWAP. HEAD moves only if it is still `expected`; git refuses
    # otherwise and nothing lands.
    cas = git("update-ref", "-m", "v:triage land %s" % pid, "HEAD", new, expected)
    if cas.returncode != 0:
        print("LANDING REFUSED: HEAD moved under this landing — %s" % cas.stderr.strip())
        demote(["HEAD moved between the recheck and the commit (CAS refused)"])
        raise SystemExit(2)
    landed = new
finally:
    git("update-ref", "-d", LOCK, expected)
# ==================================================================================== #

# THE LANDING IS THE OUTCOME, and an outcome needs a key. There is no run directory at
# DIRECT and no run_id to name, so the LANDED COMMIT SHA is the key: it exists the moment
# the landing does, it is stable, it is what a revert names, and it is what the sweep
# above corrects under (last-writer-wins on `(pre_eval_id, run_id, event)`). Without a
# key, no CI failure and no revert could ever be attributed to the decision that caused
# it, and the breaker could only ever see a demotion.
outc.append_actual(pid, landed, review_result=None,
                   test_result="pass" if floor.get("passed") else "fail",
                   landing=True, authorised_path=authorised)

# The realised diff digest is bound HERE, in a landing receipt beside the record. It
# cannot live in the record itself: the record is write-once, is written BEFORE the edit
# exists, and its schema is additionalProperties:false with no field for it. This command
# is the only place the realised diff exists, so this is where it is bound.
receipt = {
    "pre_eval_id": pid,
    "tier": pe.DECISION_TO_TIER[pe.DECISION_FASTPATH],
    "landed_commit": landed,
    "expected_head": expected,
    "authorised_path": authorised,
    "realised_paths": staged,
    "diff_digest": digest_tree,
    "tree": tree,
    "taxonomy_digest": pinned,
    "floor": {"tier_used": floor.get("tier_used"), "passed": floor.get("passed"),
              "checks": floor.get("checks"), "bound_diff_digest": digest_tree,
              "commands": (slice_ or {}).get("resolved_commands")},
    "breaker": json.loads(br.stdout) if br.stdout.strip() else None,
    "predicates": {"7": True, "8": True, "9": True},
}
with open(os.path.join(pdir, pid + ".landing.json"), "w", encoding="utf-8") as fh:
    fh.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
print("")
print("LANDED %s  (%s)" % (landed, authorised))
print("receipt docs/superpowers/pre-eval/%s.landing.json — commit it next." % pid)
PY
```

### What a landing records, and why it needs a key

A DIRECT landing dispatches no reviewer and opens no run directory, so it has no `run_id` — and
`append_actual` requires one. The consequence was a hole in the very latch the class depends on: ten
DIRECT decisions, all landed, all reverted or all red in CI, produced ten `predicted` events and
**zero** negative actuals, so the breaker read 0/10 and stayed armed for the eleventh. Phase L
therefore keys its outcome on the **landed commit sha** — it exists the moment the landing does, it
is stable, and it is exactly what a revert names — and appends a terminal `actual` under it.

Reverts are then genuinely produced: `compound-v-triage-outcomes.py sweep-landings` reads the
landing receipts, asks git which of those commits have been reverted (git's own
`This reverts commit <sha>.` marker), and appends the correction under the same key, where
last-writer-wins replaces the clean actual. Phase L runs it on **both sides of the lock**, before
the breaker is read, so a landing whose predecessors were reverted meets a disarmed breaker.

**CI failure is not produced for a DIRECT decision, and is not claimed as one.** Nothing in this
repository calls back from CI into the outcome stream; `ci_failed` is a live input for full-pipeline
runs (`/v:dispatch` passes it) and is now *appendable* against a landing because the key exists, but
no DIRECT landing has ever produced one. Wiring that is a workflow-file change, and until it lands
the honest numerator for this tier is demotions, reverts and escalations — an unreachable input in a
safety latch is worse than a smaller honest one.

Then commit the receipt **separately**. It cannot ride in the landing commit: predicate 8 requires
the realised diff to be exactly the one authorised path, and the receipt records a commit that does
not exist until that commit is made.

```bash
git add docs/superpowers/pre-eval/<pre_eval_id>.landing.json docs/superpowers/memory/triage-outcomes.jsonl
```

```bash
git commit -m "chore(v-triage): landing receipt for <pre_eval_id>"
```

Both paths are under `docs/superpowers/`, which the Stop-hook triage gate exempts, so the receipt
commit does not itself need a record.

---

## Safety

- **Never use Phase L for an attended change.** It is the unattended landing gate, not a commit
  helper. An attended DIRECT change is an ordinary commit.
- **Never widen the class.** `auto_route_allow`, the `sensitive` set and the line budget come from
  the taxonomy through `match_auto_route`; do not add a special case here.
- **Never hand-write or re-score a record that already exists.** The UserPromptSubmit hook and
  Phase T are the two producers and they call the same subcommand; a third copy of the scoring is
  the drift v3.4 removed.
- **Never edit the taxonomy inside a landing.** The two policy files are sensitive in code
  (`compound-v-taxonomy.MANDATORY_SENSITIVE`) as well as in this repo's taxonomy, so a taxonomy that
  forgets them still cannot be self-widened — but the digest check is what makes that guarantee hold
  across the edit.
- **Never force the commit.** If the CAS refuses, something moved HEAD; demote and let a human look.
- **Never let the tests write the tree.** A floor that stages into the index is refused, not
  reconciled — a suite that edited what it was validating has validated nothing.
- **Never invent a session id.** An empty `CLAUDE_CODE_SESSION_ID` means the record covers nothing;
  say so.
- **No fabricated metrics.** Print the floor's real exit codes and the breaker's real rate, nothing
  derived or estimated.

## Selftests

Phase T is no longer prose, so its proofs are no longer here: the scoring, the binding, the
declared-path vocabulary and predicates 1-6 are covered by the engine's own suite, which CI runs.

```bash
python3 scripts/compound-v-preeval.py --selftest
```

Phase L is still prose-hosted, and its proofs live in **`tests/test-triage-landing.sh`**. Run it
from the repo root; it exits non-zero on any failure, and CI's `tests` job discovers it recursively
and always runs it.

```bash
bash tests/test-triage-landing.sh
```

It extracts the Phase L block **verbatim out of this file** and runs it against throwaway git
repositories in `$TMPDIR`, so it drives the gate as shipped rather than a copy that can drift — if
you edit Phase L, the suite runs your edit. Every assertion is a real invocation and what that
invocation left behind: its exit code, the sandbox's git history, and the outcome stream the run
wrote. It covers path substitution (including an index the implementer pre-poisoned), taxonomy
self-widening in both shapes, both halves of the concurrency defence (the lock ref and the
expected-HEAD compare-and-swap), the RECORDED demotion (`demoted_from` / `demotion_reason` reaching
the outcome stream), predicate 7 against a red contract, an absent one and one with no
`full_command`, the line budget and the no-test-file clause, a latched-off breaker, both halves of
the mutable-index defence (a floor that stages into its own candidate index, and one that steps
around the variable to stage into the real one — each caught by a different check, each proved
independent by the other staying green under the first's mutation), and the landing outcome key
(the terminal `actual` under the landed sha, and a reverted landing disarming the breaker before the
next landing is authorised). Each refusal is paired with a control that LANDS, and with a planted
mutation that removes the corresponding check from a copy of the gate and is asserted to turn that
refusal's assertion red.

**What this replaced, and why.** The fixture that used to sit here asserted `staged ==
["OTHER.md"]` (a fact about `git add`), that two sha256 digests differ (a fact about sha256), and
that `git update-ref` honours an expected old value (a fact about git). Phase L could have been
deleted from this file and all fifteen of its assertions would still have passed. It was also
outside CI — the sweep covers `scripts/*.py --selftest` and `tests/**`, and `commands/` is in
neither — so nothing ever ran it. Its trailing `build_record` binding assertions were a duplicate
of `scripts/compound-v-preeval.py --selftest`, which CI does run.

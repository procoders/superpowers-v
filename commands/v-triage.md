---
description: Classify one change request before any work starts — resolve, score, and write plus COMMIT the pre-eval triage record, then print the tier (DIRECT | SCOPED | FULL) with the predicates that decided it. `--land` is the DIRECT auto-route landing gate — it re-checks predicates 7, 8 and 9 and commits behind an expected-HEAD compare-and-swap.
---

You are running **`/v:triage`** — the **entry point** to Compound V's sizing engine.

`scripts/compound-v-preeval.py` and its five siblings are ~10,400 lines of deterministic scoring
that, until this command existed, **nothing ever called**: `docs/superpowers/pre-eval/` had never
appeared in this repository's git history and no run had ever been bound to a record. Every other
v3.0 mechanism — the validator's `triage` block, the Stop-hook coverage gate, the outcome stream,
the circuit breaker — consumes a record that only this command produces.

The argument is `{{args}}`.

## Two modes

| Invocation | What it does | When |
|---|---|---|
| `/v:triage <request>` | **Phase T** — resolve localization, classify, score, write **and commit** the record, print the tier and predicates 1-6. | Before any work starts. |
| `/v:triage --land <pre_eval_id>` | **Phase L** — the DIRECT **auto-route landing gate**. Re-checks predicates 7, 8 and 9 against the realised diff and commits behind an expected-HEAD compare-and-swap. | After the edit, immediately before the commit, and only for a DIRECT record. |

Phase L is *not* a general commit helper. SCOPED and FULL still require a human offer and
acceptance, then `/v:orchestrate` and `/v:dispatch`; only the DIRECT auto-route class may land
without one, and only through this gate.

## The vocabulary rule

**Never re-spell a decision string or a tier token.** `DECISION_FASTPATH` / `DECISION_SCOPED` /
`DECISION_FULL` and the `DECISION_TO_TIER` map are read **from `scripts/compound-v-preeval.py`**, by
import, in every snippet below. A duplicated wire vocabulary is how the two halves of this release
drift apart, and the one ratified exception (a sibling analyser consuming the value as JSON off a
record, with a selftest asserting equality) does not apply here — this command imports the engine
already.

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
| 7 | **The floor has been run and passed** — and an *unattended* landing additionally requires `full_command` | Phase L | yes (the floor result is bound to a diff digest; a moved diff re-runs it) |
| 8 | **Full post-diff re-validation** against the immutable pre-edit taxonomy snapshot: path identity, allowlist, sensitive set, no test file, line budget, taxonomy digest unchanged | Phase L | yes |
| 9 | **Circuit breaker armed** (`compound-v-triage-outcomes.py breaker`, exit 3 = disarmed) | Phase L | yes |

Predicates 1-6 decide *membership*. Predicates 7-9 decide *landing*, and they are the only
enforcement the DIRECT tier has: DIRECT dispatches **no reviewer**, so a review cannot be the
enforcement point for the one tier that commits without a human. Any failure **demotes to SCOPED
before the commit**, and the demotion is recorded on the outcome stream.

### Why predicate 7 demands `full_command`, not just the floor

The floor is an early-feedback optimization; it does not restore what the full suite guaranteed
(ADR 0003). An attended change survives that gap because a human and a reviewer are downstream of
it. An unattended DIRECT landing has neither, so it must clear the bar the class is trading on —
`test_contract.full_command`. **A repository that declares no `full_command` cannot auto-route at
all**, and that is the intended fail-closed outcome, not a defect to route around.

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

`CLAUDE_CODE_SESSION_ID` is the harness session id as a Bash call in this session sees it, and it is
what the record binds. **If it is empty, say so and continue** — the record is still written and
still classifies, but with `session_id: null` it covers nothing for the Stop-hook triage gate
(`hooks/epic-goal-stop.sh` compares it exactly, and an empty value can never match). That is the
fail-closed direction; do not substitute a pid or an invented uuid.

### T2. Score, bind, write the record

Run from the repo root, with the request text in `V_TRIAGE_REQUEST`.

```bash
V_TRIAGE_REQUEST='<the request text>' python3 - <<'PY'
import importlib.util, json, os, re, subprocess, sys

REPO = os.path.abspath(os.environ.get("V_TRIAGE_REPO", "."))

def _load(basename, modname):
    path = os.path.join(REPO, "scripts", basename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

pe = _load("compound-v-preeval.py", "cv_preeval")      # the engine — vocabulary comes from here
tx = _load("compound-v-taxonomy.py", "cv_taxonomy")    # match_auto_route == predicates 4 and 5

request = (os.environ.get("V_TRIAGE_REQUEST") or "").strip()
if not request:
    sys.exit("REFUSED: /v:triage needs a request")

session = (os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip()
head = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"],
                      capture_output=True, text=True).stdout.strip()

# declared_paths: what this record's classification COVERS, in the exact vocabulary
# hooks/epic-goal-stop.sh can read back — an exact path, a `dir/` prefix, or a `*` glob.
# A bare `scripts` deliberately does NOT cover `scripts/app.py`. Entries the hook would
# silently DROP (control characters, a leading `/`, a `..` segment) are dropped HERE
# instead, where the producer still learns about it.
_CTRL = re.compile(r"[\x00-\x1f]")
def declare(paths):
    out, refused = [], []
    for p in paths or []:
        if not isinstance(p, str) or not p:
            continue
        if p.startswith("/") or _CTRL.search(p) or ".." in p.split("/"):
            refused.append(p)
            continue
        if p not in out:
            out.append(p)
    for p in refused:
        print("WARNING: declared path refused (unreadable by the triage gate): %r" % p)
    return out

# THE BINDING GOES THROUGH build_record's kwarg, never onto the record afterwards.
# `digest` covers the whole record, so a producer that attached these fields after the
# fact would ship a record whose own integrity digest no longer verifies — silently,
# because `digest` is optional and only checked when present. Wrapping build_record is
# how the binding reaches the ONE place that keeps the digest correct by construction,
# while `run_preeval` keeps owning the config kill-switch, the taxonomy snapshot, the
# Tier-2 lookup and the `predicted` event. Re-implementing that orchestration here to
# get a kwarg through would be the drift this release is trying to stop.
binding = {"session_id": session or None, "base_commit": head or None}
_orig_build_record = pe.build_record
def _build_record_bound(pre_eval_id, req, verdict, localization, *a, **kw):
    kw["binding"] = dict(binding,
                         declared_paths=declare(localization.get("resolved_paths")))
    return _orig_build_record(pre_eval_id, req, verdict, localization, *a, **kw)
pe.build_record = _build_record_bound

t3 = os.environ.get("V_TRIAGE_T3_CATEGORY") or None
res = pe.run_preeval(request, repo=REPO, t3_category=t3)

if res.get("pre_eval_disabled"):
    print("pre_eval.enabled is false — the stage is a no-op and this change is %s."
          % pe.DECISION_TO_TIER[pe.DECISION_FULL])
    raise SystemExit(0)

if res.get("needs_t3"):
    print("NEEDS T3: the deterministic layers cannot band this request. Run the light "
          "classify Task with the prompt below, then re-invoke with "
          "V_TRIAGE_T3_CATEGORY=<%s>." % "|".join(pe.T3_CATEGORIES))
    print("--- t3 prompt ---")
    print(res["t3_prompt"])
    raise SystemExit(0)

rec, pid = res["record"], res["pre_eval_id"]
decision = rec["decision"]
tier = pe.DECISION_TO_TIER.get(decision)          # never re-spelled here
paths = (rec.get("localization") or {}).get("resolved_paths") or []

# The taxonomy as PINNED BY THIS RECORD — the immutable pre-edit snapshot predicate 8
# re-validates against later. Reading it back (rather than re-reading .claude/) is what
# makes predicate 3 a real digest match instead of a restatement.
snap = os.path.join(REPO, "docs", "superpowers", "pre-eval",
                    pid + ".taxonomy-snapshot.yaml")
taxonomy = snap_digest = None
if os.path.isfile(snap):
    with open(snap, "rb") as fh:
        snap_bytes = fh.read()
    snap_digest = tx.taxonomy_digest_bytes(snap_bytes)
    taxonomy = tx.load_taxonomy(text=snap_bytes.decode("utf-8"))

# Predicate 6's test-path set. The taxonomy has no test-file key, so this is a
# deliberately BROAD heuristic: every extra shape it catches removes a change from the
# auto-route class, which is the safe direction. Widen it freely; narrowing it is a
# policy change.
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

single = pe._is_single_literal_path(paths)
one = paths[0] if single else None
ar = tx.match_auto_route(taxonomy, one) if (taxonomy and one) else None
bands_known = (rec["difficulty"]["band"] in ("low", "medium", "high")
               and rec["impact"]["band"] in ("low", "medium", "high"))

P = []
P.append((1, "tier is DIRECT and no override fired",
          decision == pe.DECISION_FASTPATH and rec["override_fired"] is None,
          "decision=%s override_fired=%s" % (decision, rec["override_fired"])))
P.append((2, "exactly one resolved path, and it is a literal", single,
          "resolved_paths=%s" % (paths,)))
P.append((3, "taxonomy present, digest-matched, bands not unknown",
          bool(taxonomy) and snap_digest == rec.get("taxonomy_digest") and bands_known,
          "snapshot=%s record=%s bands=%s/%s"
          % (snap_digest, rec.get("taxonomy_digest"),
             rec["difficulty"]["band"], rec["impact"]["band"])))
P.append((4, "path matches auto_route_allow", bool(ar and ar["allowed"]),
          "; ".join(ar["reasons"]) if ar else "not evaluated (no single literal path)"))
P.append((5, "path matches NO entry in the sensitive set",
          bool(ar and not ar["sensitive"]),
          "sensitive=%s" % (ar["sensitive"] if ar else "not evaluated")))
P.append((6, "no test file touched", bool(one) and not is_test_path(one),
          "path=%s" % one))

print("")
print("pre_eval_id : %s" % pid)
print("TIER        : %s   (decision %s)" % (tier, decision))
print("record      : %s" % res["record_ref"])
print("binding     : session_id=%s base_commit=%s declared_paths=%s"
      % (rec.get("session_id"), rec.get("base_commit"), rec.get("declared_paths")))
print("")
print("auto-route predicates (spec A4):")
for n, name, okp, why in P:
    print("  %d. [%s] %s — %s" % (n, "PASS" if okp else "FAIL", name, why))
for n, name in ((7, "floor run and passed (+ full_command when unattended)"),
                (8, "full post-diff re-validation"),
                (9, "circuit breaker armed")):
    print("  %d. [ -- ] %s — deferred to `/v:triage --land %s`" % (n, name, pid))

member = all(okp for _, _, okp, _ in P)
print("")
if decision != pe.DECISION_FASTPATH:
    print("NOT in the auto-route class: %s requires a human offer and acceptance." % tier)
elif member:
    print("IN the auto-route candidate class on predicates 1-6. Make the change, then run "
          "`/v:triage --land %s` — it enforces 7, 8 and 9 and commits, or demotes to %s."
          % (pid, pe.DECISION_TO_TIER[pe.DECISION_SCOPED]))
else:
    print("DIRECT, but NOT auto-routable — implement it, then offer it to the user as usual.")
PY
```

### T3. Commit the record

The engine deliberately **never runs git**; committing is this command's job, and it is not
optional. An uncommitted record is invisible to the Stop-hook triage gate (which reads committed
files back with `jq`) and is destroyed by `git worktree remove` the moment a branch is merged or
discarded — the v2.6.4 data-loss shape.

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

- **DIRECT, in the class** → make the change, then `/v:triage --land <id>`.
- **DIRECT, not in the class** → implement, then offer it to the user as usual.
- **SCOPED** → `/v:orchestrate` (manifest, run dir, scope gate, floor, one combined SPEC+QUALITY review; recon and the three pre-flights are skipped).
- **FULL** → the unchanged pipeline.

---

## Phase L — the landing gate

Run **after** the edit and **instead of** `git commit`. It refuses anything that is not a DIRECT
record, demotes on any predicate failure, and records the demotion. Set `V_TRIAGE_DRY_RUN=1` to
evaluate 7, 8 and 9 and stop before the CAS window.

```bash
V_TRIAGE_ID='<pre_eval_id>' V_TRIAGE_MESSAGE='<commit message>' python3 - <<'PY'
import hashlib, importlib.util, json, os, subprocess, sys

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

def git(*args):
    return subprocess.run(["git", "-C", REPO] + list(args),
                          capture_output=True, text=True)

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

def revalidate():
    """Predicate 8, in full, against the immutable pre-edit snapshot. Returns
    (ok, [reasons], realised_diff_digest). Called once before the lock and AGAIN inside
    it — the second call is the one the commit is actually authorised by."""
    why = []
    st = [p for p in git("diff", "--cached", "--name-only", "-z").stdout.split("\0") if p]
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
    for row in git("diff", "--cached", "--numstat", "--no-renames",
                   "-z").stdout.split("\0"):
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
    blob = git("diff", "--cached", "--no-color").stdout
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
        floor = fr.run_test_floor(REPO, "HEAD", changed_paths=list(staged),
                                  test_commands=slice_["resolved_commands"])
        floor["bound_diff_digest"] = realised_digest
        ok7 = bool(floor.get("passed")) and not floor.get("merge_blocked")
        if not ok7:
            why7.extend(floor.get("reasons") or ["the floor did not pass"])
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
        floor = fr.run_test_floor(REPO, "HEAD", changed_paths=list(staged),
                                  test_commands=slice_["resolved_commands"])
        floor["bound_diff_digest"] = digest_now
        ok7 = bool(floor.get("passed")) and not floor.get("merge_blocked")
        why7 = [] if ok7 else (floor.get("reasons") or ["the floor did not pass"])
    ok9, br, why9 = breaker()
    report("in-lock")

    if not (ok7 and ok8 and ok9):
        demote(why7 + why8 + why9)
        raise SystemExit(2)

    tree = git("write-tree").stdout.strip()
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
    "diff_digest": digest_now,
    "taxonomy_digest": pinned,
    "floor": {"tier_used": floor.get("tier_used"), "passed": floor.get("passed"),
              "checks": floor.get("checks"), "bound_diff_digest": digest_now,
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

- **Never widen the class.** `auto_route_allow`, the `sensitive` set and the line budget come from
  the taxonomy through `match_auto_route`; do not add a special case here.
- **Never edit the taxonomy inside a landing.** The two policy files are sensitive in code
  (`compound-v-taxonomy.MANDATORY_SENSITIVE`) as well as in this repo's taxonomy, so a taxonomy that
  forgets them still cannot be self-widened — but the digest check is what makes that guarantee hold
  across the edit.
- **Never force the commit.** If the CAS refuses, something moved HEAD; demote and let a human look.
- **Never invent a session id.** An empty `CLAUDE_CODE_SESSION_ID` means the record covers nothing;
  say so.
- **No fabricated metrics.** Print the floor's real exit codes and the breaker's real rate, nothing
  derived or estimated.

## Selftest — `tests/test-triage-landing.sh`

Phase L's proofs live in **`tests/test-triage-landing.sh`**. Run it from the repo root; it exits
non-zero on any failure, and CI's `tests` job discovers it recursively and always runs it.

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
the outcome stream), and predicate 7 refusing an unattended landing against a red contract, an
absent one, and one with no `full_command`. Each attack is paired with a control that LANDS, and
with a planted mutation that removes the corresponding check from a copy of the gate and is
asserted to turn that attack's assertion red.

**What this replaced, and why.** The fixture that used to sit here asserted `staged ==
["OTHER.md"]` (a fact about `git add`), that two sha256 digests differ (a fact about sha256), and
that `git update-ref` honours an expected old value (a fact about git). Phase L could have been
deleted from this file and all fifteen of its assertions would still have passed. It was also
outside CI — the sweep covers `scripts/*.py --selftest` and `tests/**`, and `commands/` is in
neither — so nothing ever ran it. Its trailing `build_record` binding assertions were a duplicate
of `scripts/compound-v-preeval.py --selftest`, which CI does run.

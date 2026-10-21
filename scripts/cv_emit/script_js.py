"""The emitted workflow script: stage schemas, the JS template and emit_script."""

from __future__ import annotations

import re

from .util import (
    STAGE_PHASES, _js_json, neutralize_in_data,
)
from .retry import (
    escalation_map, retry_config,
)
from .recall import (
    RECALL_EVIDENCE_MAX, RECALL_REASON_LABELS,
)
from .prompts import (
    _constraint_lines, _interface_lines,
)
from .plan import (
    PROVISION_TIMEOUT_DEFAULT,
)


# --------------------------------------------------------------------------- #
# the emitted workflow script
# --------------------------------------------------------------------------- #
IMPLEMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "worktree", "summary"],
    "properties": {
        "status": {"type": "string", "enum": ["ok", "error"]},
        # A LOCATOR, not evidence. The Implement stage returns a raw result and
        # NEVER a `job_result`: job_result carries blocked/files_changed/
        # violations, which this project's contract says are git-derived by the
        # caller. Asking the implementer to report its own enforcement fields is
        # the fabricated-evidence pattern with extra steps.
        "worktree": {"type": "string"},
        "summary": {"type": "string"},
        "notes": {"type": "string"},
    },
}

GATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["job_id", "verdict", "source"],
    "properties": {
        "job_id": {"type": "string"},
        "verdict": {"type": "string", "enum": ["pass", "blocked", "error"]},
        "source": {"type": "string"},
        "receipt_path": {"type": "string"},
        "baseline_commit": {"type": "string"},
        "realised_commit": {"type": "string"},
        "diff_digest": {"type": "string"},
        "exit_code": {"type": "integer"},
        "raw_stdout": {"type": "string"},
        "reason": {"type": "string"},
        # The tree the gate ACTUALLY measured, carried forward so Record does not
        # have to reconstruct it. 3.0.1 threw this away and rebuilt a locator from
        # lane-map.json, which holds the WRAPPER agent's project cwd — so a codex
        # job whose worker changed files in its own worktree was recorded against
        # an unchanged tree and its valid patch never reached the project. Empty
        # string for a `direct` job: there is no worktree, and that is a value.
        "worktree": {"type": "string"},
        # gate-receipt emits `tests` on a passing verdict, and this object is
        # additionalProperties:false — so without this line the Gate agent's own
        # structured result was invalid on every clean happy path.
        "tests": {"type": "object"},
    },
}

FINALIZE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["wave", "integrated"],
    "properties": {
        "wave": {"type": "integer"},
        "integrated": {"type": "boolean"},
        "commit": {"type": "string"},
        "merged": {"type": "array", "items": {"type": "string"}},
        "refused": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
        # The FINALIZER reports whether it appended the run's triage `actual`.
        # It moved here from RECORD in the fourth review pass: the append must
        # happen after the integration authority has re-derived this wave, never
        # between a direct-mode job's gate and that re-derivation.
        "triage_actual": {"type": "string"},
    },
}

RECORD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["job_id", "recorded"],
    "properties": {
        "job_id": {"type": "string"},
        "recorded": {"type": "boolean"},
        "merged": {"type": "boolean"},
        "status": {"type": "string"},
        "result_path": {"type": "string"},
        "reason": {"type": "string"},
        # NO `triage_actual` HERE. Record no longer appends the run's triage
        # `actual` — that write is the finalizer's, after the authority (fourth
        # review pass). RECORD_SCHEMA is additionalProperties:false, so declaring
        # a field the ack cannot emit is dead schema, and the ack emitting a
        # field the schema does not declare would make Record's structured result
        # invalid. Both halves moved together, to FINALIZE_SCHEMA.
    },
}

INTEGRATED_JOBS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["integrated"],
    "properties": {
        # Job ids state.json already records `merged.integrated: true` for, read
        # ONCE before wave 0 (see `alreadyIntegratedIds` below and
        # `cmd_integrated_jobs`). A transport ack, not a verdict: it never
        # decides at-most-once by itself, and the finalizer's git-derived check
        # stays the last line of defence.
        "integrated": {"type": "array", "items": {"type": "string"}},
    },
}


def _implement_prompt(job, plan):
    """The implementer's prompt. Ends with the enforcement-field lock."""
    lines = []
    if job.get("agent_type"):
        # Spawned BY ROLE. The role contract lives in that agent's own
        # definition, so this prompt supplies the job's inputs and nothing else —
        # restating the contract here is how the two copies drift apart.
        # Deliberately ROLE-NEUTRAL wording. Until 3.4.0 only the reviewer arrived
        # by role, and this line said "your passes and your verdict vocabulary" —
        # reviewer language that reads as nonsense to an implementer, which is now
        # the other role that lands here.
        lines.append("You are spawned as `%s`. Your role and its standing "
                     "instructions come from your OWN agent definition; this "
                     "prompt carries only Compound V job `%s`'s inputs."
                     % (job["agent_type"], job["id"]))
    else:
        lines.append("You are the implementer for Compound V job `%s`." % job["id"])
    lines.append("")
    lines.append("TITLE: %s" % job["title"])
    lines.append("")
    lines.append("FIRST COMMAND, BEFORE ANY OTHER TOOL CALL — register your lane.")
    lines.append("This is what lets `hooks/lane-guard.sh` resolve which job an")
    lines.append("out-of-lane write belongs to. Without it the guard resolves")
    lines.append("nothing, fails open, and silently allows every write.")
    lines.append("")
    # A LITERAL PATH, NEVER A SHELL SUBSTITUTION. The clamp matches a literal
    # command prefix and refuses a command whose structure it cannot verify;
    # `"$PWD"` and `$(...)` are exactly that structure, so the very first command
    # of a real run (2026-09-02, run r9) was DENIED for the `--cwd "$PWD"` this
    # block used to render — before the job could register at all, which is the
    # one failure that silently disarms the lane guard for the whole job. `pwd`
    # is itself an admitted form (IMPLEMENT_SHELL), so the worker runs it and
    # pastes what it printed.
    #
    # The isolation below is the AGENT layer's, not the manifest's: register-lane
    # uses it to decide both where to pin the baseline and whether to take the
    # pre-existing snapshot, and a depends_on job runs its agent in the project
    # checkout while declaring `worktree` in the manifest — passing the manifest
    # value here meant the job that most needs the snapshot, the one gated in a
    # shared already-dirty tree, was the only one that never got it.
    lines.append("Run `pwd` first — it is admitted — and write the absolute path")
    lines.append("it prints in place of `<ABSOLUTE_CWD>` below, LITERALLY. The")
    lines.append("clamp refuses shell substitution of any kind: a variable")
    lines.append("expansion or a nested command is structure it cannot verify,")
    lines.append("and a real run's very first command was denied for exactly")
    lines.append("that — before the job could register, which leaves the lane")
    lines.append("guard with nothing to resolve for the rest of the job.")
    lines.append("")
    lines.append("```bash")
    lines.append("pwd")
    lines.append("```")
    lines.append("")
    lines.append("```bash")
    # `--recall-check-json` rides along ONLY where recall actually found a
    # pattern. It is the same file `emit` wrote, so state.json records the
    # verdict the prompt was built from — not a second, later reading of a
    # results root that has moved on since.
    lines.append('%s -B %s register-lane --run-dir %s --job-id %s '
                 '--cwd <ABSOLUTE_CWD> --repo-root %s --isolation %s%s'
                 % (plan["python"], plan["emitter"], plan["run_dir"], job["id"],
                    plan["repo_root"],
                    "worktree" if job.get("agent_isolation") == "worktree" else "direct",
                    (" --recall-check-json %s" % job["recall_check_file"])
                    if job.get("recall_check_file") else ""))
    lines.append("```")
    lines.append("")
    if job.get("agent_isolation") == "worktree" and job.get("provision_command"):
        # THE HARNESS DEFAULT WOULD KILL THE INSTALL.
        #
        # register-lane runs this job's `provision_command` inside the fresh
        # worktree before anything else, and it is an ordinary agent Bash call —
        # whose default ceiling is 120 s. A `provision_timeout_s` of 600 buys
        # nothing if the call wrapping it is cut at two minutes: the install dies
        # half-done, no snapshot is taken, and the gate blocks the job over the
        # very `node_modules/` this feature exists to subtract. The Gate stage's
        # prompt already carries an explicit timeout for the same reason; this is
        # that shape, sized from the declared bound plus a minute of headroom and
        # capped at the harness maximum.
        _prov_ms = min(600000,
                       ((job.get("provision_timeout_s") or PROVISION_TIMEOUT_DEFAULT)
                        + 60) * 1000)
        lines.append("Call the Bash tool with `timeout: %d` for that command: it runs"
                     % _prov_ms)
        lines.append("this job's `provision_command` (%s) inside your worktree first,"
                     % job["provision_command"])
        lines.append("bounded at %d s, and the harness's 120 s default would kill the"
                     % (job.get("provision_timeout_s") or PROVISION_TIMEOUT_DEFAULT))
        lines.append("install half-done — which BLOCKS you for files you did not write.")
        lines.append("")
    lines.append("That command also PINS this job's baseline commit before anything")
    lines.append("changes, and it fails closed if it cannot. A gate measured against a")
    lines.append("HEAD that moved is a gate that passes the run it should have caught.")
    lines.append("")
    lines.append("Run Python with `-B` (or export PYTHONDONTWRITEBYTECODE=1) for EVERY")
    lines.append("python command you issue: the scope gate forgives no path by")
    lines.append("extension, so a stray .pyc left outside your lane BLOCKS your job.")
    lines.append("")
    if job["backend"] != "claude" and job["launch_command"]:
        lines.append("THIS JOB RUNS ON AN EXTERNAL BACKEND (%s)." % job["backend"])
        lines.append("You do not implement it yourself. Run EXACTLY this command — every")
        lines.append("argument is already materialized, including the prompt file, which")
        lines.append("was written before this workflow started. Do not edit it, do not")
        lines.append("substitute values, do not add flags. The worker creates and OWNS its")
        lines.append("own git worktree — you are at `direct` isolation precisely so no")
        lines.append("worktree is nested inside another:")
        lines.append("")
        lines.append("```bash")
        lines.append(job["launch_command"])
        lines.append("```")
        lines.append("")
        lines.append("Call the Bash tool with `timeout: 600000` (ten minutes, the harness")
        lines.append("maximum): the worker's own cap is set below it on purpose, and a")
        lines.append("command the harness detaches to the background leaves you with no")
        lines.append("job_result to return — a worker you did not wait for is a job that")
        lines.append("did not run.")
        lines.append("")
        lines.append("The full argv is also committed at `%s`, so the invocation that ran"
                     % job["launch_argv_file"])
        lines.append("is a file in the run directory and not a reconstruction. The task")
        lines.append("itself is `%s`." % job["prompt_file"])
        lines.append("")
        lines.append("When the worker finishes, return the ABSOLUTE worktree it reports")
        lines.append("(the `worktree` field of its job_result) as your `worktree` — that")
        lines.append("is the tree the Gate will measure. Never return your own `pwd`; you")
        lines.append("did not change anything in it.")
        lines.append("")
    elif job.get("agent_isolation") == "worktree":
        lines.append("You are running in your OWN git worktree. Return its absolute path")
        lines.append("(`pwd`) as `worktree` — that is the tree the Gate measures.")
        lines.append("")
    elif job["isolation"] == "worktree":
        # A dependent job under the 3.0.5 rule: manifest says worktree, the agent
        # runs in the main checkout. Say so — the three layers must agree
        # (finding 60), and the worker must not report a worktree it never had.
        lines.append("You are running in the MAIN checkout (a dependent job; the manifest's")
        lines.append("`isolation: worktree` is for scope attribution). Return an empty")
        lines.append("`worktree`; the Gate measures the main tree in direct mode.")
        lines.append("")
    else:
        lines.append("You are running at `direct` isolation, in the project checkout")
        lines.append("itself. Return `worktree` as the EMPTY STRING. A direct job has no")
        lines.append("worktree to merge from, and reporting your `pwd` there is what made")
        lines.append("3.0.1 apply a direct job's patch into a different repository.")
        lines.append("")
    lines.append("WRITE-ALLOWED (your lane — anything else is a scope violation):")
    for glob in job["write_allowed"]:
        lines.append("  - %s" % glob)
    lines.append("")
    # v3.4.17: the plan's project-wide constraints, then this job's interface
    # contract — in that fixed order, before the acceptance list. Superpowers
    # 6.2.0 added both sections to writing-plans FOR the isolated implementer,
    # and this prompt is where that isolation is at its most complete. Absent on
    # a pre-6.2.0 plan ⇒ neither block is rendered.
    lines += _constraint_lines(plan.get("global_constraints"),
                               "GLOBAL CONSTRAINTS (binding on every job in this run):")
    lines += _interface_lines(job.get("interfaces"),
                              "INTERFACES (your only view of the neighbouring jobs):")
    if job["acceptance"]:
        lines.append("ACCEPTANCE (your definition of done):")
        for item in job["acceptance"]:
            lines.append("  - %s" % item)
        lines.append("")
    # ---- PRIOR FAILURES ON THIS LANE ------------------------------------- #
    # Evidence, delivered where an implementer will actually see it, with a
    # budget attached. Recall that arrives as an open-ended "go research your
    # lane" instruction spends the turns the job needs for the work — and this
    # repository has already shipped one recall instruction that was unreachable
    # and one that was unbudgeted.
    _recall = job.get("recall_check") or {}
    if _recall.get("verdict") == "tighten" and _recall.get("evidence"):
        lines.append("## Prior failures on your lane")
        lines.append("")
        lines.append("Recall (`compound-v-memory.py recall-check`, run at emit time) found %d"
                     % _recall.get("match_count", 0))
        lines.append("recorded job_result(s) that FAILED on files matching your write-allowed")
        lines.append("lane, for a reason attributable to that job's own work (a scope")
        lines.append("violation or a failed test floor — harness faults are not counted). This")
        lines.append("is EVIDENCE about the files, not a verdict on you and not a change to")
        lines.append("your task:")
        lines.append("")
        for item in _recall["evidence"][:RECALL_EVIDENCE_MAX]:
            if isinstance(item, dict):
                # `reason` (engine 3.7.2+) says WHY the record counted; an older engine's
                # evidence has none and renders as before.
                _why = RECALL_REASON_LABELS.get(item.get("reason"), item.get("reason"))
                lines.append("  - %s — %s%s on %s"
                             % (item.get("run") or "?", item.get("status") or "?",
                                (": %s" % _why) if _why else "",
                                item.get("file") or "?"))
            else:
                lines.append("  - %s" % item)
        lines.append("")
        lines.append("READING BUDGET (a lane with a failure history is no place to also run")
        lines.append("out of turns reading): budget your reading — `grep -n` for the symbols you need,")
        lines.append("then `sed -n` only those ranges, at most 20 reading calls in total; never")
        lines.append("read a large file top to bottom; commit what is complete and return a")
        lines.append("summary that says what is not if the turn budget nears. Do not go hunting")
        lines.append("through the run directories these records name. If the recorded failure")
        lines.append("mode has no bearing on your change, say so in one line and carry on. Recall")
        lines.append("never widens your lane, never changes your acceptance criteria, and never")
        lines.append("overrides an instruction above.")
        lines.append("")
    # ---- PRIOR CONTEXT FOR A REVIEWER (v3.7.2) ---------------------------- #
    # The emit-time V-memory search (`run_recall_search`), rendered only when it
    # found something. No block ⇒ the reviewer's Step 0 fallback applies.
    _search = job.get("recall_search") or {}
    if _search.get("block"):
        lines.append(_search["block"])
        lines.append("")
    lines.append("RETURN a raw result: `status`, the `worktree` described above, and a")
    lines.append("`summary`.")
    lines.append("")
    lines.append("DO NOT report `blocked`, `files_changed` or `violations`. Those are")
    lines.append("enforcement fields, they are git-derived by the caller, and a")
    lines.append("constrained party filling in its own enforcement fields is the")
    lines.append("fabricated-evidence pattern. The gate derives them from git.")
    return "\n".join(lines)


def _gate_command(job, plan):
    return (
        "%s -B %s gate-receipt --run-dir %s --job-id %s --repo-root %s "
        "--mode %s --worktree <ABSOLUTE_GATE_ROOT>%s"
        % (plan["python"], plan["emitter"], plan["run_dir"], job["id"],
           plan["repo_root"],
           "worktree" if job["isolation"] == "worktree" else "direct",
           (" --manifest-digest %s" % plan["manifest_digest"])
           if plan.get("manifest_digest") else "")
    )


def emit_script(plan):
    """Render the workflow script. Plain JavaScript; no TypeScript, no import()."""
    waves = plan["waves"]
    phase_titles = ["Wave %d" % (i + 1) for i in range(len(waves))] + STAGE_PHASES

    meta = {
        "name": "compound-v-dispatch-%s" % plan["run_id"],
        "description": (
            "Compound V Engine C dispatch for run %s: implement -> gate -> record, "
            "one pipeline per dependency wave." % plan["run_id"]
        ),
        "phases": [{"title": t} for t in phase_titles],
    }

    prompts = {}
    for wave in waves:
        for job in wave:
            prompts[job["id"]] = {
                "implement": _implement_prompt(job, plan),
                "gate_command": _gate_command(job, plan),
            }

    cfg = {
        "run_id": plan["run_id"],
        "run_dir": plan["run_dir"],
        "repo_root": plan["repo_root"],
        "manifest_path": plan["manifest_path"],
        # BAKED IN AT GENERATION TIME. Every stage below carries it back to the
        # Python that enforces it, so the lane map the run is measured against is
        # provably the one this script was generated from.
        "manifest_digest": plan["manifest_digest"],
        "python": plan["python"],
        "emitter": plan["emitter"],
        "budget_reserve_per_agent": plan["budget_reserve_per_agent"],
        "narrow_disallowed": plan["narrow_disallowed"],
        "implement_disallowed": plan["implement_disallowed"],
        "transport_model": plan["transport_model"],
        "retry": plan.get("retry") or retry_config({}),
        "escalation": (plan["escalation"] if isinstance(plan.get("escalation"), dict)
                       else escalation_map()),
        "waves": waves,
        "prompts": prompts,
    }

    # ONE NON-RECURSIVE PASS OVER THE TEMPLATE (v3.4.17, cross-model review r1
    # finding 7). This was six sequential `body.replace(...)` calls, and every
    # call after the first re-scanned text that an EARLIER call had just
    # injected. `__CFG__` carries every job prompt verbatim, so a manifest whose
    # constraint, interface line, title, acceptance item or task body contained
    # the literal text `__IMPLEMENT_SCHEMA__` had the raw schema JSON spliced
    # into the middle of a quoted JS string — a syntax error in the emitted
    # script, produced by data the manifest was entitled to write. The same
    # hazard ran the other way: a run_id is id-safe but may contain `__CFG__`,
    # which lands in `__META__`'s JSON and is then eaten by the `__CFG__` pass.
    #
    # `re.sub` with a CALLABLE never rescans its own replacement and never
    # interprets backreferences in it, so each sentinel is substituted exactly
    # once and injected data is inert. Longest-first alternation so no sentinel
    # name can be shadowed by a prefix of another.
    substitutions = {
        "__META__": neutralize_in_data(_js_json(meta)),
        "__CFG__": neutralize_in_data(_js_json(cfg)),
        "__IMPLEMENT_SCHEMA__": _js_json(IMPLEMENT_SCHEMA),
        "__GATE_SCHEMA__": _js_json(GATE_SCHEMA),
        "__RECORD_SCHEMA__": _js_json(RECORD_SCHEMA),
        "__FINALIZE_SCHEMA__": _js_json(FINALIZE_SCHEMA),
        "__INTEGRATED_JOBS_SCHEMA__": _js_json(INTEGRATED_JOBS_SCHEMA),
    }
    pattern = re.compile("|".join(
        re.escape(k) for k in sorted(substitutions, key=len, reverse=True)))
    return pattern.sub(lambda m: substitutions[m.group(0)], JS_TEMPLATE)


# `export const meta = { name, description, phases }` MUST be the FIRST statement
# in the script and meta must be a pure literal — both enforced by the runtime's
# parser, verbatim from the installed binary. Everything after it is the body.
JS_TEMPLATE = r"""export const meta = __META__;

// Compound V — Engine C dispatch script. GENERATED by
// scripts/compound-v-emit-workflow.py from this run's manifest.yaml. Edit the
// manifest and re-emit; do not hand-edit this file, or the committed artefact
// stops being what ran.
//
// Determinism: this runtime makes the wall-clock and RNG globals THROW (the
// no-arg clock read, the random call, and the dynamic module import), because
// they would break resume. Timestamps arrive via `args` instead. The generator
// refuses to write a script containing any of those constructs — and it has to,
// because the runtime's own static check for them runs only on an inline
// `script`, never on the `scriptPath` form Engine C forces.
//
// The script has no filesystem and no shell access. Every side effect happens in
// a spawned agent running ONE clamped Python command, so the logic that decides
// anything is in Python where it can be tested, and the agent is reduced to a
// transport for it.

const CFG = __CFG__;
const IMPLEMENT_SCHEMA = __IMPLEMENT_SCHEMA__;
const GATE_SCHEMA = __GATE_SCHEMA__;
const RECORD_SCHEMA = __RECORD_SCHEMA__;
const FINALIZE_SCHEMA = __FINALIZE_SCHEMA__;
const INTEGRATED_JOBS_SCHEMA = __INTEGRATED_JOBS_SCHEMA__;

// Timestamps must be passed in; the runtime forbids reading a clock.
const NOW = (args && args.now) ? String(args.now) : null;

function q(s) {
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

// ---------------------------------------------------------------------------
// budget — the native ceiling is HARD: once spent() reaches total, further
// agent() calls THROW. A throw inside a stage drops the item to null and skips
// its remaining stages, which is exactly how the audit trail gets lost. So we
// stop SCHEDULING before the ceiling instead of running into it.
// ---------------------------------------------------------------------------
function budgetAllows(n) {
  try {
    if (!budget || budget.total === null || budget.total === undefined) return true;
    const remaining = budget.remaining();
    if (typeof remaining !== 'number') return true;
    return remaining > CFG.budget_reserve_per_agent * n;
  } catch (e) {
    // Reading the budget must never be what stops the run.
    return true;
  }
}

// ---------------------------------------------------------------------------
// withRetry — a transient API death is retried, deterministically.
//
// THE TRIGGER IS A NULL RESOLUTION, not a throw. agent() RESOLVES to null when
// it is skipped or dies on a terminal API error — the three 529s that
// motivated this arrived that way — and only some failures arrive as
// exceptions. Both are retried. NEITHER IS CLASSIFIED HERE: the runtime hands
// the script no error text, so naming the class would be a guess, and Record
// records `other` with a reason that says exactly that.
//
// The wait is the failure policy's table with the randomised term REMOVED,
// because there is nothing to jitter with: the RNG global and every clock read
// are refused by this runtime (deterministic resume). setTimeout is the one
// timing primitive that works here, probed live before this was written.
// Nothing is timed and nothing is stamped — Record stamps the time when it
// writes; a duration this script claimed would be a fabricated measurement.
// ---------------------------------------------------------------------------
async function withRetry(stage, jobId, fn) {
  const retries = [];
  let lastErr = null;
  for (let attempt = 1; attempt <= CFG.retry.max_attempts; attempt++) {
    let r = null;
    try {
      r = await fn();
    } catch (e) {
      r = null;
      lastErr = String(e && e.message ? e.message : e);
    }
    if (r !== null && r !== undefined) {
      return { value: r, retries: retries, exhausted: false,
               last_error: lastErr, attempts: attempt };
    }
    if (attempt < CFG.retry.max_attempts) {
      const wait = Math.min(CFG.retry.cap_ms,
                            CFG.retry.base_ms * Math.pow(2, attempt - 1));
      retries.push({ stage: stage, job: jobId, attempt: attempt, wait_ms: wait });
      log('retry: ' + stage + ' ' + jobId + ' attempt ' + attempt +
          ' produced no result' + (lastErr ? ' (' + lastErr + ')' : '') +
          '; waiting ' + wait + 'ms before attempt ' + (attempt + 1));
      await new Promise(function (res) { setTimeout(res, wait); });
    }
  }
  // EXHAUSTED. The caller falls into exactly the null path it had before this
  // existed: nothing is written less than before, and no stage is made worse.
  return { value: null, retries: retries, exhausted: true,
           last_error: lastErr, attempts: CFG.retry.max_attempts };
}

// Only a REVIEW job is lifted. The manifest's own `type` decides — never the
// model, never the title — and an implementer is never escalated in-run.
function isReviewJob(job) {
  return String(job && job.job_type ? job.job_type : '') === 'review';
}

// The retry log travels Gate -> Record on the verdict object under a name no
// receipt ever carries, and Record strips it before the verdict goes anywhere
// near argv or a file. It is bookkeeping, never part of the gate's verdict.
function withRetryMeta(verdict, meta) {
  const out = Object.assign({}, verdict);
  out.__retry = meta;
  return out;
}

// ---------------------------------------------------------------------------
// Stage 1 — Implement. Returns a RAW result, never a job_result.
// ---------------------------------------------------------------------------
// The registry, not the repository, decides whether an agentType can spawn. When it
// cannot (plugin updated mid-session, not installed, renamed), the role is run from
// its inlined definition instead of the job silently failing its Gate.
function isAgentTypeMissing(err) {
  const m = String(err && err.message ? err.message : err);
  return /agent type '[^']*' not found/i.test(m);
}

// ---------------------------------------------------------------------------
// agentTransport — the ONE place the four clamped, single-command transports
// (Gate, Record, Finalize, Continuity) spawn from. `agents/transport.md`
// (3.6.4) declares `omitClaudeMd: true`, so a spawn that resolves it skips
// loading this repository's own CLAUDE.md/AGENTS.md — real weight for an agent
// whose entire job is "run one command and return its JSON verbatim", spent
// four times per job plus once per wave. `CFG.transport_agent_type` is None
// when the plugin manifest or `agents/transport.md` cannot be resolved at
// emit-time (see `resolve_role_agent_type` in Python) — never guessed — and
// then every call below is the plain, anonymous `agent(prompt, opts)` this file
// ran before 3.6.4.
//
// On `agent type 'transport' not found` this retries ONCE with the identical
// opts minus `agentType` — the SAME fallback `attemptImplement` already uses
// for `implementer`/`spec-reviewer`, and the SAME anonymous shape these four
// stages ran with in every release before this one, so a plugin update or a
// session that never registered the agent degrades to proven behaviour rather
// than failing the job. No other error is caught here: a transport that fails
// for any other reason (a bad clamp, a schema/tools mismatch this repo has not
// yet hit live) must surface as THAT stage's own failure — every one of Gate,
// Record, Finalize and Continuity already fails closed on a thrown error (see
// each stage's own try/catch), so the blast radius of a wrong guess here is a
// FAIL verdict on the affected job, never a silent wrong merge.
// ---------------------------------------------------------------------------
let _transportFallbackLogged = false;
async function agentTransport(prompt, opts) {
  if (!CFG.transport_agent_type) return agent(prompt, opts);
  const withRole = Object.assign({}, opts, { agentType: CFG.transport_agent_type });
  try {
    return await agent(prompt, withRole);
  } catch (err) {
    if (!isAgentTypeMissing(err)) throw err;
    if (!_transportFallbackLogged) {
      _transportFallbackLogged = true;
      log('transport: ' + CFG.transport_agent_type + ' is not loaded in this session — ' +
          'every remaining Gate/Record/Finalize/Continuity spawn falls back to the ' +
          'anonymous transport (loses omitClaudeMd and the definition\'s own maxTurns; ' +
          'disallowedTools and the bashCommandClamp are unchanged, since those come ' +
          'from opts, not from the definition)');
    }
    return await agent(prompt, opts);
  }
}

function implementFailure(job) {
  return { job: job, implement: null, retries: [], escalated_from: null,
           exhausted: false };
}
function inlineDefinition(job, prompt) {
  return 'Your agent definition (' + job.agent_type + ') could not be spawned by role in ' +
    'this session, so it follows verbatim. Follow it exactly, including its Step 0.\\n\\n' +
    job.agent_definition.body + '\\n\\n---\\n\\n' + prompt;
}

async function implementStage(job) {
  try {
    const p = CFG.prompts[job.id];
    const opts = {
      label: 'implement ' + job.id,
      phase: 'Implement',
      schema: IMPLEMENT_SCHEMA
    };
    // An external job's wrapper is a Claude transport (job.agent_model); the
    // backend's own model (job.model) lives in the launch argv, never here.
    if (job.agent_model) opts.model = job.agent_model;
    else if (job.model) opts.model = job.model;
    if (job.effort) opts.effort = job.effort;
    // Narrow at spawn, same as the transport stages — a different list, because an
    // implementer keeps the tools it needs to write code. See IMPLEMENT_DISALLOWED.
    if (CFG.implement_disallowed) opts.disallowedTools = CFG.implement_disallowed;
    if (job.agent_isolation) opts.isolation = job.agent_isolation;
    if (job.implement_clamp) opts.bashCommandClamp = job.implement_clamp;
    // Spawn BY ROLE where the manifest's own job `type` says the work is one of
    // this project's registered agents. Only `type: review` maps today, to the
    // Review Gate — the need the native-mechanisms audit recorded against
    // `agentType`. Gate, Record and Finalize deliberately stay anonymous: they
    // are single-command transports whose safety is `disallowedTools` +
    // `bashCommandClamp`, and every agent definition here declares no `tools:`
    // restriction, so spawning them by role would hand back the whole toolbox.
    if (job.agent_type) opts.agentType = job.agent_type;
    // ONE attempt, fallback included. The by-role fallback answers a DIFFERENT
    // failure — the registry cannot spawn this role — so it lives INSIDE the
    // retried function rather than around it: a transient death retries the
    // whole attempt, fallback and all, and a missing agentType is still fixed on
    // the first try instead of being re-asked of a registry that will not change
    // its mind.
    async function attemptImplement(useOpts) {
      try {
        return await agent(p.implement, useOpts);
      } catch (spawnErr) {
        if (!job.agent_definition || !isAgentTypeMissing(spawnErr)) throw spawnErr;
        log('implement ' + job.id + ': ' + job.agent_type + ' is not loaded in this session — ' +
            'spawning from its inlined definition' +
            (job.agent_definition.max_turns
              ? '; its maxTurns cap of ' + job.agent_definition.max_turns +
                ' is LOST on this path (maxTurns is a property of a registered ' +
                'definition, and agent() has no option to re-impose it)'
              : ''));
        const inl = Object.assign({}, useOpts);
        delete inl.agentType;
        if (!inl.model && job.agent_definition.model) inl.model = job.agent_definition.model;
        return await agent(inlineDefinition(job, p.implement), inl);
      }
    }
    const first = await withRetry('implement', job.id, function () {
      return attemptImplement(opts);
    });
    let raw = first.value;
    let retries = first.retries;
    let escalatedFrom = null;
    // THE REVIEWER LIFT. A reviewer whose every attempt died transiently is
    // re-spawned ONCE on the next rung — the incident this feature exists for
    // is an Opus reviewer three 529s made unavailable. It is a REQUESTED
    // escalation: an org allowlist can substitute a model silently, so the run
    // records what was ASKED FOR and says so in those words.
    //
    // Implementers are never lifted here (the cross-run re-attempt escalation is
    // a different trigger, and it is the one `_is_reviewer_job` guards), and a
    // model that is not a rung — an explicit pin we do not own, or the top of
    // the ladder — has no successor and is left exactly as it was.
    if (first.exhausted && isReviewJob(job) && CFG.retry.escalate_reviewer) {
      const current = opts.model ? String(opts.model).toLowerCase() : null;
      // CFG.escalation is already cut at the stance's ceiling; an explicit
      // manifest pin is never stepped.
      const next = (current && job.model_source !== 'explicit')
        ? (CFG.escalation[current] || null) : null;
      if (next) {
        log('review ' + job.id + ': ' + CFG.retry.max_attempts + ' attempt(s) on ' +
            current + ' produced no result — lifting ONCE to ' + next +
            ' (a requested escalation: an allowlist may substitute another model)');
        const lifted = Object.assign({}, opts);
        lifted.model = next;
        lifted.label = opts.label + ' (escalated)';
        escalatedFrom = current;
        retries = retries.concat([{ stage: 'implement', job: job.id,
                                    attempt: CFG.retry.max_attempts + 1, wait_ms: 0,
                                    escalated_from: current, model: next }]);
        try {
          raw = await attemptImplement(lifted);
        } catch (liftErr) {
          log('review ' + job.id + ': the escalated attempt threw: ' +
              String(liftErr && liftErr.message ? liftErr.message : liftErr));
          raw = null;
        }
      } else {
        log('review ' + job.id + ': NOT lifted — ' +
            (!current ? 'no model is pinned, so there is no rung to step from'
             : job.model_source === 'explicit' ? current + ' is an explicit manifest pin'
             : current + ' is not a rung below the stance escalation ceiling'));
      }
    }
    return { job: job, implement: (raw === undefined ? null : raw),
             retries: retries, escalated_from: escalatedFrom,
             exhausted: Boolean(first.exhausted) && (raw === null || raw === undefined) };
  } catch (e) {
    // A THROW here would drop the item and skip Gate AND Record — the v2.6.4
    // audit-trail loss, structurally. Return the failure as a value instead, so
    // the Gate reads it as null-is-FAIL and Record still writes a result.
    log('implement ' + job.id + ' threw: ' + String(e && e.message ? e.message : e));
    return implementFailure(job);
  }
}

// ---------------------------------------------------------------------------
// Stage 2 — Gate. THIS STAGE MUST NEVER THROW.
//
// A throwing stage drops its item to null and skips every remaining stage, so a
// Gate exception means Record never runs: no state written, no result file, and
// the job silently becomes null — precisely on the jobs that went wrong. Every
// outcome, including "the gate itself failed", comes back as a verdict value.
//
// null is FAIL, never pass. agent() returns null when it is skipped or dies on a
// terminal API error, and a gate that reads null as "no violations found" is
// unreachable exactly when the worker died.
// ---------------------------------------------------------------------------
function gateFailure(jobId, reason) {
  return {
    job_id: jobId,
    verdict: 'error',
    source: 'workflow',
    reason: reason
  };
}

async function gateStage(prev, job) {
  // Declared OUTSIDE the try, so the catch can still carry the retry log. A
  // stage that swallows its own evidence on the way out is the failure this
  // file exists to prevent.
  let meta = { retries: [], exhausted: false, attempts: CFG.retry.max_attempts,
               escalated_from: null };
  try {
    if (prev === null || prev === undefined) {
      return gateFailure(job.id, 'implement stage produced null (skipped, or a terminal API error)');
    }
    meta = { retries: (prev.retries || []).slice(),
             exhausted: Boolean(prev.exhausted),
             attempts: CFG.retry.max_attempts,
             escalated_from: prev.escalated_from || null };
    let impl = prev.implement;
    if (impl === null || impl === undefined) {
      // The runtime hands back null when the implementer hit its turn cap or
      // died. r4 of v3.4.6 (finding 113): the fallback below only saw an EMPTY
      // object, so a null result still voided the wave. A null is the same
      // fact — no locator, unfinished work — so it takes the same path: gate
      // the registered tree with --impl-no-result for a Claude job; an external
      // worker's tree is outside the checkout, so that one still fails closed.
      const externalNull = job.backend && job.backend !== 'claude';
      if (externalNull) {
        return gateFailure(job.id, 'external worker returned null — treated as FAIL, never as a clean tree');
      }
      impl = {};
    }

    // WHERE TO GATE follows where the AGENT actually ran (`agent_isolation`),
    // never whether the agent happened to return a non-empty locator, and never
    // the MANIFEST's isolation — those are two different layers that share a
    // field name. A depends_on job declares `worktree` in the manifest (the
    // validator requires it; scope attribution uses it) and runs its agent in
    // the project checkout, because a fresh worktree branches from the default
    // ref and would not contain the wave that just committed.
    //
    // Reading the manifest value here made Record refuse a perfectly good direct
    // run for "carrying no observed worktree" — the fail-closed rule from 3.0.2
    // firing on a job that was never supposed to have one.
    // An EXTERNAL backend's wrapper agent runs direct (D5.3: no nested worktrees),
    // but the WORK lives in the worker's own worktree, returned as `worktree`.
    // Gating the checkout instead charged the codex job with the run's own
    // bookkeeping files and BLOCKED a green job (stage-4 dogfood, finding 79).
    const externalBackend = job.backend && job.backend !== 'claude';
    let gateRoot;
    let implNoResult = false;
    if (job.agent_isolation === 'worktree' || externalBackend) {
      gateRoot = (impl.worktree || '').trim();
      if (!gateRoot) {
        if (externalBackend) {
          return gateFailure(job.id, 'external worker reported no worktree; there is no tree to gate — fails closed');
        }
        // A Claude worktree job whose implementer returned nothing (turn cap, crash)
        // still has the tree the lane guard enforced: lane-map.json maps that cwd to
        // this job. gate-receipt resolves it and tags the receipt `impl_no_result`,
        // so Record refuses THIS job with a receipt instead of the authority voiding
        // the whole wave for want of one (findings 107/108, two runs lost).
        implNoResult = true;
      }
    } else {
      gateRoot = CFG.repo_root;
      if (!(impl.worktree || '').trim() && !(impl.status || '').trim()) implNoResult = true;
    }

    const cmd = CFG.python + ' -B ' + CFG.emitter + ' gate-receipt' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --job-id ' + q(job.id) +
      ' --repo-root ' + q(CFG.repo_root) +
      ' --worktree ' + q(gateRoot) +
      (implNoResult ? ' --impl-no-result' : '') +
      // The REQUESTED reviewer escalation, onto the receipt. A rung name from
      // CFG.escalation, so there is no caller text in this argv.
      (prev.escalated_from ? ' --escalated-from ' + q(prev.escalated_from) : '') +
      ' --manifest ' + q(CFG.manifest_path) +
      (CFG.manifest_digest ? ' --manifest-digest ' + q(CFG.manifest_digest) : '') +
      // The gate's mode must follow where the AGENT actually ran, not what the
      // manifest declares. A job with depends_on keeps `isolation: worktree` in the
      // manifest (the validator requires it, and scope attribution uses it) while its
      // agent runs in the main checkout, because a fresh worktree branches from the
      // default ref and would not contain the wave that just committed. Passing the
      // manifest's value here made the gate run in worktree mode over a direct run,
      // so it skipped the pre-existing snapshot and charged the job with every dirty
      // path in the tree. Two layers, one field name, opposite meanings.
      ' --mode ' + q((job.agent_isolation === 'worktree' || externalBackend) ? 'worktree' : 'direct') +
      (NOW ? ' --now ' + q(NOW) : '');

    const prompt =
      'Run EXACTLY this one command and return its JSON output verbatim as your ' +
      'structured result. Call the Bash tool with `timeout: 600000` (ten minutes): the command runs the test contract and can exceed the 120 s default, and a command the harness detaches to the background leaves you with no way to read its output — a verdict you did not read is not a verdict. ' +
      'Do not summarise it, do not re-run it, do not run ' +
      'anything else — your shell is clamped to this command form and any other ' +
      'command is denied.\n\n```bash\n' + cmd + '\n```\n';

    const opts = {
      label: 'gate ' + job.id,
      phase: 'Gate',
      schema: GATE_SCHEMA,
      // Transport, not judgment: one clamped command, verbatim JSON back.
      ...(CFG.transport_model ? { model: CFG.transport_model } : {}),
      // Narrow at spawn. Bash stays (a clamp on a Bash-less agent can bind
      // nothing and the runtime refuses the spawn); StructuredOutput stays or
      // schema mode is denied and the spawn is likewise refused.
      disallowedTools: CFG.narrow_disallowed,
      bashCommandClamp: [
        'Bash(' + CFG.python + ' -B ' + CFG.emitter + ' gate-receipt:*)'
      ]
    };

    const gres = await withRetry('gate', job.id, function () {
      return agentTransport(prompt, opts);
    });
    meta.retries = meta.retries.concat(gres.retries);
    if (gres.exhausted) meta.exhausted = true;
    const verdict = gres.value;
    if (verdict === null || verdict === undefined) {
      return withRetryMeta(gateFailure(job.id, 'gate agent returned null — FAIL, never pass'), meta);
    }
    if (!verdict.verdict) {
      return withRetryMeta(gateFailure(job.id, 'gate agent returned no verdict field'), meta);
    }
    return withRetryMeta(verdict, meta);
  } catch (e) {
    // Everything. Including budget exhaustion, which throws.
    return withRetryMeta(gateFailure(job.id, 'gate stage caught: ' + String(e && e.message ? e.message : e)), meta);
  }
}

// ---------------------------------------------------------------------------
// Stage 3 — Record. EVIDENCE ONLY. It writes results/, receipts/ and state.json
// and it touches NOTHING in the main checkout.
//
// Until 3.0.2 this stage called `git apply --index` in the project checkout —
// BEFORE the integration authority had run, and without ever committing. Any
// later plain `git commit` (`/v:orchestrate` runs one) swept that staged patch
// into history, so a job could land with the authority never having run. The
// authority was not defeated; it was bypassed. Integration now belongs to the
// wave finalizer below, which runs the authority FIRST.
//
// Idempotence alone is not enough: a relaunch re-runs every agent that started
// after a failed one, INCLUDING completed ones, so a finished job can implement,
// gate and record a second time. The at-most-once property is keyed to an
// immutable commit hash in Python, not to this stage running once — that stays
// true here, as the last line of defence. But a job the wave loop already knows
// is `merged.integrated` (see `alreadyIntegratedIds` below) is filtered out of
// `wave` before `pipeline(...)` runs at all, so this stage — like Implement and
// Gate — is not even reached for it on a relaunch; only a job this run has not
// yet proven merged still pays for a second implement/gate/record.
// ---------------------------------------------------------------------------
async function recordStage(verdict, job) {
  try {
    const v0 = verdict || gateFailure(job.id, 'record received a null verdict');
    // The retry log is BOOKKEEPING and never part of a verdict: it is lifted off
    // here and passed as its own argument, and the verdict that reaches argv or
    // a receipt comparison is byte-identical to the one the Gate produced.
    const meta = v0.__retry || null;
    const v = Object.assign({}, v0);
    delete v.__retry;
    const cmd = CFG.python + ' -B ' + CFG.emitter + ' record' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --job-id ' + q(job.id) +
      ' --repo-root ' + q(CFG.repo_root) +
      ' --manifest ' + q(CFG.manifest_path) +
      (CFG.manifest_digest ? ' --manifest-digest ' + q(CFG.manifest_digest) : '') +
      // The receipt the gate wrote is the verdict; pass its PATH and the two
      // fields that bind it, never the JSON inline (finding 69: the clamp
      // refuses argv that quotes a checker with `; do … done`). A verdict
      // without a receipt (gateFailure) is small and stays inline.
      (v.receipt_path
        ? ' --verdict-file ' + q(v.receipt_path) +
          ' --expect-verdict ' + q(String(v.verdict || '')) +
          (v.diff_digest ? ' --expect-diff-digest ' + q(String(v.diff_digest)) : '')
        : ' --verdict-json ' + q(JSON.stringify(v))) +
      (meta && (meta.retries.length || meta.exhausted || meta.escalated_from)
        ? ' --retries-json ' + q(JSON.stringify(meta)) : '') +
      (NOW ? ' --now ' + q(NOW) : '');

    const prompt =
      'Run EXACTLY this one command and return its JSON output verbatim as your ' +
      'structured result. Call the Bash tool with `timeout: 600000`. ' +
      'It is idempotent; do not re-run it, and do not run ' +
      'anything else.\n\n```bash\n' + cmd + '\n```\n';

    // Record's OWN retries cannot reach the result it is trying to write, so
    // they are logged and go no further — claiming them in a file this stage
    // never wrote would be the fabrication, not the omission.
    const rres = await withRetry('record', job.id, function () {
      return agentTransport(prompt, {
      label: 'record ' + job.id,
      phase: 'Record',
      schema: RECORD_SCHEMA,
      // Transport, not judgment: one clamped command, verbatim JSON back.
      ...(CFG.transport_model ? { model: CFG.transport_model } : {}),
      disallowedTools: CFG.narrow_disallowed,
      bashCommandClamp: [
        'Bash(' + CFG.python + ' -B ' + CFG.emitter + ' record:*)'
      ]
      });
    });
    if (rres.retries.length) {
      log('record ' + job.id + ' retried: ' + JSON.stringify(rres.retries));
    }
    const ack = rres.value;
    if (ack === null || ack === undefined) {
      return { job_id: job.id, recorded: false, reason: 'record agent returned null' };
    }
    return ack;
  } catch (e) {
    return {
      job_id: job.id,
      recorded: false,
      reason: 'record stage caught: ' + String(e && e.message ? e.message : e)
    };
  }
}

// ---------------------------------------------------------------------------
// Stage 4 — the WAVE FINALIZER. Serialized, once per wave, after the pipeline.
//
// This is the only place a job's work reaches the project checkout, and it does
// three things IN THIS ORDER, in one Python call that fails closed at every step:
//
//   1. run scripts/compound-v-integration-gate.py — the AUTHORITY — over exactly
//      this wave's jobs. Anything other than `permitted` and nothing merges;
//   2. merge the permitted jobs' gate-approved slices into the checkout;
//   3. COMMIT them.
//
// Step 3 is what makes the wave barrier mean anything. A merge that only stages
// leaves the next wave's worktrees — created fresh at HEAD — unable to see their
// prerequisites, and leaves a patch lying in the index for an unrelated commit
// to sweep up. The barrier was documented as doing this since 1.0; it never did.
// ---------------------------------------------------------------------------
async function finalizeWave(waveIndex, wave) {
  const title = 'Wave ' + (waveIndex + 1);
  try {
    const ids = wave.map(function (j) { return j.id; }).join(',');
    const cmd = CFG.python + ' -B ' + CFG.emitter + ' finalize-wave' +
      ' --run-dir ' + q(CFG.run_dir) +
      ' --repo-root ' + q(CFG.repo_root) +
      ' --manifest ' + q(CFG.manifest_path) +
      (CFG.manifest_digest ? ' --manifest-digest ' + q(CFG.manifest_digest) : '') +
      ' --wave ' + q(String(waveIndex + 1)) +
      ' --jobs ' + q(ids) +
      (NOW ? ' --now ' + q(NOW) : '');

    const prompt =
      'Run EXACTLY this one command and return its JSON output verbatim as your ' +
      'structured result. Call the Bash tool with `timeout: 600000`. ' +
      'It runs the integration authority over this wave and, ' +
      'only if the authority permits, merges and commits the wave. Do not ' +
      'summarise it, do not re-run it, do not run anything else.\n\n```bash\n' +
      cmd + '\n```\n';

    const fres = await withRetry('finalize', 'wave-' + (waveIndex + 1), function () {
      return agentTransport(prompt, {
      label: 'finalize ' + title,
      phase: 'Finalize',
      schema: FINALIZE_SCHEMA,
      // Transport, not judgment: one clamped command, verbatim JSON back.
      ...(CFG.transport_model ? { model: CFG.transport_model } : {}),
      disallowedTools: CFG.narrow_disallowed,
      bashCommandClamp: [
        'Bash(' + CFG.python + ' -B ' + CFG.emitter + ' finalize-wave:*)'
      ]
      });
    });
    if (fres.retries.length) {
      log(title + ' finalize retried: ' + JSON.stringify(fres.retries));
    }
    const res = fres.value;
    if (res === null || res === undefined) {
      return { wave: waveIndex + 1, integrated: false,
               reason: 'finalizer agent returned null — nothing is integrated' };
    }
    return res;
  } catch (e) {
    return {
      wave: waveIndex + 1,
      integrated: false,
      reason: 'finalize stage caught: ' + String(e && e.message ? e.message : e)
    };
  }
}

function waveHadFailure(waveSummary, fin) {
  if (!fin || fin.integrated !== true) return true;
  for (let i = 0; i < waveSummary.jobs.length; i++) {
    // 'skipped-integrated' is not a pipeline outcome — nothing ran, because
    // state.json already proved this job merged on a prior attempt — so it must
    // not read as the FAILURE that any other non-'success' status is. Treating
    // it as one would halt every relaunch on the very jobs the skip exists to
    // let through.
    if (waveSummary.jobs[i].status !== 'success'
        && waveSummary.jobs[i].status !== 'skipped-integrated') return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Pre-wave — which jobs state.json ALREADY records as `merged.integrated`,
// read ONCE before wave 0, not per wave. A relaunch (native crash-resume, or
// `/v:resume`'s documented `resume-prepare` then relaunch-by-`scriptPath`: see
// its docstring, which computes the SAME set as this call's `integrated`, just
// from the orchestrator's side) re-executes this script from wave 0 with the
// SAME embedded `CFG.waves` — so without this read, a merged job is handed to
// `pipeline(...)` again: a full Implement spawn, then a Gate spawn whose `git
// diff` runs against a baseline every commit since has moved past, so it can
// only ever refuse (the merge-time twin of finding 146). Reading it via
// `cmd_integrated_jobs` (the same `_load_state` the finalizer's own
// "ALREADY MERGED? ASK GIT, NOT state.json" check reads) is not a second
// source of truth, and it does not decide at-most-once itself — the finalizer
// below, from git, stays the last line of defence; this only skips the two
// spawns that check could never have made worthwhile.
//
// Once is enough for the whole run: integration is monotonic (nothing
// un-merges a job), and a job can only ever be added to this set by a wave
// BEFORE the one asking, never a later one. If this call itself fails (a null
// or malformed ack), it fails OPEN to "nothing known integrated" — the
// pre-existing behaviour of re-running Implement/Gate — rather than guessing;
// that is a wasted spawn, never a wrong merge.
//
// One honest limit: if the runtime's own crash-resume ever replays a prior
// `agent()` call's result BY POSITION instead of re-invoking it, this call
// would replay whatever it answered on the attempt that crashed. That is no
// worse than today: wave 0's Implement and Gate calls are exactly as
// positionally replayed, and this call carries no side effect either way.
// ---------------------------------------------------------------------------
async function alreadyIntegratedIds() {
  const cmd = CFG.python + ' -B ' + CFG.emitter + ' integrated-jobs' +
    ' --run-dir ' + q(CFG.run_dir);
  const prompt =
    'Run EXACTLY this one command and return its JSON output verbatim as your ' +
    'structured result. Do not summarise it, do not re-run it, do not run ' +
    'anything else.\n\n```bash\n' + cmd + '\n```\n';
  const ires = await withRetry('continuity', 'run', function () {
    return agentTransport(prompt, {
      label: 'already-integrated jobs',
      phase: 'Continuity',
      schema: INTEGRATED_JOBS_SCHEMA,
      // Transport, not judgment: one clamped command, verbatim JSON back.
      ...(CFG.transport_model ? { model: CFG.transport_model } : {}),
      disallowedTools: CFG.narrow_disallowed,
      bashCommandClamp: [
        'Bash(' + CFG.python + ' -B ' + CFG.emitter + ' integrated-jobs:*)'
      ]
    });
  });
  if (ires.retries.length) {
    log('already-integrated check retried: ' + JSON.stringify(ires.retries));
  }
  const doc = ires.value;
  if (!doc || !Array.isArray(doc.integrated)) {
    // LOUD, not silent: this is the one path where the fix this stage exists
    // for does not apply, and a relaunch will pay for it again.
    log('already-integrated check produced no usable result — every job in ' +
        'this run will be treated as NOT yet integrated (Implement/Gate will ' +
        're-run for jobs that may already be merged).');
    return [];
  }
  return doc.integrated;
}

// ---------------------------------------------------------------------------
// Waves. Each wave is a BARRIER, and the barrier is load-bearing.
//
// The next wave's agents — hence the next wave's worktrees — are not spawned
// until this wave has been gated by the authority, merged and COMMITTED. Do not
// flatten the waves, and do not move the finalizer inside the pipeline: it has
// to be serialized, because it writes to the one shared checkout.
// ---------------------------------------------------------------------------
const summary = {
  run_id: CFG.run_id, waves: [], stopped_for_budget: false,
  halted: false, halt_reason: null
};

const alreadyIntegrated = await alreadyIntegratedIds();
if (alreadyIntegrated.length) {
  log('relaunch: ' + alreadyIntegrated.length + ' job(s) already integrated — ' +
      alreadyIntegrated.join(', ') + ' — will be skipped before Implement.');
}

for (let w = 0; w < CFG.waves.length; w++) {
  const allJobs = CFG.waves[w];
  const title = 'Wave ' + (w + 1);
  phase(title);

  if (!budgetAllows(allJobs.length)) {
    log(title + ': stopping before the budget ceiling rather than letting agent() throw. ' +
        'Remaining waves are unrun; /v:resume re-dispatches them.');
    summary.stopped_for_budget = true;
    break;
  }

  // Filtered BEFORE `pipeline(...)`, not inside implementStage: a job already
  // proven merged has nothing left for Implement OR Gate to do, and filtering
  // here is what makes both spawns not happen at all, rather than happening
  // and being discarded.
  const wave = allJobs.filter(function (j) { return alreadyIntegrated.indexOf(j.id) === -1; });
  const skipped = allJobs.filter(function (j) { return alreadyIntegrated.indexOf(j.id) !== -1; });

  log(title + ': ' + wave.length + ' job(s) — ' + wave.map(function (j) { return j.id; }).join(', ') +
      (skipped.length ? '; ' + skipped.length + ' already integrated, skipped: ' +
       skipped.map(function (j) { return j.id; }).join(', ') : ''));

  const acks = wave.length
    ? await pipeline(wave, implementStage, gateStage, recordStage)
    : [];

  const waveSummary = { wave: w + 1, jobs: [] };
  // Skipped jobs are reported FIRST and by name — /v:status and a human reading
  // the transcript must see WHY a job in this wave shows no Implement or Gate
  // activity on this relaunch, not read it as silently missing.
  for (let i = 0; i < skipped.length; i++) {
    waveSummary.jobs.push({
      id: skipped[i].id,
      // Not recorded BY THIS RELAUNCH — nothing here wrote results/receipts/
      // state.json this run. It was recorded by whichever earlier attempt
      // actually merged it, and claiming this run recorded it would be the
      // fabricated-evidence pattern this project refuses everywhere else.
      recorded: false,
      status: 'skipped-integrated',
      reason: 'state.json already records merged.integrated for this job; ' +
              'Implement and Gate were not re-run on this relaunch'
    });
  }
  for (let i = 0; i < wave.length; i++) {
    const ack = acks[i];
    waveSummary.jobs.push({
      id: wave[i].id,
      // A null ack means the pipeline dropped the item. That is a FAILURE, and
      // it is reported as one; the integration authority will find no valid
      // receipt for this job and refuse integration.
      recorded: ack ? Boolean(ack.recorded) : false,
      status: ack && ack.status ? ack.status : 'unknown',
      reason: ack && ack.reason ? ack.reason : null
    });
  }

  // The FULL wave — skipped ids included — goes to the finalizer unchanged
  // from before this fix: its own git-derived "ALREADY MERGED?" check (below)
  // already handles a job proven merged, and that at-most-once check is the
  // one this file does not touch.
  const fin = await finalizeWave(w, allJobs);
  waveSummary.finalize = fin;
  summary.waves.push(waveSummary);
  log(title + ' done: ' + JSON.stringify(waveSummary.jobs));
  log(title + ' finalize: ' + JSON.stringify(fin));

  // STOP SCHEDULING after any non-success result. Continuing past a blocked or
  // errored job builds later waves on a base that is missing a prerequisite, and
  // a dependent that silently ran without its dependency is worse than a run
  // that stopped where it broke. /v:resume re-dispatches what is incomplete.
  if (waveHadFailure(waveSummary, fin)) {
    summary.halted = true;
    summary.halt_reason = title + ': ' +
      (fin && fin.integrated === true
        ? 'a job did not reach `success`'
        : ('integration was not permitted — ' + (fin && fin.reason ? fin.reason : 'no reason given')));
    log('HALTED. ' + summary.halt_reason + ' Remaining waves are unrun; ' +
        'inspect the run dir and recover with /v:resume.');
    break;
  }
}

log('Engine C finished. Each wave was gated by scripts/compound-v-integration-gate.py ' +
    'before it merged; the workflow Gate stage is defence in depth and an early exit.');

return summary;
"""

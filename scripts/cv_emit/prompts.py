"""The external handoff paths and the per-job worker prompt."""

from __future__ import annotations

import os
import re

from .roles import (
    job_turn_cap,
)


# --------------------------------------------------------------------------- #
# the external handoff, materialized BEFORE the workflow runs
#
# 3.0.1 emitted the literal string `worker-script ...` as an external job's only
# launcher. There was no argv and no prompt file, so the one thing the worker
# script cannot start without — `--prompt-file` — was left for a model to invent
# at run time, from a prompt that did not contain it. `emit` now writes both
# artefacts into the run dir and puts the COMPLETE argv in the prompt, so the
# invocation is a committed file rather than an instruction to improvise.
# --------------------------------------------------------------------------- #
def worker_prompt_path(run_dir, job_id):
    return os.path.join(run_dir, "jobs", "%s.prompt.md" % job_id)


def launch_argv_path(run_dir, job_id):
    return os.path.join(run_dir, "jobs", "%s.launch.argv.json" % job_id)


def baseline_pin_path(run_dir, job_id):
    """`jobs/<job-id>.baseline` — the PER-JOB pin.

    state.json is one file that every job in a wave writes, so a pin that lived
    only there could be lost to a sibling's last-writer-wins save. This file is
    written by exactly one job and read by the gate, which is what makes "pinned
    before the worker launched" a fact rather than a hope. state.json still gets
    the same value; this is the copy that cannot be raced away.
    """
    return os.path.join(run_dir, "jobs", "%s.baseline" % job_id)


def read_pinned_baseline(run_dir, job_id, state_job=None):
    """The pinned baseline, or None. state.json first, then the per-job pin."""
    pinned = (state_job or {}).get("baseline")
    if isinstance(pinned, str) and re.match(r"^[0-9a-f]{40}$", pinned.strip()):
        return pinned.strip()
    try:
        with open(baseline_pin_path(run_dir, job_id), "r", encoding="utf-8") as fh:
            candidate = fh.read().strip()
    except Exception:  # noqa: BLE001
        return None
    return candidate if re.match(r"^[0-9a-f]{40}$", candidate) else None


# --------------------------------------------------------------------------- #
# v3.4.17 — the two plan fields Superpowers 6.2.0 added for ISOLATED implementers.
#
# `## Global Constraints` (plan header) and a task's `**Interfaces:**` block
# exist precisely because "a task's implementer sees only their own task"
# (SP 6.2.0 skills/writing-plans/SKILL.md:92-93). Compound V's implementers are
# the most isolated of all — a separate agent, often a separate worktree, always
# a separate context — so dropping either field on the way from the plan to the
# prompt removes the only channel that carried it. Both are OPTIONAL: a plan
# written before 6.2.0 has neither section, the manifest then carries neither
# key, and NOTHING is rendered. Ordering is fixed (constraints, then consumes,
# then produces) so two emits of one manifest produce byte-identical prompts.
# --------------------------------------------------------------------------- #
def _job_interfaces(job):
    """Normalize a job's `interfaces` into `{consumes: [...], produces: [...]}`.

    Only non-empty strings survive, and a missing/malformed key becomes an empty
    list — the validator is what REFUSES a malformed block; this renderer never
    invents a signature and never fails a run over one."""
    raw = job.get("interfaces")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in ("consumes", "produces"):
        vals = raw.get(key)
        if not isinstance(vals, list):
            continue
        kept = [v.strip() for v in vals if isinstance(v, str) and v.strip()]
        if kept:
            out[key] = kept
    return out


def _constraint_lines(constraints, heading, bullet="  - "):
    """The GLOBAL CONSTRAINTS block, or `[]` when there are none."""
    kept = [c.strip() for c in (constraints or [])
            if isinstance(c, str) and c.strip()]
    if not kept:
        return []
    lines = [heading, "",
             "Project-wide, and binding on EVERY job in this run including yours.",
             "Copied verbatim from the plan — do not reinterpret, relax or widen",
             "them.", ""]
    lines += ["%s%s" % (bullet, c) for c in kept]
    lines.append("")
    return lines


def _interface_lines(interfaces, heading, bullet="  - "):
    """The INTERFACES block, or `[]` when the job declares none."""
    iface = interfaces if isinstance(interfaces, dict) else {}
    consumes = iface.get("consumes") or []
    produces = iface.get("produces") or []
    if not consumes and not produces:
        return []
    lines = [heading, "",
             "You see only your own job. This block is the ONLY view you get of the",
             "names and signatures neighbouring jobs rely on — implement exactly",
             "these, and do not rename or re-shape them.", ""]
    if consumes:
        lines += ["consumes (what earlier jobs give you):", ""]
        lines += ["%s%s" % (bullet, c) for c in consumes]
        lines.append("")
    if produces:
        lines += ["produces (what later jobs will call):", ""]
        lines += ["%s%s" % (bullet, p) for p in produces]
        lines.append("")
    return lines


def render_worker_prompt(job, run_id, global_constraints=None):
    """The task itself, as the file the worker is handed via `--prompt-file`.

    WHAT THIS TEMPLATE DELIBERATELY DOES NOT ADD: an imperative to verify, to
    re-check, or to report per item. Anthropic's own Opus 5 guidance is that
    explicit verification instructions make the model verify MORE than the task
    needs, and this pipeline already re-derives every enforcement fact from git
    after the worker is gone. The task's own `body` may ask for whatever it likes;
    the template asks for nothing beyond the lanes, the acceptance list and the cap.
    """
    lines = ["# %s" % (job.get("title") or job.get("id")),
             "",
             "Compound V run `%s`, job `%s`." % (run_id, job.get("id")),
             ""]
    # `body` FIRST, because that is what every manifest in this repository writes.
    #
    # This line read `description or prompt or spec` and nothing else. Not one of
    # the twenty-plus manifests written for this release uses any of those three
    # names — they all use `body:` — so the names never intersected and **the task
    # text was silently dropped from every worker prompt**. Workers received a
    # title, their lanes and their acceptance criteria, and no instructions.
    #
    # Five reviews reported it (df10, df11, df12, df18, df20) and it stayed live,
    # because each was read as a one-off finding about that run. Dogfood 25 is the
    # one that closed it, and only because recall had just been made reachable: the
    # reviewer's second query returned all five prior reports at once, and the
    # finding stopped being "a spec gap" and became "the loop is not closing".
    # That is the whole argument for recall, demonstrated on recall's own release.
    body = (job.get("body") or job.get("description")
            or job.get("prompt") or job.get("spec"))
    if isinstance(body, str) and body.strip():
        lines += [body.strip(), ""]
    else:
        # NO TASK TEXT IS NOT A JOB. A prompt carrying only a title and lanes asks a
        # worker to guess, and a guess that lands inside its lane passes every gate
        # this pipeline has — the scope gate checks WHICH files changed, never what
        # they say. Refusing here is the mechanism that would have caught the
        # dropped `body` on its first run instead of its twenty-fifth.
        # A TITLE PLUS ACCEPTANCE CRITERIA IS A TASK. A cross-model review was
        # right that the first version of this refusal broke manifest shapes that
        # were valid before it, and right about the tell: the fixtures were made to
        # pass by injecting synthetic `body` strings rather than by showing the
        # contract required one. This function RENDERS the title and the acceptance
        # list itself, so a job carrying both is not a job with no instructions.
        #
        # What stays refused is the shape that actually caused the damage: lanes and
        # a title and NOTHING to check the work against. That is the prompt a worker
        # has to invent a task from, and an invented task inside its lane passes
        # every gate here.
        acceptance = [a for a in (job.get("acceptance") or [])
                      if isinstance(a, str) and a.strip()]
        title = str(job.get("title") or "").strip()
        if title and acceptance:
            lines += ["_No `body` was declared. The title above and the acceptance "
                      "criteria below are the whole of this task; if they are not "
                      "enough to act on, report BLOCKED rather than inventing "
                      "scope._", ""]
        else:
            raise ValueError(
                "job %r carries no task text and no title+acceptance to stand in "
                "for one: none of `body`, `description`, `prompt` or `spec` is set, "
                "and %s. A prompt with lanes and nothing to check the work against "
                "asks the worker to invent the task, and an invented task that "
                "stays in its lane passes the scope gate — which is how this went "
                "unnoticed for twenty-five runs."
                % (job.get("id"),
                   "the title is empty" if not title
                   else "no acceptance criteria are declared")
            )
    deps = job.get("depends_on") or []
    if isinstance(deps, str):
        deps = [deps]
    if deps:
        lines += ["Prerequisites, already merged and COMMITTED into your base "
                  "before this worktree was created: %s." % ", ".join(deps), ""]
    lines.append("## You are unattended")
    lines.append("")
    lines.append("No one reads this session while it runs and no one will answer a question:")
    lines.append("a turn that ends by asking for confirmation, approval or a preference does")
    lines.append("NOTHING, and the job is then recorded as an absent implementation. Decide")
    lines.append("with the spec, the plan and this prompt; when they are silent, choose the")
    lines.append("smallest change that meets the acceptance, do it, run the checks, and return.")
    lines.append("")

    lines += ["## Write-allowed (your lane — anything else is a scope violation)", ""]
    for glob in (job.get("write_allowed") or []):
        lines.append("- `%s`" % glob)
    lines.append("")
    # v3.4.17: the plan's project-wide constraints and this task's interface
    # contract, in that fixed order. Both absent on a pre-6.2.0 plan ⇒ nothing.
    lines += _constraint_lines(global_constraints,
                               "## Global constraints (binding on every job)",
                               bullet="- ")
    lines += _interface_lines(_job_interfaces(job),
                              "## Interfaces (your only view of the neighbours)",
                              bullet="- ")
    read_allowed = job.get("read_allowed") or []
    if read_allowed:
        lines += ["## Read-allowed (advisory — git cannot enforce reads)", ""]
        for glob in read_allowed:
            lines.append("- `%s`" % glob)
        lines.append("")
    acceptance = job.get("acceptance") or []
    if acceptance:
        lines += ["## Acceptance (your definition of done)", ""]
        for item in acceptance:
            lines.append("- %s" % item)
        lines.append("")
    cap, cap_src = job_turn_cap(job)
    lines += ["Turn cap: %d (%s; default light 30 / standard 50 / deep 80). "
              "Plan to finish inside it." % (cap, cap_src), ""]
    lines += [
        "## What you must NOT report",
        "",
        "Do not report `blocked`, `files_changed` or `violations`. Those are",
        "enforcement fields, they are derived from git by the caller, and a",
        "constrained party filling in its own enforcement fields is the",
        "fabricated-evidence pattern.",
    ]
    return "\n".join(lines) + "\n"

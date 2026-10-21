"""The bashCommandClamp rules for a job's agents."""

from __future__ import annotations

import os

from .util import (
    IMPLEMENT_SHELL,
)


def _clamp_rules(job, python_bin, self_path, worker_script_for):
    """The bashCommandClamp for one job's IMPLEMENT agent.

    Spec D5.1: a non-`claude` job's clamp MUST admit
    `scripts/compound-v-run-<backend>-worker.sh`, or carry no clamp. A clamp that
    can bind nothing makes the runtime refuse the spawn — which fails loudly
    rather than degrading, but it still means the second family cannot launch.

    THE `None` RETURN IS UNREACHABLE FOR A JOB THAT ACTUALLY LAUNCHES, and 3.0.6
    described it wrongly. It happens only for an external backend whose worker
    script is absent — and `job_entry` REFUSES that job outright a few lines later
    ("the handoff cannot be materialized"). A `claude` job always carries the
    register-lane rule. So no implementer that reaches `agent()` is ever unclamped;
    the claim that one could be was a caveat written from reading this function
    alone instead of the path around it. `_check("every launched job carries a
    clamp", ...)` in the selftest now holds that shut.

    Rule syntax is the standard permission rule, validated by the runtime:
    `Bash(<command or prefix>)`, tool name case-sensitive, no whitespace padding
    inside the parens. An entry that parses to a tool with no rule content is an
    "inert clamp entry" and the spawn is refused.
    """
    backend = job.get("backend") or "claude"
    # `-B` IS PART OF THE ADMITTED FORM, and the rule and the command it admits
    # must carry it identically. The scope gate forgives no path by extension
    # since the fourth review pass, so a `__pycache__` entry this plumbing left
    # beside a script is an out-of-lane write that BLOCKS the job. A clamp is a
    # literal prefix match: `<python> -B <script>` in the rule and `<python>
    # <script>` in the command is a DENY, which is why both are built here.
    rules = ["Bash(%s -B %s register-lane:*)" % (python_bin, self_path)]
    # THE RECALL LAYER, READ-ONLY, OR THE INSTRUCTION TO USE IT IS UNREACHABLE.
    #
    # v3.3.3 told five agents to consult V-memory first. Dogfood 24 spawned the one
    # agent Engine C spawns by role and watched it try: the clamp admitted exactly
    # one command form — `register-lane` — and denied the recall query, a third
    # phrasing of it, the `recall-check` bridge, and the form `/v:remember` itself
    # instructs. The instruction was prose in an agent definition; the clamp is
    # mechanism, and mechanism wins. This repository already has a name for that
    # failure and shipped it into the feature meant to demonstrate recall.
    #
    # `search` and `recall-check` only READ: they open a SQLite index outside the
    # repo and print. Admitting them widens no write surface, and the scope gate is
    # unaffected either way — it measures the tree, not the commands.
    memory = os.path.join(os.path.dirname(self_path), "compound-v-memory.py")
    if os.path.exists(memory):
        rules.append("Bash(%s -B %s search:*)" % (python_bin, memory))
        rules.append("Bash(%s -B %s recall-check:*)" % (python_bin, memory))
    # A developer's shell (see IMPLEMENT_SHELL) — tests, selftests, linters,
    # deletions and renames. Denied by omission: network, privilege, scheduler,
    # installs, and every git form that commits or pushes.
    rules.extend(IMPLEMENT_SHELL)
    if backend != "claude":
        worker = worker_script_for(backend)
        if not worker:
            return None  # no clamp at all beats a clamp that cannot launch it
        rules.append("Bash(%s:*)" % worker)
    return rules

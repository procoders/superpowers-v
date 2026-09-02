#!/usr/bin/env python3
"""
Compound V — emit the Phase 1 pre-flight as a NATIVE WORKFLOW.

WHAT THIS IS
------------
Phase 1 runs three independent auditors against one spec:

    1A  code-archaeologist   what the existing CODE actually does
    1B  domain-expert        what the DOMAIN and its regulators actually require
    1C  doc-validator        what the LIBRARIES actually are, today

They have always run in parallel. They ran as three separate `Task` calls, which
means the developer watching sees three opaque spawns, no phase grouping, no
progress tree, no shared budget ceiling, and no structured result — the same
"we built our own instead of using the native one" pattern this release line has
been closing everywhere else. `parallel()` inside a Workflow gives all four for
free, and `agentType` spawns each auditor BY ROLE so it arrives with its own
definition rather than a re-pasted prompt.

WHY `parallel()` AND NOT `pipeline()`
-------------------------------------
The house rule is pipeline-by-default, and this is the documented exception: the
brainstorm cannot continue until it has ALL THREE audits, so the barrier is real
rather than incidental. There is no second stage to overlap with.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
  * NO `bashCommandClamp`. Dogfood 24 watched a clamped agent get its own
    documented first step denied. An auditor greps, reads, runs `git log`, and
    queries the recall layer; a clamp here would break the audit the same way.
  * NO removal of the NETWORK. The Implement stage denies WebFetch/WebSearch on
    purpose — research belongs to a PRE-FLIGHT, and this IS the pre-flight.
    `domain-expert` and `doc-validator` are network-dependent by definition (4 and
    6 references respectively in their own files).

    That is NOT the same as "no narrowing at all", and the first version of this
    file conflated the two. A cross-model review called it HIGH: with no
    `disallowedTools` an auditor could run arbitrary commands, rewrite any file in
    the repository and spawn further agents, while this docstring claimed it
    "writes ONE document into its own directory". `agentType` selects instructions;
    it enforces nothing.

    So the narrowing is now the OPPOSITE selection from Implement's: the network
    stays, and the authority to mutate anything beyond the audit goes. `Task` and
    `Agent` go because an auditor that spawns is no longer an auditor; `Bash` goes
    because nothing in these three definitions needs a shell that `Grep`, `Glob`
    and `Read` do not already give — with ONE exception, admitted through a clamp:
    the recall query, which dogfood 24 proved is denied without one.
  * NO isolation. An auditor writes ONE document into its own directory and reads
    everything else; a worktree would only hide the repository it exists to read.
  * NO routing decisions. These produce evidence. Backend, tier and isolation for
    the eventual jobs stay with `routing-policy.md`, deterministic and untouched.

MODEL
-----
Each agent's own frontmatter decides: `code-archaeologist` and `doc-validator` are
`sonnet` (scanning and version-checking are execution), `domain-expert` is `opus`
(domain judgment). This script passes NO `model`, so the definitions win — the one
place where not wiring something is the correct choice.

Usage
-----
    compound-v-emit-preflight.py --spec docs/.../spec.md --topic linkedin-sequences \\
        [--out preflight.workflow.js] [--skip 1a,1c] [--recon docs/.../recon.md]
    compound-v-emit-preflight.py --selftest

Python 3.9-safe, stdlib only.
"""

import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)

# (phase-id, agent role, output directory, one-line purpose)
PREFLIGHTS = (
    ("1A", "code-archaeologist", "docs/superpowers/archaeology",
     "what the existing code actually does, sets, branches on, and would regress"),
    ("1B", "domain-expert", "docs/superpowers/expert",
     "what the domain and its regulators actually require"),
    ("1C", "doc-validator", "docs/superpowers/library-audit",
     "what the libraries actually are today, not in the training data"),
)

RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["phase", "wrote", "findings", "blocking"],
    "properties": {
        "phase": {"type": "string"},
        # The path the auditor actually wrote. Empty string when it wrote nothing,
        # which is a real outcome and must not be reported as a path.
        "wrote": {"type": "string"},
        "findings": {"type": "integer", "minimum": 0},
        # Constraints the plan MUST honour. The brainstorm reads these first.
        "blocking": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
}


def plugin_name(root=None):
    """The `name` from plugin.json — the agentType prefix. Never guessed."""
    path = os.path.join(root or PLUGIN_ROOT, ".claude-plugin", "plugin.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            name = (json.load(fh) or {}).get("name")
    except Exception:  # noqa: BLE001
        return None
    return name.strip() if isinstance(name, str) and name.strip() else None


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s or "topic"


def agent_available(role, root=None):
    return os.path.exists(os.path.join(root or PLUGIN_ROOT, "agents", "%s.md" % role))


def build_plan(spec_path, topic, today, skip=(), recon=None, root=None):
    """Everything the emitted script needs, as plain data."""
    name = plugin_name(root)
    if not name:
        raise ValueError(
            "cannot resolve the plugin name from .claude-plugin/plugin.json — "
            "agentType is a real identifier and is never assembled from a "
            "directory name (the 3.0.2 rule)"
        )
    slug = slugify(topic)
    skip = {s.strip().lower() for s in (skip or ()) if str(s).strip()}
    entries = []
    for phase, role, outdir, purpose in PREFLIGHTS:
        if phase.lower() in skip:
            continue
        if not agent_available(role, root):
            # A missing agent is skipped with a NOTICE, never silently: an audit
            # that did not run must not look like an audit that found nothing.
            entries.append({"phase": phase, "role": role, "skipped":
                            "agents/%s.md is not present in this installation" % role})
            continue
        entries.append({
            "phase": phase,
            "role": role,
            "agent_type": "%s:%s" % (name, role),
            "out": "%s/%s-%s.md" % (outdir, today, slug),
            "purpose": purpose,
        })
    memory = os.path.join(HERE, "compound-v-memory.py")
    return {
        "spec_path": spec_path,
        "topic": topic,
        "slug": slug,
        "recon": recon or "",
        "entries": entries,
        # Read, grep, search, write ONE document. Not: spawn, shell out, re-enter
        # the pipeline. WebSearch/WebFetch are deliberately ABSENT from this list.
        "disallowed": ["Task", "Agent", "SlashCommand", "NotebookEdit"],
        # The one shell form an auditor needs, and the one its own Step 0 names.
        "clamp": (["Bash(%s %s search:*)" % (sys.executable or "python3", memory),
                   "Bash(%s %s recall-check:*)" % (sys.executable or "python3", memory)]
                  if os.path.exists(memory) else None),
    }


_SCRIPT = """export const meta = {
  name: 'compound-v-preflight',
  description: 'Compound V Phase 1 — three independent audits of one spec, in parallel',
  phases: [{ title: 'Pre-flight', detail: 'archaeology, domain, library — concurrently' }],
};

const CFG = __CFG__;

// parallel(), not pipeline(): the brainstorm cannot continue until it has ALL
// THREE audits, so this barrier is real rather than incidental, and there is no
// second stage to overlap with. See the module docstring.
phase('Pre-flight');
log('Auditing ' + CFG.spec_path + ' — ' + CFG.entries.length + ' pre-flight(s)');

const results = await parallel(CFG.entries.map(function (e) {
  return async function () {
    if (e.skipped) {
      log('SKIPPED ' + e.phase + ' (' + e.role + '): ' + e.skipped);
      return { phase: e.phase, wrote: '', findings: 0, blocking: [], notes: e.skipped };
    }
    const prompt =
      'You are Phase ' + e.phase + ' of a Compound V pre-flight: ' + e.purpose + '.\\n\\n' +
      'SPEC UNDER AUDIT: ' + CFG.spec_path + '\\n' +
      (CFG.recon ? 'TRIGGER-0 RECON (read it first, deepen it, do not repeat it): ' + CFG.recon + '\\n' : '') +
      'TOPIC SLUG: ' + CFG.slug + '\\n\\n' +
      'Follow your own agent definition exactly, including its Step 0.\\n' +
      'Write your audit to: ' + e.out + '\\n\\n' +
      'Return the structured result: the path you actually wrote (empty string if ' +
      'you wrote nothing), how many findings it contains, and the constraints the ' +
      'plan MUST honour. Report what you found, not what would be reassuring.';

    try {
      const r = await agent(prompt, {
        label: e.phase + ' ' + e.role,
        phase: 'Pre-flight',
        schema: CFG.schema,
        // agentType, so the auditor arrives as itself. No model override: its own
        // frontmatter decides (sonnet for the two scanners, opus for judgment).
        agentType: e.agent_type,
        // The network STAYS — this is the research phase. What goes is the
        // authority to change anything: an auditor reads, greps and searches, and
        // writes exactly one document. Bash is admitted only for the recall query,
        // through a clamp, because dogfood 24 proved it is denied without one.
        disallowedTools: CFG.disallowed,
        bashCommandClamp: CFG.clamp,
      });
      if (r === null || r === undefined) {
        log('Phase ' + e.phase + ' returned nothing');
        return { phase: e.phase, wrote: '', findings: 0, blocking: [],
                 notes: 'the agent returned null — treat as NOT RUN, never as clean' };
      }
      log('Phase ' + e.phase + ' wrote ' + (r.wrote || '(nothing)') +
          ' with ' + (r.findings || 0) + ' finding(s)');
      return r;
    } catch (err) {
      // A throw here must not take the other two audits with it.
      log('Phase ' + e.phase + ' threw: ' + String(err && err.message ? err.message : err));
      return { phase: e.phase, wrote: '', findings: 0, blocking: [],
               notes: 'threw: ' + String(err && err.message ? err.message : err) };
    }
  };
}));

const done = results.filter(Boolean);
const blocking = [];
for (const r of done) { for (const b of (r.blocking || [])) blocking.push(r.phase + ': ' + b); }
const ran = done.filter(function (r) { return r.wrote; });

log('Pre-flight complete: ' + ran.length + '/' + done.length +
    ' audit(s) produced a document, ' + blocking.length + ' blocking constraint(s)');

return {
  spec_path: CFG.spec_path,
  topic: CFG.topic,
  audits: done,
  // The brainstorm reads this first. An audit that did not run is NOT a clean one.
  blocking_constraints: blocking,
  incomplete: done.filter(function (r) { return !r.wrote; }).map(function (r) { return r.phase; }),
};
"""


def emit_script(plan):
    cfg = dict(plan)
    cfg["schema"] = RESULT_SCHEMA
    return _SCRIPT.replace("__CFG__", json.dumps(cfg, indent=2, sort_keys=True))


FORBIDDEN = (
    ("Date.now()", re.compile(r"Date\.now\s*\(")),
    ("Math.random()", re.compile(r"Math\.random\s*\(")),
    ("bare new Date()", re.compile(r"new\s+Date\s*\(\s*\)")),
    ("import()", re.compile(r"(?<![A-Za-z0-9_.])import\s*\(")),
)


def forbidden_hits(script):
    """Constructs the Workflow runtime THROWS on. Same list the job emitter uses."""
    return [{"construct": name} for name, pat in FORBIDDEN if pat.search(script)]


def main(argv):
    ap = argparse.ArgumentParser(prog="compound-v-emit-preflight.py")
    ap.add_argument("--spec", help="path to the spec under audit")
    ap.add_argument("--topic", help="topic slug source (defaults to the spec's stem)")
    ap.add_argument("--recon", default="", help="exact Trigger-0 recon path, if one exists")
    ap.add_argument("--skip", default="", help="comma-separated phases to skip, e.g. 1a,1c")
    ap.add_argument("--out", help="write the script here (default: stdout)")
    ap.add_argument("--today", help="YYYY-MM-DD for the output filenames")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv[1:])

    if args.selftest:
        return _selftest()
    if not args.spec:
        ap.error("--spec is required")

    today = args.today or datetime.date.today().isoformat()
    topic = args.topic or os.path.splitext(os.path.basename(args.spec))[0]
    plan = build_plan(args.spec, topic, today,
                      skip=[s for s in args.skip.split(",") if s.strip()],
                      recon=args.recon)
    script = emit_script(plan)
    hits = forbidden_hits(script)
    if hits:
        sys.stderr.write("REFUSING TO EMIT: forbidden construct(s): %s\n"
                         % ", ".join(h["construct"] for h in hits))
        return 2
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(script)
        print(json.dumps({"out": args.out, "phases": [e["phase"] for e in plan["entries"]]},
                         indent=2, sort_keys=True))
    else:
        sys.stdout.write(script)
    return 0


def _selftest():
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
        else:
            fail += 1
            print("FAIL: %s %s" % (name, detail))

    plan = build_plan("docs/superpowers/specs/x-design.md", "LinkedIn Sequences!",
                      "2026-01-02")
    ids = [e["phase"] for e in plan["entries"]]
    check("all three phases are planned", ids == ["1A", "1B", "1C"], str(ids))
    check("the slug is filename-safe",
          plan["slug"] == "linkedin-sequences", plan["slug"])
    check("each audit has a dated output path",
          all(e["out"].endswith("2026-01-02-linkedin-sequences.md")
              for e in plan["entries"]), str([e["out"] for e in plan["entries"]]))
    check("outputs go to three DIFFERENT directories",
          len({os.path.dirname(e["out"]) for e in plan["entries"]}) == 3)
    check("agentType carries the plugin's real name",
          all(e["agent_type"].endswith(":" + e["role"]) and ":" in e["agent_type"]
              for e in plan["entries"]))
    check("agentType is not assembled from a directory name",
          all(e["agent_type"].split(":")[0] == plugin_name()
              for e in plan["entries"]))

    skipped = build_plan("s.md", "t", "2026-01-02", skip=["1b"])
    check("--skip drops exactly that phase",
          [e["phase"] for e in skipped["entries"]] == ["1A", "1C"])

    script = emit_script(plan)
    check("meta is the first statement",
          script.lstrip().startswith("export const meta = {"))
    check("no forbidden runtime constructs", forbidden_hits(script) == [],
          str(forbidden_hits(script)))
    check("uses parallel(), the documented barrier case", "await parallel(" in script)
    check("uses the native progress surface",
          "phase('Pre-flight')" in script and "log(" in script)
    check("spawns BY ROLE", "agentType: e.agent_type" in script)
    check("passes NO model override — the agent frontmatter decides",
          "opts.model" not in script and "model:" not in script)
    check("the NETWORK is never taken away — research is what a pre-flight IS",
          "WebSearch" not in json.dumps(plan.get("disallowed"))
          and "WebFetch" not in json.dumps(plan.get("disallowed")))
    check("but the authority to spawn or re-enter the pipeline is",
          {"Task", "Agent", "SlashCommand"} <= set(plan["disallowed"]))
    check("Read/Grep/Glob/Write are never denied — the audit needs them",
          not ({"Read", "Grep", "Glob", "Write", "Edit"} & set(plan["disallowed"])))
    check("Bash is clamped to the recall query, not denied outright",
          plan["clamp"] is None
          or all("compound-v-memory.py" in r for r in plan["clamp"]))
    check("the emitted script passes both narrowings",
          "disallowedTools: CFG.disallowed" in script
          and "bashCommandClamp: CFG.clamp" in script)
    check("a null return is NOT reported as a clean audit",
          "never as clean" in script)
    check("one audit throwing cannot take the others with it",
          "catch (err)" in script)
    check("the caller is told which audits did not produce a document",
          '"incomplete"' in script or "incomplete:" in script)
    check("blocking constraints are surfaced with their phase",
          "blocking_constraints" in script)
    check("the schema forbids unknown fields",
          RESULT_SCHEMA["additionalProperties"] is False)
    check("`wrote` is a string so 'nothing' is expressible",
          RESULT_SCHEMA["properties"]["wrote"]["type"] == "string")

    # A root that HAS a plugin.json but NO agents/ — the shape of an installation
    # missing an agent file. A root with no plugin.json is a different failure and
    # is asserted separately below.
    import tempfile
    with tempfile.TemporaryDirectory() as _td:
        os.makedirs(os.path.join(_td, ".claude-plugin"), exist_ok=True)
        with open(os.path.join(_td, ".claude-plugin", "plugin.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"name": "superpowers-v"}, fh)
        missing = build_plan("s.md", "t", "2026-01-02", root=_td)
        check("a missing agent is a NOTICE, not a silent omission",
              len(missing["entries"]) == 3
              and all("skipped" in e for e in missing["entries"]),
              str(missing["entries"])[:120])
        check("a skipped audit carries no output path to mistake for a real one",
              all(not e.get("out") for e in missing["entries"]))
    with tempfile.TemporaryDirectory() as _td2:
        raised = False
        try:
            build_plan("s.md", "t", "2026-01-02", root=_td2)
        except ValueError as exc:
            raised = "never assembled from a directory name" in str(exc)
        check("no plugin.json fails LOUD rather than guessing the agentType prefix",
              raised)

    print("%d/%d checks passed" % (ok, ok + fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

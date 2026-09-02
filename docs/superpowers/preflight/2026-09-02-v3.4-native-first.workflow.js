export const meta = {
  name: 'compound-v-preflight',
  description: 'Compound V Phase 1 — three independent audits of one spec, in parallel',
  phases: [{ title: 'Pre-flight', detail: 'archaeology, domain, library — concurrently' }],
};

const CFG = {
  "clamp": [
    "Bash(/opt/homebrew/opt/python@3.14/bin/python3.14 /Users/oleg/Dev/superpowers-v/scripts/compound-v-memory.py search:*)",
    "Bash(/opt/homebrew/opt/python@3.14/bin/python3.14 /Users/oleg/Dev/superpowers-v/scripts/compound-v-memory.py recall-check:*)"
  ],
  "disallowed": [
    "Task",
    "Agent",
    "SlashCommand",
    "NotebookEdit"
  ],
  "entries": [
    {
      "agent_type": "superpowers-v:code-archaeologist",
      "out": "docs/superpowers/archaeology/2026-09-02-v3-4-native-first.md",
      "phase": "1A",
      "purpose": "what the existing code actually does, sets, branches on, and would regress",
      "role": "code-archaeologist"
    },
    {
      "agent_type": "superpowers-v:doc-validator",
      "out": "docs/superpowers/library-audit/2026-09-02-v3-4-native-first.md",
      "phase": "1C",
      "purpose": "what the libraries actually are today, not in the training data",
      "role": "doc-validator"
    }
  ],
  "recon": "",
  "schema": {
    "additionalProperties": false,
    "properties": {
      "blocking": {
        "items": {
          "type": "string"
        },
        "type": "array"
      },
      "findings": {
        "minimum": 0,
        "type": "integer"
      },
      "notes": {
        "type": "string"
      },
      "phase": {
        "type": "string"
      },
      "wrote": {
        "type": "string"
      }
    },
    "required": [
      "phase",
      "wrote",
      "findings",
      "blocking"
    ],
    "type": "object"
  },
  "slug": "v3-4-native-first",
  "spec_path": "docs/superpowers/specs/2026-09-02-v3.4-native-first-design.md",
  "topic": "v3.4-native-first"
};

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
      'You are Phase ' + e.phase + ' of a Compound V pre-flight: ' + e.purpose + '.\n\n' +
      'SPEC UNDER AUDIT: ' + CFG.spec_path + '\n' +
      (CFG.recon ? 'TRIGGER-0 RECON (read it first, deepen it, do not repeat it): ' + CFG.recon + '\n' : '') +
      'TOPIC SLUG: ' + CFG.slug + '\n\n' +
      'Follow your own agent definition exactly, including its Step 0.\n' +
      'Write your audit to: ' + e.out + '\n\n' +
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

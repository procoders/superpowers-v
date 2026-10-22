#!/usr/bin/env python3
"""
Compound V frontmatter linter.

Parses every Markdown file in the plugin and validates its YAML frontmatter
against Claude Code's plugin spec + this project's conventions:

  - Path-class PRESENCE gate (A4): `agents/*.md`, `commands/*.md`, and
    `skills/*/SKILL.md` MUST have a frontmatter block; every other .md is exempt.
    Path classes anchor at the lint root — run from the plugin root, as CI does
    (`python3 scripts/lint-frontmatter.py .`).
  - Frontmatter parses as valid YAML mapping
  - Required `name` and `description` fields present (commands exempt — name = filename;
    the commands/ check uses path.parts, never substring matching — A6; the harness-DATA
    subtrees `.claude/rules/**` and `.claude/agent-memory{,-local}/**` are exempt from
    both, while `.claude/agents|commands|skills/**` classify normally — 3.5.0)
  - `description` <= 500 chars (soft), <= 1024 total frontmatter (hard)
  - No Haiku, except the read-only `v-memory` agent whose tools must be a subset of
    Read, Grep, Glob; no other agent or skill body may name Haiku (v4)
  - `model: opus` REQUIRED on `agents/*.md` (A5), except the Sonnet pre-flight agents
    (code-archaeologist, doc-validator, domain-expert) and v-memory
  - `memory`, when present, is exactly `user` | `project` | `local` (3.5.0), and is
    REQUIRED ABSENT on every agent
  - Closing `---` at EOF without a trailing newline is accepted (A6)
  - Common YAML pitfalls (unquoted globs in `paths`)

Exit 0 = clean, exit 1 = violations found.

Usage: python3 scripts/lint-frontmatter.py [path]
       python3 scripts/lint-frontmatter.py --selftest
"""

import pathlib
import sys

import yaml

DESCRIPTION_SOFT_MAX = 500
FRONTMATTER_HARD_MAX = 1024

# v4 model policy (plan Task 9). Opus by default; Sonnet for the three pre-flight
# agents, whose work is lookups (reading a repository, resolving a library, a bounded
# web search); Haiku for exactly one agent, the read-only `v-memory` docs search
# (Oleg, 2026-10-22), and only while its tools are limited to reading.
SONNET_ELIGIBLE_AGENTS = {
    "code-archaeologist",   # measures existing code; produces findings, decides nothing
    "doc-validator",        # resolves libraries and compares versions against the repo
    "domain-expert",        # ≤4 searches, requirement → source → check
}
HAIKU_ELIGIBLE_AGENTS = {"v-memory"}
HAIKU_TOOLS = {"Read", "Grep", "Glob"}   # a Haiku agent may read; it may not act

# Claude Code's native persistent subagent memory (3.5.0). The field takes exactly
# three scopes, each naming a directory the harness creates on first write:
#   user    -> ~/.claude/agent-memory/<name>/
#   project -> .claude/agent-memory/<name>/          (committed; the recommended default)
#   local   -> .claude/agent-memory-local/<name>/    (gitignored)
# Anything else is not a stricter setting, it is no setting: the runtime ignores an
# unrecognised value and the agent launches with no memory while its file claims one.
MEMORY_SCOPES = ("user", "project", "local")

# v4: no agent carries `memory:` (plan Task 9). Project knowledge lives in
# docs/compound-v/ and is read on demand by `v-memory`; a per-agent memory directory
# would be a second, unreviewed store. `memoryless(name)` is True for every agent
# (all of them).
def memoryless(name: str) -> bool:
    return True


# Path classes (relative to the lint root) that MUST carry frontmatter (A4).
CLASS_AGENT = "agent"
CLASS_COMMAND = "command"
CLASS_SKILL = "skill"


def path_class(rel):
    """Classify a path RELATIVE to the lint root: "agent" | "command" | "skill" | None.

    Uses path.parts, never substring matching (A6) — `mycommands/x.md` or
    `docs/commands-history.md` can no longer masquerade as a command.

    RECURSIVE semantics, deliberate (Codex v2.8 round-1 #7): ANY `.md` under
    `agents/` or `commands/` (nested dirs included) is gated, and ANY file
    literally named `SKILL.md` at ANY depth under `skills/` is gated — stricter
    than the docstring's `skills/*/SKILL.md` glob reads. Rationale: a nested
    `commands/sub/x.md` would still be loaded as a command by the plugin
    runtime, and a reference file has no business being named SKILL.md; if one
    ever legitimately is, rename it rather than weakening the gate.
    """
    parts = rel.parts
    if rel.suffix != ".md":
        return None
    # `.claude/` holds a SECOND copy of the same three path classes — a project-scoped
    # agent, command or skill lives at `.claude/agents/x.md`, `.claude/commands/x.md`,
    # `.claude/skills/foo/SKILL.md` and is loaded by the runtime exactly like the
    # plugin's own. Strip the prefix and classify what is underneath, so a
    # `.claude/agents/implementer.md` carrying `model: sonnet` and `memory: project`
    # meets the same model policy and the same memoryless-role rule as `agents/`.
    # (Codex 3.5.0 round-1 #7: the first cut exempted ALL of `.claude/**` as harness
    # data, which handed those files a blanket pass.) Harness DATA — rules and agent
    # memory — is a different subtree and is handled by is_harness_data below.
    if parts[:1] == (".claude",):
        parts = parts[1:]
    if len(parts) < 2:
        return None
    if parts[0] == "agents":
        return CLASS_AGENT
    if parts[0] == "commands":
        return CLASS_COMMAND
    if parts[0] == "skills" and len(parts) >= 3 and parts[-1] == "SKILL.md":
        return CLASS_SKILL
    return None


# The ONLY subtrees that are harness DATA rather than plugin definition files. Named
# exhaustively on purpose: `.claude/` also holds project-scoped agents, commands and
# skills, and a blanket `.claude/**` exemption gave those a pass on the model policy
# and the memoryless-role rule (Codex 3.5.0 round-1 #7). Adding an entry here is a
# deliberate act, exactly like adding a name to SONNET_ELIGIBLE_AGENTS.
HARNESS_DATA_PREFIXES = (
    (".claude", "rules"),                # project rules: frontmatter is `paths:`, or none
    (".claude", "agent-memory"),         # subagent memory, `project` scope (3.5.0)
    (".claude", "agent-memory-local"),   # subagent memory, `local` scope (gitignored)
)


def is_harness_data(rel):
    """True for the named harness-DATA subtrees under `.claude/` — never for a file
    the runtime loads as an agent, command or skill.

    Two kinds qualify and neither has (or should have) a `name`/`description`:

      * project rules, `.claude/rules/**.md`, whose documented frontmatter is `paths:`
        and nothing else;
      * subagent memory, `.claude/agent-memory{,-local}/<agent>/*.md` (3.5.0) — and
        Claude Code stamps a `modified:` frontmatter field onto a memory file that
        already has frontmatter, so these can acquire a block nobody wrote by hand.

    They are exempt from the two REQUIRED-field rules and from nothing else: still parsed
    as YAML, still rejected for Haiku, still size-capped, still checked for an unquoted
    glob in `paths` — which for a rules file is the pitfall that actually bites.
    """
    return rel.parts[:2] in HARNESS_DATA_PREFIXES


def lint_file(path: pathlib.Path, rel=None) -> list:
    """Lint one file. `rel` is the path relative to the lint root (for path-class
    rules); defaults to `path` itself when the caller has no separate root."""
    issues: list = []
    txt = path.read_text()
    _rel = pathlib.PurePath(rel if rel is not None else path)
    cls = path_class(_rel)
    harness = is_harness_data(_rel)

    if not txt.startswith("---\n"):
        if cls is not None:
            issues.append(
                f"missing frontmatter — {cls} files (agents/*.md, commands/*.md, "
                "skills/*/SKILL.md) must start with a '---' block"
            )
        return issues  # other .md without frontmatter: exempt, not a plugin file

    end = txt.find("\n---\n", 4)
    if end < 0 and txt.endswith("\n---"):
        # Closing --- at EOF without a trailing newline is a VALID close (A6).
        end = len(txt) - len("\n---")
    if end < 0:
        issues.append("no closing --- delimiter")
        return issues

    fm_raw = txt[4:end]

    # Hard char limit
    if len(fm_raw) > FRONTMATTER_HARD_MAX:
        issues.append(
            f"frontmatter is {len(fm_raw)} chars (hard max {FRONTMATTER_HARD_MAX})"
        )

    # Parse
    try:
        data = yaml.safe_load(fm_raw)
    except yaml.YAMLError as e:
        issues.append(f"YAML parse error: {e}")
        return issues

    if not isinstance(data, dict):
        issues.append(f"frontmatter parses as {type(data).__name__}, expected mapping")
        return issues

    # Commands use filename as name; skills/agents need name field. Harness data under
    # `.claude/` has neither by design (see is_harness_data).
    if cls != CLASS_COMMAND and not harness and "name" not in data:
        issues.append("missing required 'name' field")

    if not harness and "description" not in data:
        issues.append("missing required 'description' field")

    desc = data.get("description", "") or ""
    if len(desc) > DESCRIPTION_SOFT_MAX:
        issues.append(
            f"description is {len(desc)} chars (soft max {DESCRIPTION_SOFT_MAX})"
        )

    # Project policy: no Haiku, except the read-only v-memory agent (checked below).
    model = str(data.get("model") or "").strip().lower()
    agent_name = str(data.get("name") or "").strip() if cls == CLASS_AGENT else ""
    if "haiku" in model and agent_name not in HAIKU_ELIGIBLE_AGENTS:
        issues.append(f"model '{model}' contains 'haiku' — project policy forbids Haiku")
    # A prompt that names Haiku is a model choice too: only v-memory's own file may.
    body = txt[end + 5:]
    if (cls in (CLASS_AGENT, CLASS_SKILL) and agent_name not in HAIKU_ELIGIBLE_AGENTS
            and "haiku" in body.lower()):
        issues.append("body names 'haiku' — only the v-memory agent may use Haiku")

    # Project policy (A5, revised by the maintainer 2026-09-02): agents carry
    # `model: opus`, EXCEPT the named scanning agents, which may carry `model: sonnet`.
    #
    # The revision follows the same split the execution ladder uses: Sonnet EXECUTES
    # (including reading code — scanning a repository is execution however large it is),
    # Opus JUDGES. The allow-list is explicit and short on purpose: the original rule was
    # absolute precisely so it could not drift, and "any agent may pick its own model"
    # would be that drift. Adding a name here is a deliberate act with a reason attached.
    #
    # Fable is NOT an option here. It belongs to a business-critical INVOCATION, not to
    # an agent definition, and the caller sets it with the Agent tool's `model` override
    # (which takes precedence over frontmatter). A static `model: fable` would spend the
    # top model on every routine pre-flight.
    if cls == CLASS_AGENT:
        name = agent_name
        if name in HAIKU_ELIGIBLE_AGENTS:
            allowed = ("haiku", "sonnet", "opus")
        elif name in SONNET_ELIGIBLE_AGENTS:
            allowed = ("opus", "sonnet")
        else:
            allowed = ("opus",)
        if model not in allowed:
            found = f"'{model}'" if model else "no model field"
            issues.append(
                f"agent '{name}' must carry model: {' or '.join(allowed)} "
                f"(found {found}) — project model policy"
            )

        # The Haiku agent reads and nothing else: its tools must be a non-empty subset
        # of Read, Grep, Glob. No `tools` field means every tool, which is refused.
        if name in HAIKU_ELIGIBLE_AGENTS and model == "haiku":
            raw = data.get("tools")
            tools = ([t.strip() for t in raw.split(",")] if isinstance(raw, str)
                     else [str(t).strip() for t in raw] if isinstance(raw, list) else [])
            tools = [t for t in tools if t]
            extra = sorted(set(tools) - HAIKU_TOOLS)
            if not tools or extra:
                issues.append(
                    f"agent '{name}' runs on Haiku, so its tools must be limited to "
                    f"Read, Grep, Glob (found {', '.join(extra) if extra else 'no tools field'})"
                )

        if memoryless(name) and "memory" in data:
            issues.append(
                f"agent '{name}' must NOT carry a 'memory' field (found "
                f"{data.get('memory')!r}) — v4 keeps project knowledge in "
                "docs/compound-v/, read on demand by v-memory"
            )

    # `maxTurns` (3.4.0) — the turn cap an agent definition carries natively. It is
    # optional, and a typo is silent: a string, a float or a negative is ignored by
    # the runtime, so the agent runs uncapped while its file says otherwise.
    if "maxTurns" in data:
        turns = data.get("maxTurns")
        if not isinstance(turns, int) or isinstance(turns, bool) or turns < 1:
            issues.append(
                f"maxTurns must be a positive integer (got {turns!r}) — a "
                "malformed cap is ignored, and the agent runs uncapped"
            )

    # `memory` (3.5.0) — the native persistent-memory scope. Optional; a value outside
    # the three documented scopes is silently ignored by the runtime.
    if "memory" in data:
        mem = data.get("memory")
        mem_s = mem.strip() if isinstance(mem, str) else mem
        if mem_s not in MEMORY_SCOPES:
            issues.append(
                "memory must be one of %s (got %r) — an unrecognised scope is "
                "ignored by the runtime, and the agent launches with no memory "
                "while its file claims one" % ("|".join(MEMORY_SCOPES), mem)
            )

    # Common gotcha: unquoted glob in paths field
    paths_val = data.get("paths")
    if isinstance(paths_val, str) and any(c in paths_val for c in "{}[]"):
        issues.append(
            f"'paths' field contains glob chars — quote it: paths: \"{paths_val}\""
        )

    return issues


def _selftest() -> int:
    import shutil
    import tempfile

    fails = []

    def check(name, cond):
        print(("  ok   " if cond else "  FAIL ") + name)
        if not cond:
            fails.append(name)

    root = pathlib.Path(tempfile.mkdtemp())

    def issues_for(relpath, text):
        p = root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return lint_file(p, rel=p.relative_to(root))

    AGENT_OK = "---\nname: x\ndescription: d\nmodel: opus\n---\nbody\n"
    try:
        # presence gate (A4): the three gated classes flag a missing block…
        check("agent without frontmatter flagged",
              any("missing frontmatter" in i for i in issues_for("agents/a.md", "# doc\n")))
        check("command without frontmatter flagged",
              any("missing frontmatter" in i for i in issues_for("commands/c.md", "# doc\n")))
        check("SKILL.md without frontmatter flagged",
              any("missing frontmatter" in i
                  for i in issues_for("skills/foo/SKILL.md", "# doc\n")))
        # …and everything else stays exempt
        check("plain doc exempt", issues_for("docs/notes.md", "# doc\n") == [])
        check("skill reference file exempt",
              issues_for("skills/foo/reference.md", "# doc\n") == [])
        check("nested agents/ dir NOT gated (anchored at root)",
              issues_for("docs/agents/readme.md", "# doc\n") == [])

        # maxTurns: optional, but a malformed cap is silently ignored by the
        # runtime, so the linter is the only thing that can notice it.
        check("agent with a valid maxTurns clean",
              issues_for("agents/cap.md",
                         "---\nname: x\ndescription: d\nmodel: opus\n"
                         "maxTurns: 60\n---\nbody\n") == [])
        for bad in ("'60'", "0", "-1", "1.5", "true"):
            check(f"agent with maxTurns: {bad} flagged",
                  any("maxTurns must be a positive integer" in i
                      for i in issues_for("agents/badcap.md",
                                          "---\nname: x\ndescription: d\n"
                                          f"model: opus\nmaxTurns: {bad}\n"
                                          "---\nbody\n")))

        # happy paths
        check("valid agent clean", issues_for("agents/good.md", AGENT_OK) == [])
        check("valid command clean (name exempt)",
              issues_for("commands/good.md", "---\ndescription: d\n---\nbody\n") == [])
        check("valid skill clean",
              issues_for("skills/foo/SKILL.md",
                         "---\nname: s\ndescription: d\n---\nbody\n") == [])

        # A6: closing --- at EOF without trailing newline is a valid close
        check("EOF-terminated frontmatter accepted",
              issues_for("commands/eof.md", "---\ndescription: d\n---") == [])
        check("truly unclosed frontmatter still flagged",
              any("no closing" in i for i in issues_for("commands/open.md",
                                                        "---\ndescription: d\n")))

        # A6: commands/ detection by path.parts, not substring — a dir merely
        # CONTAINING "commands" gets no name exemption
        check("substring 'commands' dir is not a command (name required)",
              any("missing required 'name'" in i
                  for i in issues_for("subcommands/x.md", "---\ndescription: d\n---\nb\n")))

        # Recursive path-class semantics are DELIBERATE (Codex v2.8 r1 #7):
        # nested commands and any SKILL.md at depth are gated
        check("nested commands/sub/x.md requires frontmatter",
              any("must start with a '---'" in i
                  for i in issues_for("commands/sub/x.md", "no frontmatter here\n")))
        check("nested skills/foo/refs/SKILL.md requires frontmatter",
              any("must start with a '---'" in i
                  for i in issues_for("skills/foo/refs/SKILL.md", "plain body\n")))

        # A5: agents must carry model: opus
        check("a non-listed agent with model sonnet is flagged",
              any("model policy" in i for i in issues_for(
                  "agents/sonnet.md", "---\nname: x\ndescription: d\nmodel: sonnet\n---\nb\n")))
        check("a listed scanning agent may carry model sonnet",
              not any("model policy" in i for i in issues_for(
                  "agents/code-archaeologist.md",
                  "---\nname: code-archaeologist\ndescription: d\nmodel: sonnet\n---\nb\n")))
        check("a listed scanning agent may still carry model opus",
              not any("model policy" in i for i in issues_for(
                  "agents/doc-validator.md",
                  "---\nname: doc-validator\ndescription: d\nmodel: opus\n---\nb\n")))
        check("no agent may carry model fable in frontmatter",
              any("model policy" in i for i in issues_for(
                  "agents/code-archaeologist.md",
                  "---\nname: code-archaeologist\ndescription: d\nmodel: fable\n---\nb\n")))
        check("the allow-list never admits haiku",
              any("haiku" in i for i in issues_for(
                  "agents/code-archaeologist.md",
                  "---\nname: code-archaeologist\ndescription: d\nmodel: haiku\n---\nb\n")))
        check("agent with no model field flagged",
              any("model policy" in i for i in issues_for(
                  "agents/nomodel.md", "---\nname: x\ndescription: d\n---\nb\n")))

        # Harness data under `.claude/` — rules and subagent memory. Neither carries a
        # name or a description, and neither is loaded as a plugin file.
        check("a .claude/rules file with only paths: is clean",
              issues_for(".claude/rules/testing.md",
                         '---\npaths:\n  - "tests/**/*.sh"\n---\nrule body\n') == [])
        check("a .claude/rules file with NO frontmatter is clean",
              issues_for(".claude/rules/plain.md", "rule body\n") == [])
        check("a subagent memory file stamped with modified: is clean",
              issues_for(".claude/agent-memory/spec-reviewer/topic.md",
                         "---\nmodified: '2026-09-04T00:00:00Z'\n---\nnote\n") == [])
        check("harness data is still rejected for haiku",
              any("haiku" in i for i in issues_for(
                  ".claude/rules/bad.md", "---\nmodel: haiku\n---\nb\n")))
        check("harness data still flags an unquoted glob in paths",
              any("glob chars" in i for i in issues_for(
                  ".claude/rules/glob.md", "---\npaths: tests/{a,b}/**\n---\nb\n")))
        # Codex 3.5.0 round-1 #7. `.claude/` is TWO things at once: harness data
        # (rules, agent memory) and a second home for real agents/commands/skills.
        # The blanket exemption let a project-scoped agent skip the model policy and
        # the memoryless-role rule entirely, so each half is pinned separately.
        check(".claude/agents/implementer.md with memory is REFUSED",
              any("must NOT carry a 'memory' field" in i for i in issues_for(
                  ".claude/agents/implementer.md",
                  "---\nname: implementer\ndescription: d\nmodel: opus\n"
                  "memory: project\n---\nb\n")))
        check(".claude/agents/*.md is held to the model policy (sonnet refused)",
              any("model policy" in i for i in issues_for(
                  ".claude/agents/implementer.md",
                  "---\nname: implementer\ndescription: d\nmodel: sonnet\n---\nb\n")))
        check(".claude/agents/*.md still needs name and description",
              len([i for i in issues_for(".claude/agents/bare.md",
                                         "---\nmodel: opus\n---\nb\n")
                   if "missing required" in i]) == 2)
        check(".claude/agents/*.md without frontmatter is flagged",
              any("missing frontmatter" in i
                  for i in issues_for(".claude/agents/nofm.md", "# doc\n")))
        check(".claude/skills/foo/SKILL.md without frontmatter is flagged",
              any("missing frontmatter" in i
                  for i in issues_for(".claude/skills/foo/SKILL.md", "# doc\n")))
        check(".claude/commands/x.md keeps the command name exemption",
              issues_for(".claude/commands/x.md", "---\ndescription: d\n---\nb\n") == [])
        check(".claude/agent-memory-local is harness data too",
              issues_for(".claude/agent-memory-local/spec-reviewer/MEMORY.md",
                         "---\nmodified: '2026-09-04T00:00:00Z'\n---\nnote\n") == [])
        check("a .claude subtree that is NOT named harness data gets no exemption",
              any("missing required 'name'" in i for i in issues_for(
                  ".claude/notes/x.md", "---\ndescription: d\n---\nb\n")))

        check("a REAL agent still needs name and description",
              len([i for i in issues_for("agents/bare.md",
                                         "---\nmodel: opus\n---\nb\n")
                   if "missing required" in i]) == 2)

        # `memory` (3.5.0) — the native persistent-memory scope.
        check("agent with memory: project is flagged (no agent carries memory)",
              any("must NOT carry a 'memory' field" in i for i in issues_for(
                  "agents/mem.md",
                  "---\nname: spec-reviewer\ndescription: d\nmodel: opus\n"
                  "memory: project\n---\nbody\n")))
        for good in ("user", "project", "local"):
            check(f"memory: {good} accepted",
                  not any("memory must be one of" in i
                          for i in issues_for("agents/mem.md",
                                              "---\nname: spec-reviewer\ndescription: d\n"
                                              f"model: opus\nmemory: {good}\n---\nb\n")))
        for bad in ("repo", "'true'", "shared", "Project", "1"):
            check(f"memory: {bad} flagged",
                  any("memory must be one of" in i
                      for i in issues_for("agents/badmem.md",
                                          "---\nname: spec-reviewer\ndescription: d\n"
                                          f"model: opus\nmemory: {bad}\n---\nb\n")))
        # An agent that writes inside a declared lane must carry NO memory at all:
        # its memory directory is outside that lane, so the note it takes is the
        # out-of-lane write that BLOCKS its own job.
        for lane_writer in ("implementer", "parallel-dispatcher"):
            check(f"{lane_writer} with memory: project flagged",
                  any("must NOT carry a 'memory' field" in i
                      for i in issues_for("agents/lw.md",
                                          f"---\nname: {lane_writer}\ndescription: d\n"
                                          "model: opus\nmemory: project\n---\nb\n")))
            check(f"{lane_writer} without memory clean",
                  issues_for("agents/lw.md",
                             f"---\nname: {lane_writer}\ndescription: d\n"
                             "model: opus\n---\nb\n") == [])
        check("a memoryless agent with an INVALID memory is flagged twice",
              len([i for i in issues_for("agents/lw.md",
                                         "---\nname: implementer\ndescription: d\n"
                                         "model: opus\nmemory: nope\n---\nb\n")
                   if "memory" in i]) == 2)
        check("memory stays OPTIONAL on every other agent",
              issues_for("agents/plain.md",
                         "---\nname: whatever\ndescription: d\nmodel: opus\n---\nb\n") == [])

        # v4 (plan Task 9): Haiku only for v-memory, and only with read tools.
        VM = "---\nname: v-memory\ndescription: d\nmodel: haiku\n%s---\nb\n"
        check("v-memory on haiku with Read, Grep, Glob is clean",
              issues_for("agents/v-memory.md", VM % "tools: Read, Grep, Glob\n") == [])
        check("v-memory on haiku with a YAML tools list is clean",
              issues_for("agents/v-memory.md",
                         VM % "tools:\n  - Read\n  - Grep\n") == [])
        check("v-memory on haiku with Bash is flagged",
              any("limited to" in i for i in issues_for(
                  "agents/v-memory.md", VM % "tools: Read, Grep, Bash\n")))
        check("v-memory on haiku with no tools field is flagged",
              any("limited to" in i for i in issues_for("agents/v-memory.md", VM % "")))
        check("v-memory body may name haiku",
              issues_for("agents/v-memory.md",
                         "---\nname: v-memory\ndescription: d\nmodel: haiku\n"
                         "tools: Read, Grep, Glob\n---\nRuns on Haiku.\n") == [])
        check("any other agent on haiku is flagged",
              any("haiku" in i for i in issues_for(
                  "agents/reviewer.md",
                  "---\nname: reviewer\ndescription: d\nmodel: haiku\n"
                  "tools: Read\n---\nb\n")))
        check("a skill whose body names haiku is flagged",
              any("body names 'haiku'" in i for i in issues_for(
                  "skills/foo/SKILL.md",
                  "---\nname: s\ndescription: d\n---\nUse a Haiku subagent.\n")))
        check("an agent whose body names haiku is flagged",
              any("body names 'haiku'" in i for i in issues_for(
                  "agents/x.md", AGENT_OK.replace("body", "dispatch with model haiku"))))
        check("domain-expert may carry model sonnet",
              not any("model policy" in i for i in issues_for(
                  "agents/domain-expert.md",
                  "---\nname: domain-expert\ndescription: d\nmodel: sonnet\n---\nb\n")))
        check("reviewer must be opus (sonnet flagged)",
              any("model policy" in i for i in issues_for(
                  "agents/reviewer.md",
                  "---\nname: reviewer\ndescription: d\nmodel: sonnet\n---\nb\n")))
        check("a v4 agent with memory is flagged",
              any("must NOT carry a 'memory' field" in i for i in issues_for(
                  "agents/domain-expert.md",
                  "---\nname: domain-expert\ndescription: d\nmodel: sonnet\n"
                  "memory: project\n---\nb\n")))

        # unchanged policies still hold
        check("haiku still rejected anywhere",
              any("haiku" in i for i in issues_for(
                  "skills/foo/SKILL.md",
                  "---\nname: s\ndescription: d\nmodel: haiku\n---\nb\n")))
        check("description soft max still enforced",
              any("soft max" in i for i in issues_for(
                  "commands/long.md", "---\ndescription: %s\n---\nb\n" % ("x" * 501))))
        check("unquoted glob in paths still flagged",
              any("glob chars" in i for i in issues_for(
                  "skills/foo/SKILL.md",
                  '---\nname: s\ndescription: d\npaths: src/{a,b}/**\n---\nb\n')))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n%d failed" % len(fails))
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all self-tests passed")
    return 0


def main(argv: list) -> int:
    if "--selftest" in argv[1:]:
        return _selftest()
    root = pathlib.Path(argv[1]) if len(argv) > 1 else pathlib.Path(".")
    total = 0
    for f in sorted(root.rglob("*.md")):
        parts = f.parts
        # `worktrees` covers the harness's agent checkouts under .claude/worktrees/.
        # They are copies of THIS repo, so linting them double-reports every file
        # and, during a parallel build, reports dozens of "issues" in files that are
        # not in this checkout at all (observed at 51 and twice at 68). .gitignore
        # cannot help here: this walk is rglob, not git.
        if "node_modules" in parts or ".git" in parts or "worktrees" in parts:
            continue
        # `evals/**/graders/*.md` are `claude plugin eval` grader files (3.7.0). Their
        # frontmatter is the eval harness's contract (`type: regex` and so on), not an
        # agent's or a skill's, so the model policy this linter enforces does not
        # apply to them and their required keys are different ones.
        if "evals" in parts and "graders" in parts:
            continue
        issues = lint_file(f, rel=f.relative_to(root))
        for i in issues:
            print(f"❌ {f}: {i}")
            total += 1

    if total == 0:
        print("✅ All frontmatter clean")
        return 0
    print(f"\n❌ {total} issue(s) found")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""The validator selftest driver (--selftest)."""

import json
import os
import sys

from . import _SCRIPTS_DIR
from .yamlload import _mini_yaml
from .globs import globs_overlap
from .rules import TIMEOUT_SEC_MIN, TIMEOUT_SEC_MAX, _is_reviewer
from .blocks import _validate_provision, _validate_toolchain_artifacts
from .core import validate, validate_text
from .advisories import unnamespaced_agent_memory_name, advisories_text
from .selftest_fixtures import (
    GOOD_MANIFEST, FOLDED_FEATURE, FOLDED_CRITERION, FOLDED_MANIFEST, BAD_MANIFEST,
    PARALLEL_DIRECT_MANIFEST, BAD_ID_MANIFEST, HAIKU_MODEL_MANIFEST,
    DANGLING_DEP_MANIFEST, CYCLE_DEP_MANIFEST, WRONG_TYPE_MANIFEST,
    XHIGH_CODEX_MANIFEST, XHIGH_CLAUDE_MANIFEST, _timeout_manifest, _v3_manifest,
    ANTIGRAVITY_DIRECT_MANIFEST, OPENCODE_DIRECT_MANIFEST, OPENCODE_WORKTREE_MANIFEST,
    OPENCODE_REVIEWER_MANIFEST, OPENCODE_BARE_MODEL_MANIFEST,
    OPENCODE_MALFORMED_MODEL_MANIFEST, OPENCODE_INT_MODEL_MANIFEST,
    OPENCODE_LIST_MODEL_MANIFEST, OPENCODE_DICT_MODEL_MANIFEST)
from .selftest_fastpath import _selftest_fastpath
from .selftest_blocks import _selftest_blocks


def _selftest():
    failures = []

    def expect(name, cond):
        if cond:
            print("  ok   - %s" % name)
        else:
            print("  FAIL - %s" % name)
            failures.append(name)

    # Glob overlap units.
    expect("overlap: identical globs", globs_overlap("a/**", "a/**"))
    expect(
        "overlap: src/features/** vs src/features/api/**",
        globs_overlap("src/features/**", "src/features/api/**"),
    )
    expect(
        "disjoint: src/a/** vs src/b/**",
        not globs_overlap("src/a/**", "src/b/**"),
    )
    expect(
        "disjoint: src/types/x.ts vs src/db/y.ts",
        not globs_overlap("src/types/x.ts", "src/db/y.ts"),
    )
    expect(
        "overlap: dir/* vs dir/file.ts",
        globs_overlap("dir/*", "dir/file.ts"),
    )

    # GOOD manifest -> zero violations.
    good = validate_text(GOOD_MANIFEST)
    expect("good manifest: zero violations (%r)" % good, good == [])

    # BAD manifest -> catches each planted defect.
    bad = validate_text(BAD_MANIFEST)
    joined = " || ".join(bad)
    expect("bad manifest: has violations", len(bad) > 0)
    expect(
        "bad: codex-without-worktree caught",
        "backend codex" in joined and "isolation" in joined,
    )
    expect(
        "bad: reviewer-not-opus caught",
        "reviewer job" in joined and "opus" in joined,
    )
    expect("bad: write overlap caught", "overlap" in joined)
    expect(
        "bad: shared_foundation non-serial caught",
        "must run serial" in joined,
    )
    expect(
        "bad: orphan shared resource caught",
        "orphan.ts" in joined or "not written by any" in joined,
    )
    expect(
        "bad: missing model-or-tier caught",
        "must have 'model' or 'tier'" in joined,
    )
    expect(
        "bad: invalid tier caught",
        "tier 'turbo' invalid" in joined,
    )
    expect(
        "bad: invalid effort caught",
        "effort 'extreme' invalid" in joined,
    )

    # effort xhigh: valid iff backend codex — selftested BOTH ways.
    xh_ok = validate_text(XHIGH_CODEX_MANIFEST)
    expect("codex+xhigh manifest valid (%r)" % xh_ok, xh_ok == [])
    xh_bad = validate_text(XHIGH_CLAUDE_MANIFEST)
    expect(
        "claude+xhigh caught (xhigh is codex-only)",
        any("xhigh is codex-only (kernel: model_reasoning_effort); use high" in p
            for p in xh_bad),
    )
    expect(
        "bad: parallel+direct caught",
        "run: parallel with isolation: direct" in joined,
    )

    # timeout_sec: optional, integer seconds, bounded [60, 21600]. ABSENT is valid
    # and leaves the worker script's DEFAULT_TIMEOUT_SEC=900 in force.
    ts_absent = validate_text(_timeout_manifest(""))
    expect("timeout_sec absent: manifest valid (%r)" % ts_absent, ts_absent == [])
    ts_ok = validate_text(_timeout_manifest("1800"))
    expect("timeout_sec 1800: manifest valid (%r)" % ts_ok, ts_ok == [])
    for _edge in (TIMEOUT_SEC_MIN, TIMEOUT_SEC_MAX):
        _e = validate_text(_timeout_manifest(str(_edge)))
        expect("timeout_sec %d (inclusive bound) valid (%r)" % (_edge, _e), _e == [])
    ts_small = validate_text(_timeout_manifest(str(TIMEOUT_SEC_MIN - 1)))
    expect(
        "timeout_sec too small caught",
        any("timeout_sec 59 out of range" in p and "60" in p and "21600" in p
            for p in ts_small),
    )
    ts_large = validate_text(_timeout_manifest(str(TIMEOUT_SEC_MAX + 1)))
    expect(
        "timeout_sec too large caught",
        any("timeout_sec 21601 out of range" in p and "60" in p and "21600" in p
            for p in ts_large),
    )
    ts_bool = validate_text(_timeout_manifest("true"))
    expect(
        "timeout_sec bool caught (bool is an int subclass)",
        any("timeout_sec must be an integer number of seconds" in p
            for p in ts_bool),
    )
    ts_str = validate_text(_timeout_manifest('"900"'))
    expect(
        "timeout_sec string caught",
        any("timeout_sec must be an integer number of seconds" in p
            for p in ts_str),
    )
    expect(
        "no unknown-key rejection introduced (good manifest still clean)",
        not any("unknown" in p.lower() for p in good),
    )

    # never-Haiku policy: a model: haiku execution-layer override is INVALID.
    haiku = validate_text(HAIKU_MODEL_MANIFEST)
    expect(
        "model:haiku override caught (never-Haiku policy)",
        any("never-Haiku policy" in p for p in haiku),
    )

    # depends_on: dangling ref INVALID, cycle INVALID, valid DAG OK.
    dangling = validate_text(DANGLING_DEP_MANIFEST)
    expect(
        "dangling depends_on ref caught",
        any("references unknown job id 'task-0-missing'" in p for p in dangling),
    )
    cyc = validate_text(CYCLE_DEP_MANIFEST)
    expect(
        "depends_on cycle caught",
        any("cycle detected" in p for p in cyc),
    )
    expect(
        "valid DAG (good manifest) has no depends_on violation",
        not any("depends_on" in p or "cycle detected" in p for p in good),
    )

    # Structural type check: wrong-typed required field is a specific violation.
    wt_bad = validate_text(WRONG_TYPE_MANIFEST)
    expect(
        "wrong-typed acceptance_criteria caught",
        any("'acceptance_criteria' must be a list" in p for p in wt_bad),
    )

    # parallel ⇒ worktree, and a bad job id, each caught.
    pd_bad = validate_text(PARALLEL_DIRECT_MANIFEST)
    expect(
        "parallel+direct manifest invalid",
        any("run: parallel with isolation: direct" in p for p in pd_bad),
    )
    badid = validate_text(BAD_ID_MANIFEST)
    expect(
        "bad job id '../x' caught",
        any("invalid characters" in p for p in badid),
    )

    # antigravity ⇒ worktree: an external no-kernel-sandbox worker with
    # isolation: direct is INVALID (mirrors the codex⇒worktree invariant).
    agy_bad = validate_text(ANTIGRAVITY_DIRECT_MANIFEST)
    expect(
        "antigravity+direct caught (antigravity requires worktree)",
        any("backend antigravity but isolation" in p
            and "antigravity requires worktree" in p for p in agy_bad),
    )

    # opencode ⇒ worktree: same invariant, new backend (v1: worker-only, lower-trust).
    opencode_bad = validate_text(OPENCODE_DIRECT_MANIFEST)
    expect(
        "opencode+direct caught (opencode requires worktree)",
        any("backend opencode but isolation" in p
            and "opencode requires worktree" in p for p in opencode_bad),
    )
    opencode_ok = validate_text(OPENCODE_WORKTREE_MANIFEST)
    expect("opencode+worktree manifest is valid (provider/model string accepted)",
           opencode_ok == [])

    # WORKER-ONLY: a reviewer job MUST NEVER resolve to backend opencode,
    # even when tier: deep + isolation: worktree are otherwise satisfied.
    opencode_reviewer_bad = validate_text(OPENCODE_REVIEWER_MANIFEST)
    expect(
        "opencode reviewer job REJECTED (WORKER-ONLY)",
        any("reviewer job 'task-1-quality-review'" in p
            and "backend 'opencode'" in p
            and "WORKER-ONLY" in p for p in opencode_reviewer_bad),
    )

    # opencode provider/model shape: a bare (slash-less) or malformed (empty-side)
    # explicit model override is REJECTED before dispatch.
    opencode_bare_bad = validate_text(OPENCODE_BARE_MODEL_MANIFEST)
    expect(
        "bare opencode model 'gpt-6' REJECTED (not provider/model)",
        any("not a valid 'provider/model' string" in p for p in opencode_bare_bad),
    )
    opencode_malformed_bad = validate_text(OPENCODE_MALFORMED_MODEL_MANIFEST)
    expect(
        "malformed opencode model 'anthropic/' REJECTED (empty right side)",
        any("not a valid 'provider/model' string" in p
            for p in opencode_malformed_bad),
    )
    # NON-STRING opencode model (int / list / dict) must ALSO be rejected — it can
    # never be a provider/model string and must not skip the shape check.
    opencode_int_bad = validate_text(OPENCODE_INT_MODEL_MANIFEST)
    expect(
        "non-string opencode model (int 42) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_int_bad),
    )
    opencode_list_bad = validate_text(OPENCODE_LIST_MODEL_MANIFEST)
    expect(
        "non-string opencode model (list) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_list_bad),
    )
    opencode_dict_bad = validate_text(OPENCODE_DICT_MODEL_MANIFEST)
    expect(
        "non-string opencode model (dict) REJECTED",
        any("not a valid 'provider/model' string" in p
            for p in opencode_dict_bad),
    )

    # Reviewer satisfied by tier: deep (no model) — GOOD manifest task-3 uses
    # tier: deep and must not trip the reviewer invariant.
    expect(
        "reviewer via tier:deep accepted (no model)",
        not any("reviewer job 'task-3-spec-review'" in p for p in good),
    )
    # Finding 119: a reviewer lifted to the frontier tier (Fable) is STRONGER than
    # deep and must pass; a light-tier reviewer must still fail. The GOOD manifest
    # re-parsed, mutated, re-dumped — validate_text is the same entry the case
    # above used, so the two verdicts differ only in the reviewer's tier.
    import yaml as _yaml_f119
    _fr = _yaml_f119.safe_load(GOOD_MANIFEST)
    for _j in _fr.get("jobs", []):
        if _j.get("id") == "task-3-spec-review":
            _j["tier"] = "frontier"; _j.pop("model", None)
    _fr_probs = validate_text(_yaml_f119.safe_dump(_fr, sort_keys=False))
    expect("reviewer via tier:frontier accepted — stronger passes (finding 119)",
           not any("reviewer job 'task-3-spec-review'" in p for p in _fr_probs))
    for _j in _fr.get("jobs", []):
        if _j.get("id") == "task-3-spec-review":
            _j["tier"] = "light"
    _fr_probs2 = validate_text(_yaml_f119.safe_dump(_fr, sort_keys=False))
    expect("reviewer via tier:light still refused (finding 119 never weakens)",
           any("reviewer job 'task-3-spec-review'" in p for p in _fr_probs2))

    # Empty / malformed.
    expect("no jobs -> violation", validate_text("run_id: x") != [])
    expect("not a mapping -> violation", validate({}) != [])
    try:
        import yaml as _yaml_probe  # noqa: F401
        _have_pyyaml = True
    except ImportError:
        _have_pyyaml = False
    if _have_pyyaml:
        # finding 53: an inner ": " in an unquoted scalar is refused by PyYAML;
        # the validator must report it, never consult the subset parser instead.
        _fifty_three = validate_text("run_id: x\njobs:\n- id: a\n  title: Task A: the scorer\n"
                                     "  write_allowed: [a.py]\n")
        expect("PyYAML-rejected manifest is a VIOLATION, not a subset-parser pass (%r)"
               % _fifty_three, len(_fifty_three) == 1 and "PyYAML rejected" in _fifty_three[0])

    # Fallback parser parity: force the embedded parser on the good manifest.
    parsed = _mini_yaml(GOOD_MANIFEST)
    fb = validate(parsed)
    expect("fallback parser: good manifest clean (%r)" % fb, fb == [])
    fb_bad = validate(_mini_yaml(BAD_MANIFEST))
    expect("fallback parser: bad manifest flagged", len(fb_bad) > 0)

    # ------------------------------------------------------------------ #
    # FIFTH REVIEW PASS (2026-09-02) — the fallback parser could not read
    # what safe_dump writes.
    #
    # Every manifest in this repo is `yaml.safe_dump` output, and safe_dump
    # produces two shapes the shipped subset parser had no rule for: a scalar
    # FOLDED across lines at `width`, and a block SEQUENCE at its parent key's
    # own indentation. Each one made `parse_map` break early, so everything
    # after it — `jobs:` included — was silently dropped. `hooks/lane-guard.sh`
    # loads a manifest through this very function on an interpreter without
    # PyYAML; it read "no jobs", resolved no lane, and allowed every out-of-lane
    # write. FOLDED_MANIFEST below is literal safe_dump(width=100) output.
    folded = _mini_yaml(FOLDED_MANIFEST)
    expect("fallback parser: a folded plain scalar is joined, not truncated",
           folded.get("feature") == FOLDED_FEATURE)
    expect("fallback parser: a folded list item is joined too",
           folded.get("acceptance_criteria") == [FOLDED_CRITERION])
    expect("fallback parser: the document SURVIVES the fold (jobs present)",
           [j.get("id") for j in (folded.get("jobs") or [])] == ["guard-honest"])
    expect("fallback parser: the folded job's write_allowed lane is exact — "
           "this is the value the lane guard enforces on",
           folded["jobs"][0].get("write_allowed")
           == ["hooks/lane-guard.sh", "tests/test-lane-guard.sh"])

    # A TRUNCATED PARSE IS NOT A MANIFEST WITH NO JOBS. Multi-line flow
    # sequences are outside this parser's subset, so it recovers no jobs from
    # this document — and it must SAY SO rather than hand back a jobless
    # mapping that every caller reads as "nothing to enforce".
    _flow_jobs = "run_id: x\njobs: [\n  {id: a}\n]\n"
    try:
        _mini_yaml(_flow_jobs)
        _truncation_raised = ""
    except ValueError as _exc:
        _truncation_raised = str(_exc)
    expect("fallback parser: a top-level `jobs:` that yields no jobs RAISES",
           "TRUNCATED, not empty" in _truncation_raised)
    expect("...and the error says what to do about it (PyYAML)",
           "PyYAML" in _truncation_raised)
    expect("an explicitly empty `jobs: []` is parsed faithfully, not rejected",
           _mini_yaml("run_id: x\njobs: []\n") == {"run_id": "x", "jobs": []})
    expect("a document with no top-level `jobs:` at all is untouched by the check",
           _mini_yaml("run_id: x\n") == {"run_id": "x"})

    # The fixture is only evidence if it really is what safe_dump writes. When
    # PyYAML is importable, re-dump it and compare byte for byte; the CI floor
    # job installs PyYAML, so this runs there.
    try:
        import yaml as _y
    except ImportError:  # pragma: no cover - exercised on a PyYAML-less box
        expect("safe_dump cross-check SKIPPED — no PyYAML on this interpreter",
               True)
    else:
        _redump = _y.safe_dump(_y.safe_load(FOLDED_MANIFEST), width=100,
                               sort_keys=False, allow_unicode=True,
                               default_flow_style=False)
        expect("the folded fixture IS safe_dump(width=100) output, byte for byte",
               _redump == FOLDED_MANIFEST)
        expect("the fallback parser agrees with PyYAML on the folded manifest",
               _y.safe_load(FOLDED_MANIFEST) == folded)

    _selftest_blocks(expect)

    # The committed audit trail: every run manifest + the shipped example must still
    # validate WITHOUT the flag. This is the bootstrap exemption, and it is only honest
    # because /v:dispatch passes --require-triage on every live dispatch.
    import glob as _glob3
    _repo3 = os.path.dirname(_SCRIPTS_DIR)
    _hist = sorted(_glob3.glob(os.path.join(_repo3, "docs", "superpowers", "execution",
                                          "*", "manifest.yaml")))
    _hist.append(os.path.join(_repo3, "examples", "manifest.example.yaml"))
    for _hm in _hist:
        if not os.path.isfile(_hm):
            continue
        with open(_hm, "r", encoding="utf-8") as _fh:
            _hp = validate_text(_fh.read(), repo_root=_repo3)
        expect("committed manifest validates without --require-triage: %s (%r)"
               % (os.path.basename(os.path.dirname(_hm)), _hp), _hp == [])

    # --- ADVISORIES: the memory-only lane (v3.5.0, Codex round-1 #8) -----------
    # A job whose whole lane is agent memory is refused as `no_work` the moment the
    # agent has nothing durable to save, which pressures it to invent an entry. The
    # advisory says so; it must NEVER become a violation, because pairing the glob
    # with a real output lane is the author's call, not the validator's.
    def _lane(*globs):
        return _v3_manifest().replace(
            "write_allowed: [src/features/**]",
            "write_allowed: [%s]" % ", ".join(globs))

    # Namespaced form (`superpowers-v-<agent>`) is the recommended shape, so it is
    # the "clean" baseline used below for cases that assert NO advisory fires for
    # a reason unrelated to namespacing.
    _mem_only = _lane('".claude/agent-memory/superpowers-v-spec-reviewer/**"')
    _mem_msgs = advisories_text(_mem_only)
    expect("advisory: a memory-only lane warns", len(_mem_msgs) == 1)
    # Bound-checked on purpose: a regressed detector must FAIL this row, not raise
    # an IndexError that ends the whole selftest before the later rows ever run.
    expect("advisory: the warning names the job and the remedy",
           bool(_mem_msgs) and all(s in _mem_msgs[0] for s in
                                   ("task-1-v3", "memory-only lane", "no_work",
                                    "pair the memory glob", "write_allowed: []")))
    # THE contract: advisory ≠ violation. Same manifest, still valid.
    expect("advisory: a memory-only lane does NOT change the verdict",
           validate_text(_mem_only) == [])
    expect("advisory: memory glob + a real output lane does NOT warn",
           advisories_text(_lane('".claude/agent-memory/superpowers-v-spec-reviewer/**"',
                                 '"docs/superpowers/dogfood/r-1.md"')) == [])
    expect("advisory: an empty write_allowed does NOT warn",
           advisories_text(_lane()) == [])
    expect("advisory: an ordinary code lane does NOT warn",
           advisories_text(_lane('"src/**"')) == [])
    # `in any form`: a detector that knows one spelling detects nothing.
    for _form in ('"./.claude/agent-memory/superpowers-v-spec-reviewer/**"',
                  '".claude/agent-memory/superpowers-v-spec-reviewer"',
                  '".claude/agent-memory-local/spec-reviewer/**"',
                  '"/.claude/agent-memory/superpowers-v-spec-reviewer/MEMORY.md"'):
        expect("advisory: memory-only lane detected as %s" % _form,
               len(advisories_text(_lane(_form))) == 1)
    expect("advisory: a look-alike path outside the memory roots does NOT warn",
           advisories_text(_lane('".claude/agent-memoryX/spec-reviewer/**"')) == [])
    expect("advisory: an unparseable manifest yields no advisory, only violations",
           advisories_text("\tnot: [valid") == [])

    # --- ADVISORIES: MEMORY_LANE_UNNAMESPACED (v3.6) --------------------------
    # A bare (non-namespaced) project-scope memory lane collides with another
    # plugin's memory-bearing agent of the same name; the namespaced form does
    # not. Independent of whether the lane is paired with a real output lane.
    for _bare in ('"./.claude/agent-memory/spec-reviewer/**"',
                  '".claude/agent-memory/spec-reviewer"',
                  '"/.claude/agent-memory/spec-reviewer/MEMORY.md"'):
        _u_msgs = advisories_text(
            _lane(_bare, '"docs/superpowers/dogfood/r-1.md"'))
        expect("advisory: bare memory lane %s raises MEMORY_LANE_UNNAMESPACED"
               % _bare,
               any("not namespaced" in w and "superpowers-v-spec-reviewer" in w
                   for w in _u_msgs))
    expect("advisory: the namespaced lane does NOT raise MEMORY_LANE_UNNAMESPACED",
           not any("not namespaced" in w for w in advisories_text(
               _lane('".claude/agent-memory/superpowers-v-spec-reviewer/**"',
                     '"docs/superpowers/dogfood/r-1.md"'))))
    expect("advisory: the gitignored -local scope never raises "
           "MEMORY_LANE_UNNAMESPACED",
           not any("not namespaced" in w for w in advisories_text(
               _lane('".claude/agent-memory-local/spec-reviewer/**"',
                     '"docs/superpowers/dogfood/r-1.md"'))))
    expect("advisory: MEMORY_LANE_UNNAMESPACED does NOT change the verdict",
           validate_text(_lane('".claude/agent-memory/spec-reviewer/**"',
                               '"docs/superpowers/dogfood/r-1.md"')) == [])
    expect("unnamespaced_agent_memory_name: bare form -> agent name",
           unnamespaced_agent_memory_name(".claude/agent-memory/spec-reviewer/**")
           == "spec-reviewer")
    expect("unnamespaced_agent_memory_name: namespaced form -> None",
           unnamespaced_agent_memory_name(
               ".claude/agent-memory/superpowers-v-spec-reviewer/**") is None)

    # --- ADVISORIES: WAVE_EXCEEDS_RUNTIME_CONCURRENCY (v3.6.4) -----------------
    # The native Workflow runtime's default cap is 16 concurrent agents, and the
    # emitter's own peak-concurrency arithmetic (see the constant's docstring
    # above `wave_concurrency_advisories`) is 1 agent per job in flight at a
    # time — so a wave this wide queues rather than dispatching all at once.
    def _wave_manifest(n_jobs, max_parallel):
        jobs = "\n".join(
            "  - id: task-w%d\n"
            "    title: \"wave job %d\"\n"
            "    type: bounded_crud\n"
            "    backend: claude\n"
            "    tier: standard\n"
            "    effort: medium\n"
            "    isolation: worktree\n"
            "    run: parallel\n"
            "    write_allowed: [src/wave%d/**]\n"
            "    read_allowed: [src/**]\n"
            "    acceptance: [\"builds\"]"
            % (i, i, i)
            for i in range(n_jobs)
        )
        return """
run_id: 2026-09-21-wave
feature: "wave width"
spec_path: docs/superpowers/specs/2026-09-21-wave.md
plan_path: docs/superpowers/plans/2026-09-21-wave.md
audits:
  archaeology: docs/superpowers/archaeology/2026-09-21-wave.md
  domain: docs/superpowers/expert/2026-09-21-wave.md
  library: docs/superpowers/library-audit/2026-09-21-wave.md
routing_stance: balanced
max_parallel: %d
acceptance_criteria:
  - "ships"
jobs:
%s
""" % (max_parallel, jobs)

    _wide = _wave_manifest(17, 20)
    _wide_msgs = advisories_text(_wide)
    expect("advisory: a 17-job single wave raises WAVE_EXCEEDS_RUNTIME_CONCURRENCY",
           any("17 jobs exceeds" in w and "wave 1" in w for w in _wide_msgs))
    expect("advisory: the warning names the runtime default and the env var",
           bool(_wide_msgs) and any(
               "concurrency cap of 16" in w
               and "CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS" in w
               for w in _wide_msgs))
    expect("advisory: WAVE_EXCEEDS_RUNTIME_CONCURRENCY does NOT change the verdict",
           validate_text(_wide) == [])

    _narrow = _wave_manifest(4, 4)
    expect("advisory: a 4-job wave does NOT raise WAVE_EXCEEDS_RUNTIME_CONCURRENCY",
           not any("exceeds" in w and "concurrency cap" in w
                   for w in advisories_text(_narrow)))
    expect("wave-width test manifest (4-job) is itself a clean PASS",
           validate_text(_narrow) == [])

    # exactly-at-the-limit (16) must NOT warn; one over (17) must.
    expect("advisory: exactly 16 jobs in one wave does NOT warn",
           not any("concurrency cap" in w
                   for w in advisories_text(_wave_manifest(16, 20))))

    # --- v3.6: provision_command / provision_timeout_s -------------------------
    def _prov(extra):
        return _v3_manifest() + extra

    expect("provision: a valid command + timeout pair is PASS",
           validate_text(_prov("provision_command: \"npm ci\"\n"
                               "provision_timeout_s: 600\n")) == [])
    expect("provision: absent is valid (no key at all)",
           validate_text(_v3_manifest()) == [])
    expect("provision: provision_command 3 (not a string) is FAIL",
           any("provision_command" in p for p in
               validate_text(_prov("provision_command: 3\n"))))
    expect("provision: provision_command \"\" (empty) is FAIL",
           any("provision_command" in p for p in
               validate_text(_prov('provision_command: ""\n'))))
    expect("provision: provision_timeout_s 0 is FAIL",
           any("provision_timeout_s" in p for p in
               validate_text(_prov("provision_command: \"npm ci\"\n"
                                   "provision_timeout_s: 0\n"))))
    expect("provision: provision_timeout_s 1801 is FAIL",
           any("provision_timeout_s" in p for p in
               validate_text(_prov("provision_command: \"npm ci\"\n"
                                   "provision_timeout_s: 1801\n"))))
    expect("provision: provision_command with a newline is FAIL",
           any("provision_command" in p for p in
               _validate_provision({"provision_command": "npm ci\nrm -rf /"})))

    # --- issue #22: top-level toolchain_artifacts ------------------------------
    expect("toolchain_artifacts: absent is valid (no key at all)",
           validate_text(_v3_manifest()) == [])
    expect("toolchain_artifacts: a valid list of specific globs is PASS",
           validate_text(_prov(
               'toolchain_artifacts: ["tsconfig.tsbuildinfo", '
               '"node_modules/.vite/**"]\n')) == [])
    expect("toolchain_artifacts: a bare string (not a list) is FAIL",
           any("toolchain_artifacts" in p for p in
               validate_text(_prov('toolchain_artifacts: "x"\n'))))
    expect("toolchain_artifacts: [\"**\"] (catch-all) is FAIL",
           any("toolchain_artifacts" in p and "catch-all" in p for p in
               validate_text(_prov('toolchain_artifacts: ["**"]\n'))))
    expect("toolchain_artifacts: [\"\"] (empty entry) is FAIL",
           any("toolchain_artifacts" in p for p in
               validate_text(_prov('toolchain_artifacts: [""]\n'))))
    expect("toolchain_artifacts: null (bare key) is valid (same absent-vs-null "
           "rule as global_constraints)",
           validate_text(_prov("toolchain_artifacts:\n")) == [])
    # Every other catch-all spelling is refused too, not just bare "**".
    for _glob in ("*", "**/*", "/**", "./**"):
        expect("toolchain_artifacts: %r is a catch-all and FAILS" % _glob,
               any("catch-all" in p for p in _validate_toolchain_artifacts(
                   {"toolchain_artifacts": [_glob]})))
    # A catch-all mixed in with legitimate globs still fails the whole list —
    # one bad entry is enough, the good ones don't dilute it.
    expect("toolchain_artifacts: a catch-all mixed with valid globs still FAILS",
           any("catch-all" in p for p in _validate_toolchain_artifacts(
               {"toolchain_artifacts": ["tsconfig.tsbuildinfo", "**"]})))
    # A newline inside one entry is refused, same single-line discipline as
    # provision_command.
    expect("toolchain_artifacts: an entry with a newline is FAIL",
           any("toolchain_artifacts" in p and "single-line" in p
               for p in _validate_toolchain_artifacts(
                   {"toolchain_artifacts": ["tsconfig.tsbuildinfo\nrm -rf /"]})))
    # A non-string entry (bool/int) is caught by the shared shape check, not the
    # catch-all check crashing on a non-string.
    expect("toolchain_artifacts: a non-string entry (True) is FAIL, not a crash",
           any("toolchain_artifacts" in p for p in _validate_toolchain_artifacts(
               {"toolchain_artifacts": [True]})))

    # The SHIPPED example must not trip the advisory it documents.
    _ex = os.path.join(_repo3, "examples", "manifest.example.yaml")
    if os.path.isfile(_ex):
        with open(_ex, "r", encoding="utf-8") as _fh:
            _ex_warn = advisories_text(_fh.read())
        expect("advisory: examples/manifest.example.yaml raises none (%r)" % _ex_warn,
               _ex_warn == [])

    # v2.9 conditional fast-path suite (on-disk fixtures).
    _selftest_fastpath(expect)

    # --- C2: a `yaml.py` planted beside this script is NOT the parser ---------
    # (eighth review pass, 2026-09-03.) See `_harden_sys_path` at the top of this
    # file. This module reads the document that DEFINES every job's
    # `write_allowed`, and `hooks/lane-guard.sh` loads it by path from a process
    # whose CWD is the worker's own worktree — so both shadowing routes (the
    # script's directory and the CWD) are exercised here at once, with the plant
    # sitting in the directory that is both.
    import shutil as _shutil_c2
    import subprocess as _sp_c2
    import tempfile as _tempfile_c2

    _c2_tmp = _tempfile_c2.mkdtemp(prefix="cv-vm-shadow-")
    try:
        _c2_copy = os.path.join(_c2_tmp, "compound-v-validate-manifest.py")
        _shutil_c2.copy(os.path.join(_SCRIPTS_DIR, "compound-v-validate-manifest.py"),
                        _c2_copy)
        _shutil_c2.copytree(os.path.join(_SCRIPTS_DIR, "cv_validate"),
                            os.path.join(_c2_tmp, "cv_validate"))
        _c2_mark = os.path.join(_c2_tmp, "hostile-yaml-imported")
        with open(os.path.join(_c2_tmp, "yaml.py"), "w") as _fh_c2:
            _fh_c2.write(
                "open(%r, 'w').write('imported')\n"
                "def safe_load(text):\n"
                "    return {'jobs': [{'id': 'pwned', 'write_allowed': ['**']}]}\n"
                % _c2_mark)

        # The plant is POTENT: an unhardened process in that directory imports it.
        _sp_c2.run([sys.executable, "-B", "-c", "import yaml"], cwd=_c2_tmp,
                   stdout=_sp_c2.DEVNULL, stderr=_sp_c2.DEVNULL)
        expect("shadow: the planted yaml.py IS imported by an unhardened process "
               "(the plant is real)", os.path.exists(_c2_mark))
        if os.path.exists(_c2_mark):
            os.remove(_c2_mark)

        _c2_probe = (
            "import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('_cv_vm', sys.argv[1])\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "print(json.dumps(mod.load_yaml('jobs:\\n- id: real\\n')))\n"
        )
        _c2_proc = _sp_c2.run(
            [sys.executable, "-B", "-c", _c2_probe, _c2_copy], cwd=_c2_tmp,
            stdout=_sp_c2.PIPE, stderr=_sp_c2.PIPE, universal_newlines=True)
        try:
            _c2_parsed = json.loads(_c2_proc.stdout or "{}")
        except ValueError:
            _c2_parsed = {}
        _c2_jobs = (_c2_parsed or {}).get("jobs") or []
        expect("shadow: the parse is unaffected — the real document is read",
               len(_c2_jobs) == 1 and _c2_jobs[0].get("id") == "real")
        expect("shadow: the planted yaml.py was never imported",
               not os.path.exists(_c2_mark))
    finally:
        _shutil_c2.rmtree(_c2_tmp, ignore_errors=True)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    # --- 3.3.0: `type` decides who is a reviewer ---------------------------
    # Dogfood 10: a job TITLED "Writes the thing the reviewer reviews" was refused
    # for not being deep-tier. `integration` and `quality` are in the token list,
    # so ordinary titles were forcing jobs onto Opus by accident.
    expect("a declared review type is a reviewer",
           _is_reviewer({"type": "review", "id": "x", "title": "x"}) is True)
    expect("a docs job whose TITLE mentions a reviewer is NOT one",
           _is_reviewer({"type": "docs", "id": "impl-slice",
                         "title": "Writes the thing the reviewer reviews"}) is False)
    expect("'Add integration tests' is not a reviewer",
           _is_reviewer({"type": "tests_new", "id": "t1",
                         "title": "Add integration tests"}) is False)
    expect("'Refactor the quality metrics' is not a reviewer",
           _is_reviewer({"type": "mechanical_refactor", "id": "q1",
                         "title": "Refactor the quality metrics module"}) is False)
    expect("with NO type, the id/title fallback still catches a reviewer",
           _is_reviewer({"id": "spec-review", "title": "gate"}) is True)
    expect("the fallback matches WORD boundaries, so 'preview' is not 'review'",
           _is_reviewer({"id": "preview-builder",
                         "title": "build the preview"}) is False)
    expect("the fallback does not fire on 'disintegration'",
           _is_reviewer({"id": "d1", "title": "model disintegration study"}) is False)

    print("\nSELFTEST PASSED")
    return 0

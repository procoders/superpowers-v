"""Manifest fixtures shared by the validator selftests."""


# --------------------------------------------------------------------------- #
# Self-test.
# --------------------------------------------------------------------------- #
GOOD_MANIFEST = """
run_id: 2026-06-26-demo
feature: "demo"
spec_path: docs/superpowers/specs/2026-06-26-demo.md
plan_path: docs/superpowers/plans/2026-06-26-demo.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-demo.md
  domain: docs/superpowers/expert/2026-06-26-demo.md
  library: docs/superpowers/library-audit/2026-06-26-demo.md
routing_stance: balanced
max_parallel: 4
shared_resources:
  - src/types/shared.ts
acceptance_criteria:
  - "ships"
jobs:
  - id: task-0-foundation
    title: "shared foundation"
    type: shared_foundation
    backend: claude
    model: opus
    isolation: direct
    run: serial
    write_allowed: [src/types/shared.ts, src/db/schema.ts]
    read_allowed: [src/db/**]
    acceptance: ["types exported"]
  - id: task-1-editor
    title: "editor slice"
    type: large_isolated
    backend: codex
    model: gpt-5.5
    isolation: worktree
    run: parallel
    depends_on: [task-0-foundation]
    write_allowed: [src/features/editor/**]
    read_allowed: [src/features/editor/**]
    acceptance: ["create/edit"]
  - id: task-2-api
    title: "api slice"
    type: bounded_crud
    backend: claude
    tier: standard
    effort: medium
    isolation: worktree
    run: parallel
    write_allowed: [src/features/api/**]
    read_allowed: [src/server/**]
    acceptance: ["crud"]
  - id: task-3-spec-review
    title: "spec review gate"
    type: review
    backend: claude
    tier: deep
    effort: high
    isolation: direct
    run: serial
    write_allowed: []
    read_allowed: [src/**]
    acceptance: ["AC met"]
"""

# The shape `yaml.safe_dump(..., width=100)` actually emits, and the shape the
# subset parser could not read until the fifth review pass: a folded plain
# scalar (`feature`), a folded list item (`acceptance_criteria`), and block
# sequences sitting at their parent key's OWN indent (`jobs`, `write_allowed`).
# Kept as literal bytes so the fixture is evidence rather than a re-derivation;
# `_selftest` re-dumps it through PyYAML and asserts it is byte-identical.
FOLDED_FEATURE = ("Close the fifth review pass: a lane guard that actually "
                  "enforces, a register-lane the clamp accepts, and honest "
                  "acceptance greps")
FOLDED_CRITERION = (r"grep -rnE '^PIPELINE_BOOKKEEPING\s*=' scripts hooks "
                    "returns nothing, and the split literals are gone from "
                    "both files")
FOLDED_MANIFEST = r"""run_id: 2026-09-02-folded
feature: 'Close the fifth review pass: a lane guard that actually enforces, a register-lane the clamp
  accepts, and honest acceptance greps'
acceptance_criteria:
- grep -rnE '^PIPELINE_BOOKKEEPING\s*=' scripts hooks returns nothing, and the split literals are gone
  from both files
jobs:
- id: guard-honest
  type: core_slice
  backend: claude
  tier: deep
  write_allowed:
  - hooks/lane-guard.sh
  - tests/test-lane-guard.sh
  read_allowed:
  - '**'
"""

# Deliberately broken: codex w/o worktree, reviewer w/ sonnet, overlapping
# write globs, non-serial shared_foundation, unowned shared resource.
BAD_MANIFEST = """
run_id: 2026-06-26-bad
shared_resources:
  - src/types/orphan.ts
jobs:
  - id: task-0-foundation
    type: shared_foundation
    backend: claude
    model: opus
    isolation: direct
    run: parallel
    write_allowed: [src/db/schema.ts]
  - id: task-1-codex
    type: large_isolated
    backend: codex
    model: gpt-5.5
    isolation: direct
    run: parallel
    write_allowed: [src/features/**]
  - id: task-2-overlap
    type: bounded_crud
    backend: claude
    model: sonnet
    isolation: direct
    run: parallel
    write_allowed: [src/features/api/**]
  - id: task-3-review
    type: integration_review
    backend: claude
    model: sonnet
    isolation: direct
    run: serial
    write_allowed: []
  - id: task-4-no-routing
    type: docs
    backend: claude
    isolation: direct
    run: parallel
    write_allowed: [docs/orphan-area.md]
  - id: task-5-bad-vocab
    type: docs
    backend: claude
    tier: turbo
    effort: extreme
    isolation: direct
    run: parallel
    write_allowed: [docs/another-area.md]
"""


# A complete, otherwise-valid manifest whose ONE defect is parallel + direct.
PARALLEL_DIRECT_MANIFEST = """
run_id: 2026-06-26-pd
feature: "pd"
spec_path: docs/superpowers/specs/2026-06-26-pd.md
plan_path: docs/superpowers/plans/2026-06-26-pd.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-pd.md
  domain: docs/superpowers/expert/2026-06-26-pd.md
  library: docs/superpowers/library-audit/2026-06-26-pd.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-build
    title: "build slice"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: direct
    run: parallel
    write_allowed: [src/build/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# A complete manifest whose ONE defect is a path-traversal job id.
BAD_ID_MANIFEST = """
run_id: 2026-06-26-badid
feature: "badid"
spec_path: docs/superpowers/specs/2026-06-26-badid.md
plan_path: docs/superpowers/plans/2026-06-26-badid.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-badid.md
  domain: docs/superpowers/expert/2026-06-26-badid.md
  library: docs/superpowers/library-audit/2026-06-26-badid.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: ../x
    title: "evil"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    write_allowed: [src/evil/**]
    read_allowed: [src/**]
    acceptance: ["x"]
"""


# A complete, otherwise-valid manifest whose ONE defect is a model: haiku
# execution-layer override (must be rejected by the never-Haiku policy).
HAIKU_MODEL_MANIFEST = """
run_id: 2026-06-26-haiku
feature: "haiku"
spec_path: docs/superpowers/specs/2026-06-26-haiku.md
plan_path: docs/superpowers/plans/2026-06-26-haiku.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-haiku.md
  domain: docs/superpowers/expert/2026-06-26-haiku.md
  library: docs/superpowers/library-audit/2026-06-26-haiku.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-cheap
    title: "cheap slice"
    type: docs
    backend: claude
    model: claude-haiku-4
    isolation: worktree
    run: parallel
    write_allowed: [docs/cheap.md]
    read_allowed: [src/**]
    acceptance: ["x"]
"""

# A complete manifest whose ONE defect is a dangling depends_on reference.
DANGLING_DEP_MANIFEST = """
run_id: 2026-06-26-dangling
feature: "dangling"
spec_path: docs/superpowers/specs/2026-06-26-dangling.md
plan_path: docs/superpowers/plans/2026-06-26-dangling.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-dangling.md
  domain: docs/superpowers/expert/2026-06-26-dangling.md
  library: docs/superpowers/library-audit/2026-06-26-dangling.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-build
    title: "build slice"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    depends_on: [task-0-missing]
    write_allowed: [src/build/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# A complete manifest whose ONE defect is a depends_on cycle (A→B→A).
CYCLE_DEP_MANIFEST = """
run_id: 2026-06-26-cycle
feature: "cycle"
spec_path: docs/superpowers/specs/2026-06-26-cycle.md
plan_path: docs/superpowers/plans/2026-06-26-cycle.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-cycle.md
  domain: docs/superpowers/expert/2026-06-26-cycle.md
  library: docs/superpowers/library-audit/2026-06-26-cycle.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-a
    title: "a"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    depends_on: [task-b]
    write_allowed: [src/a/**]
    read_allowed: [src/**]
    acceptance: ["a"]
  - id: task-b
    title: "b"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    depends_on: [task-a]
    write_allowed: [src/b/**]
    read_allowed: [src/**]
    acceptance: ["b"]
"""

# A complete manifest whose ONE defect is a wrong-typed required field
# (acceptance_criteria provided as a scalar string instead of a list).
WRONG_TYPE_MANIFEST = """
run_id: 2026-06-26-wrongtype
feature: "wrongtype"
spec_path: docs/superpowers/specs/2026-06-26-wrongtype.md
plan_path: docs/superpowers/plans/2026-06-26-wrongtype.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-26-wrongtype.md
  domain: docs/superpowers/expert/2026-06-26-wrongtype.md
  library: docs/superpowers/library-audit/2026-06-26-wrongtype.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria: "ships"
jobs:
  - id: task-1-build
    title: "build slice"
    type: bounded_crud
    backend: claude
    tier: standard
    isolation: worktree
    run: parallel
    write_allowed: [src/build/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, fully-VALID manifest: a codex job with effort: xhigh (xhigh is
# valid iff backend: codex — this is the accept direction of that rule).
XHIGH_CODEX_MANIFEST = """
run_id: 2026-07-11-xhigh-ok
feature: "xhigh-ok"
spec_path: docs/superpowers/specs/2026-07-11-xhigh-ok.md
plan_path: docs/superpowers/plans/2026-07-11-xhigh-ok.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-11-xhigh-ok.md
  domain: docs/superpowers/expert/2026-07-11-xhigh-ok.md
  library: docs/superpowers/library-audit/2026-07-11-xhigh-ok.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-codex-xhigh
    title: "codex xhigh slice"
    type: large_isolated
    backend: codex
    tier: deep
    effort: xhigh
    isolation: worktree
    run: parallel
    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

# A complete manifest whose ONE defect is effort: xhigh on a NON-codex backend
# (the reject direction: xhigh is codex-only).
XHIGH_CLAUDE_MANIFEST = """
run_id: 2026-07-11-xhigh-bad
feature: "xhigh-bad"
spec_path: docs/superpowers/specs/2026-07-11-xhigh-bad.md
plan_path: docs/superpowers/plans/2026-07-11-xhigh-bad.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-11-xhigh-bad.md
  domain: docs/superpowers/expert/2026-07-11-xhigh-bad.md
  library: docs/superpowers/library-audit/2026-07-11-xhigh-bad.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-claude-xhigh
    title: "claude xhigh slice"
    type: core_slice
    backend: claude
    tier: deep
    effort: xhigh
    isolation: worktree
    run: parallel
    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

def _timeout_manifest(timeout_line):
    """A complete, otherwise-valid single-codex-job manifest whose ONLY variable is
    the optional `timeout_sec` line. Pass "" to omit the field entirely (the ABSENT
    case, which must stay valid — that is what every already-committed manifest
    looks like)."""
    return """
run_id: 2026-07-26-timeout
feature: "timeout"
spec_path: docs/superpowers/specs/2026-07-26-timeout.md
plan_path: docs/superpowers/plans/2026-07-26-timeout.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-26-timeout.md
  domain: docs/superpowers/expert/2026-07-26-timeout.md
  library: docs/superpowers/library-audit/2026-07-26-timeout.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-timeout
    title: "timeout slice"
    type: large_isolated
    backend: codex
    tier: deep
    effort: high
    isolation: worktree
    run: parallel
%s    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
""" % (("    timeout_sec: %s\n" % timeout_line) if timeout_line != "" else "")


def _v3_manifest(triage_block="", contract_block="", job_line="", retry_block="",
                 constraints_block=""):
    """A complete, otherwise-valid single-job manifest whose ONLY variables are the
    v3.0 additions: the top-level ``triage`` block (Feature A2), the top-level
    ``test_contract`` block (Feature B2), one extra per-job line (``test_scope``),
    the v3.4.8 top-level ``retry`` block (Task B), and the v3.4.17 top-level
    ``global_constraints`` list (``job_line`` also carries the per-job
    ``interfaces`` mapping, which is several lines rather than one).

    Pass "" to omit a block entirely — the ABSENT case, which is what every manifest
    committed before 3.0 looks like and which MUST stay valid when ``--require-triage``
    is not passed (that is what keeps the CI historical sweep and 3.0's own bootstrap
    manifest green)."""
    return """
run_id: 2026-09-01-v3
feature: "v3 contract"
spec_path: docs/superpowers/specs/2026-09-01-v3.md
plan_path: docs/superpowers/plans/2026-09-01-v3.md
audits:
  archaeology: docs/superpowers/archaeology/2026-09-01-v3.md
  domain: docs/superpowers/expert/2026-09-01-v3.md
  library: docs/superpowers/library-audit/2026-09-01-v3.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
%s%s%s%sjobs:
  - id: task-1-v3
    title: "v3 slice"
    type: bounded_crud
    backend: claude
    tier: standard
    effort: medium
    isolation: worktree
    run: parallel
%s    write_allowed: [src/features/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
""" % (triage_block, contract_block, retry_block, constraints_block, job_line)


# A well-formed `triage` block (Feature A2). `digest` is substituted so a test can
# plant a mismatch against the taxonomy bytes on disk.
def _triage_block(digest, tier="SCOPED", pre_eval_id="2026-09-01T101500Z-v3-a1b2",
                  decided_at="2026-09-01T10:15:00Z", drop=None, extra=""):
    lines = {
        "tier": "  tier: %s" % tier,
        "pre_eval_id": "  pre_eval_id: %s" % pre_eval_id,
        "taxonomy_digest": '  taxonomy_digest: "%s"' % digest,
        "decided_at": '  decided_at: "%s"' % decided_at,
    }
    if drop:
        lines.pop(drop, None)
    body = "\n".join(lines.values())
    return "triage:\n%s\n%s" % (body, extra)

# A complete, otherwise-valid manifest whose ONE defect is an antigravity job with
# isolation: direct (an external no-kernel-sandbox worker MUST be worktree-isolated).
# Uses run: serial so the ONLY violation is the antigravity⇒worktree invariant (not
# the parallel⇒worktree one).
ANTIGRAVITY_DIRECT_MANIFEST = """
run_id: 2026-06-27-agy
feature: "agy"
spec_path: docs/superpowers/specs/2026-06-27-agy.md
plan_path: docs/superpowers/plans/2026-06-27-agy.md
audits:
  archaeology: docs/superpowers/archaeology/2026-06-27-agy.md
  domain: docs/superpowers/expert/2026-06-27-agy.md
  library: docs/superpowers/library-audit/2026-06-27-agy.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-agy
    title: "antigravity slice"
    type: large_isolated
    backend: antigravity
    tier: standard
    isolation: direct
    run: serial
    write_allowed: [src/agy/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, otherwise-valid manifest whose ONE defect is an opencode job with
# isolation: direct (opencode has NO kernel write-confinement and defaults to
# allowing all operations, so worktree isolation is REQUIRED).
OPENCODE_DIRECT_MANIFEST = """
run_id: 2026-07-13-opencode
feature: "opencode"
spec_path: docs/superpowers/specs/2026-07-13-opencode.md
plan_path: docs/superpowers/plans/2026-07-13-opencode.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode.md
  domain: docs/superpowers/expert/2026-07-13-opencode.md
  library: docs/superpowers/library-audit/2026-07-13-opencode.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    tier: standard
    isolation: direct
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, VALID manifest with a single opencode job, worktree-isolated -- confirms
# "opencode" is accepted end-to-end (VALID_BACKENDS + the worktree invariant) once it
# is NOT paired with isolation: direct. model is a genuine "provider/model" string,
# matching the resolver's opencode convention.
OPENCODE_WORKTREE_MANIFEST = """
run_id: 2026-07-13-opencode-ok
feature: "opencode-ok"
spec_path: docs/superpowers/specs/2026-07-13-opencode-ok.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-ok.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-ok.md
  domain: docs/superpowers/expert/2026-07-13-opencode-ok.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-ok.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-ok
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: "anthropic/claude-sonnet-4-6"
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A complete, otherwise-valid manifest whose ONE defect is a REVIEWER job routed to
# backend: opencode. opencode is a lower-trust, opt-in, WORKER-ONLY backend (see
# adapter-opencode.md) -- a reviewer job must never resolve its Review-Gate opus/deep
# guarantee through a low-trust external router. tier: deep + isolation: worktree are
# otherwise satisfied, so ONLY the WORKER-ONLY violation fires.
OPENCODE_REVIEWER_MANIFEST = """
run_id: 2026-07-13-opencode-reviewer
feature: "opencode-reviewer"
spec_path: docs/superpowers/specs/2026-07-13-opencode-reviewer.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-reviewer.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-reviewer.md
  domain: docs/superpowers/expert/2026-07-13-opencode-reviewer.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-reviewer.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-quality-review
    title: "quality review pass"
    type: quality_review
    backend: opencode
    tier: deep
    isolation: worktree
    run: serial
    write_allowed: []
    read_allowed: [src/**]
    acceptance: ["reviewed"]
"""


# A complete, otherwise-valid manifest whose ONE defect is an opencode job with a BARE
# (slash-less) explicit model override. opencode addresses models as a "provider/model"
# string with no single-vendor default (see adapter-opencode.md); a bare name would
# silently pass a naive validator but fail opencode's own model resolution / the
# worker's `-m` argument at run time, so it must be rejected here, before dispatch.
OPENCODE_BARE_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-bare-model
feature: "opencode-bare-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-bare-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-bare-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-bare-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-bare-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-bare-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-bare
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: "gpt-6"
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# Same defect, malformed shape variant: a trailing slash with an EMPTY model half
# ("anthropic/") — the '/' is present but one side is empty, still not a valid
# provider/model pair.
OPENCODE_MALFORMED_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-malformed-model
feature: "opencode-malformed-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-malformed-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-malformed-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-malformed-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-malformed-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-malformed-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-malformed
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: "anthropic/"
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


# A family of opencode jobs whose explicit `model` is a NON-STRING (int / inline list
# / inline mapping). A non-string can never be a valid 'provider/model' string, and the
# shape check must NOT skip it (an earlier version only ran the check for str models, so
# a `model: 42` slipped through with zero violations). Each carries `tier: standard` so
# the model override is present-but-invalid without also tripping the model-or-tier
# requirement — isolating the shape violation as the guaranteed one.
OPENCODE_INT_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-int-model
feature: "opencode-int-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-int-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-int-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-int-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-int-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-int-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-int
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: 42
    tier: standard
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


OPENCODE_LIST_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-list-model
feature: "opencode-list-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-list-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-list-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-list-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-list-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-list-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-list
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: ["anthropic/claude-opus-4-6"]
    tier: standard
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""


OPENCODE_DICT_MODEL_MANIFEST = """
run_id: 2026-07-13-opencode-dict-model
feature: "opencode-dict-model"
spec_path: docs/superpowers/specs/2026-07-13-opencode-dict-model.md
plan_path: docs/superpowers/plans/2026-07-13-opencode-dict-model.md
audits:
  archaeology: docs/superpowers/archaeology/2026-07-13-opencode-dict-model.md
  domain: docs/superpowers/expert/2026-07-13-opencode-dict-model.md
  library: docs/superpowers/library-audit/2026-07-13-opencode-dict-model.md
routing_stance: balanced
max_parallel: 2
acceptance_criteria:
  - "ships"
jobs:
  - id: task-1-opencode-dict
    title: "opencode slice"
    type: large_isolated
    backend: opencode
    model: {}
    tier: standard
    isolation: worktree
    run: serial
    write_allowed: [src/opencode/**]
    read_allowed: [src/**]
    acceptance: ["builds"]
"""

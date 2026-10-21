"""Optional top-level blocks: test_contract, retry, provision, toolchain_artifacts, interfaces."""

from .rules import (
    TEST_CONTRACT_ALLOWED_KEYS, IMPACTED_MAP_REQUIRED_KEYS, RETRY_ALLOWED_KEYS,
    INTERFACES_ALLOWED_KEYS)


# --------------------------------------------------------------------------- #
# v3.0 (Feature B2) — `test_contract` + per-job `test_scope`.
# --------------------------------------------------------------------------- #
def _validate_test_contract(manifest, job_scopes):
    """Return violations for the optional top-level ``test_contract`` block and for
    the per-job ``test_scope`` values already collected (enum-checked in the jobs
    loop). ``job_scopes`` is a list of ``(job_id, scope_or_None)``."""
    problems = []
    contract = manifest.get("test_contract")
    present = "test_contract" in manifest and contract is not None

    if present and not isinstance(contract, dict):
        problems.append("manifest 'test_contract' must be a mapping (got %r)"
                        % (contract,))
        contract = {}
        present = False
    if not isinstance(contract, dict):
        contract = {}

    if present:
        for key in contract:
            if key not in TEST_CONTRACT_ALLOWED_KEYS:
                problems.append(
                    "manifest test_contract has unknown key '%s' (allowed: %s)"
                    % (key, ", ".join(TEST_CONTRACT_ALLOWED_KEYS))
                )
        for key in ("floor_command", "full_command"):
            val = contract.get(key)
            if val is not None and not isinstance(val, str):
                problems.append("manifest test_contract.%s must be a string "
                                "(got %r)" % (key, val))
        if "timeout_s" in contract:
            tval = contract.get("timeout_s")
            if (
                isinstance(tval, bool)
                or not isinstance(tval, int)
                or not (1 <= tval <= 540)
            ):
                problems.append(
                    "manifest test_contract.timeout_s must be an integer "
                    "between 1 and 540 (got %r)" % (tval,)
                )
        imap = contract.get("impacted_map")
        if imap is not None:
            if not isinstance(imap, list):
                problems.append("manifest test_contract.impacted_map must be a "
                                "list of {when, run} mappings")
            else:
                for i, row in enumerate(imap):
                    if not isinstance(row, dict):
                        problems.append("manifest test_contract.impacted_map[%d] "
                                        "must be a mapping with 'when' and 'run'"
                                        % i)
                        continue
                    for key in IMPACTED_MAP_REQUIRED_KEYS:
                        if row.get(key) in (None, "", [], {}):
                            problems.append(
                                "manifest test_contract.impacted_map[%d] missing "
                                "required field '%s' — a half-declared rule "
                                "selects nothing" % (i, key)
                            )
                        elif not isinstance(row.get(key), str):
                            problems.append(
                                "manifest test_contract.impacted_map[%d].%s must "
                                "be a string (got %r)" % (i, key, row.get(key))
                            )
                    for key in row:
                        if key not in IMPACTED_MAP_REQUIRED_KEYS:
                            problems.append(
                                "manifest test_contract.impacted_map[%d] has "
                                "unknown key '%s' (allowed: %s)"
                                % (i, key, ", ".join(IMPACTED_MAP_REQUIRED_KEYS))
                            )

    # Resolution rules. A scope must never resolve to running nothing: `floor_only`
    # needs a real floor_command, and `impacted` needs a full_command because a
    # changed path matching no `when` glob is unknown blast radius and falls back
    # to the full suite.
    floor_cmd = contract.get("floor_command")
    full_cmd = contract.get("full_command")
    for jid, scope in job_scopes:
        if scope == "floor_only" and not (isinstance(floor_cmd, str) and floor_cmd.strip()):
            problems.append(
                "job '%s' has test_scope: floor_only but test_contract.floor_command "
                "is absent or empty — floor_only means ONLY the floor, never nothing"
                % jid
            )
        if scope == "impacted" and not (isinstance(full_cmd, str) and full_cmd.strip()):
            problems.append(
                "job '%s' has test_scope: impacted but test_contract.full_command is "
                "absent or empty — a changed path matching no impacted_map 'when' "
                "glob resolves to full_command, so it would resolve to nothing" % jid
            )
    return problems


def _validate_retry(manifest):
    """Return violations for the optional top-level ``retry`` block
    (v3.4.8, Task B): ``{max_attempts: int 1..3, escalate_reviewer: bool}``.
    ABSENT is valid — every manifest committed before 3.4.8 has no ``retry``
    key at all."""
    problems = []
    retry = manifest.get("retry")
    present = "retry" in manifest and retry is not None

    if present and not isinstance(retry, dict):
        problems.append("manifest 'retry' must be a mapping (got %r)" % (retry,))
        return problems
    if not present:
        return problems

    for key in retry:
        if key not in RETRY_ALLOWED_KEYS:
            problems.append(
                "manifest retry has unknown key '%s' (allowed: %s)"
                % (key, ", ".join(RETRY_ALLOWED_KEYS))
            )

    if "max_attempts" in retry:
        ma = retry.get("max_attempts")
        if isinstance(ma, bool) or not isinstance(ma, int) or not (1 <= ma <= 3):
            problems.append(
                "manifest retry.max_attempts must be an integer between 1 "
                "and 3 (got %r)" % (ma,)
            )

    if "escalate_reviewer" in retry:
        er = retry.get("escalate_reviewer")
        if not isinstance(er, bool):
            problems.append(
                "manifest retry.escalate_reviewer must be a boolean (got %r)"
                % (er,)
            )

    return problems


def _validate_provision(manifest):
    """Return violations for the optional top-level ``provision_command`` +
    ``provision_timeout_s`` fields — a command a fresh worktree runs ONCE before
    the before-image is captured (e.g. ``npm ci``). Idempotent by convention and
    must not modify tracked files; the caller (not this validator) is what
    actually runs it. ABSENT is valid — every manifest committed before this
    field existed has neither key. ``provision_timeout_s`` defaults to 600 when
    absent; that default is applied by the caller, never asserted here as a
    violation of absence."""
    problems = []
    if "provision_command" in manifest and manifest.get("provision_command") is not None:
        pc = manifest.get("provision_command")
        if not isinstance(pc, str) or not pc.strip() or "\n" in pc:
            problems.append(
                "manifest 'provision_command' must be a non-empty, single-line "
                "string (got %r)" % (pc,)
            )
    if "provision_timeout_s" in manifest and manifest.get("provision_timeout_s") is not None:
        pt = manifest.get("provision_timeout_s")
        if isinstance(pt, bool) or not isinstance(pt, int) or not (1 <= pt <= 1800):
            problems.append(
                "manifest 'provision_timeout_s' must be an integer between 1 "
                "and 1800 (got %r)" % (pt,)
            )
    return problems


def _string_list_problems(value, label):
    """Return violations for ``value`` as a list of non-empty strings.

    Shared by ``global_constraints`` and both ``interfaces`` keys so the two
    fields cannot drift into two different definitions of "a list of lines"."""
    problems = []
    if not isinstance(value, list):
        problems.append("%s must be a list of strings (got %r)" % (label, value))
        return problems
    for idx, item in enumerate(value):
        # bool is not a str, so `- true` is caught here rather than accepted as
        # a line. An empty or whitespace-only entry is caught too: a blank
        # constraint is a line the implementer cannot act on.
        if not isinstance(item, str) or not item.strip():
            problems.append("%s[%d] must be a non-empty string (got %r)"
                            % (label, idx, item))
    return problems


# A glob is a catch-all if, after stripping a leading './' or '/', it reduces
# to one of these — i.e. it would match every path in the tree. Kept as a
# closed tuple (mirrors RETRY_ALLOWED_KEYS etc.) rather than a "looks broad"
# heuristic, so the rule stays boring and inspectable.
_CATCH_ALL_TOOLCHAIN_GLOBS = ("*", "**", "**/*")


def _validate_toolchain_artifacts(manifest):
    """Return violations for the optional top-level ``toolchain_artifacts``
    list (issue #22): globs naming build/test-tool bookkeeping paths (a
    TypeScript incremental build cache, a Vitest results cache under
    ``node_modules/.vite/``, ...) that a downstream toolchain's own first run
    drops into a fresh worktree, gitignored, after the scope gate's
    post-provisioning snapshot was taken. ``write_allowed`` cannot name them
    without widening a job's disjoint lane, so this list is a SEPARATE,
    human-reviewed exemption the scope gate (``compound-v-scope-check.py``)
    only honours when ``git check-ignore`` independently reconfirms the path
    is actually gitignored at gate time — this validator checks only the
    manifest's SHAPE, never git state.

    ABSENT or ``None`` is valid — every manifest committed before this field
    existed has neither key, and a bare ``toolchain_artifacts:`` line parses to
    None (same absent-vs-null rule as ``global_constraints``).

    Beyond the shared list-of-non-empty-strings shape check, two further rules
    apply, because a permissive shape check alone would let a reviewer wave
    through a glob that quietly defeats the gate:
      * a CATCH-ALL glob is refused outright — one of ``*``, ``**``, ``**/*``,
        ``/**``, ``./**``, or any entry whose form (after stripping one leading
        ``./`` or ``/``) reduces to ``*``, ``**``, or ``**/*``. Such a glob would
        exempt every gitignored write in the entire tree, which is exactly the
        blanket carve-out the scope gate's docstring says it never originates
        on its own — a catch-all here would make this manifest originate one
        instead.
      * an entry containing a newline is refused — the same single-line
        discipline ``_validate_provision`` applies to ``provision_command``,
        so a multi-line string can't smuggle a second (unreviewed) glob past a
        reviewer skimming one line per bullet."""
    if "toolchain_artifacts" not in manifest:
        return []
    value = manifest.get("toolchain_artifacts")
    if value is None:
        return []
    problems = _string_list_problems(value, "manifest 'toolchain_artifacts'")
    if not isinstance(value, list):
        return problems
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            continue  # already reported by _string_list_problems
        if "\n" in item:
            problems.append(
                "manifest 'toolchain_artifacts'[%d] must be a single-line "
                "string (got %r)" % (idx, item)
            )
            continue
        normalized = item
        if normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.lstrip("/")
        if normalized in _CATCH_ALL_TOOLCHAIN_GLOBS:
            problems.append(
                "manifest 'toolchain_artifacts'[%d] is a catch-all glob (%r) "
                "— this would exempt every gitignored write in the tree; name "
                "the specific toolchain-artifact paths instead" % (idx, item)
            )
    return problems


def _validate_global_constraints(manifest):
    """Return violations for the optional top-level ``global_constraints`` list
    (v3.4.17): the plan's ``## Global Constraints`` lines, copied VERBATIM.

    ABSENT is valid — a plan written before Superpowers 6.2.0 has no such
    section, so a manifest materialized from it carries no such key."""
    if "global_constraints" not in manifest:
        return []
    # ONLY A MISSING KEY IS ABSENT (cross-model review r1, finding 6). A bare
    # `global_constraints:` line parses to None in BOTH parsers, and this used to
    # read that as the absent case — so a materializer that wrote the key and
    # then failed to fill it validated clean and every implementer prompt lost
    # the plan's constraints silently. A key someone wrote down has to hold the
    # documented shape; `[]` is how you say "none" on purpose. (This is
    # deliberately stricter than `retry`, whose null-is-absent leniency predates
    # the rule and is not a precedent to copy.)
    return _string_list_problems(manifest.get("global_constraints"),
                                 "manifest 'global_constraints'")


def _validate_interfaces(job, jid):
    """Return violations for one job's optional ``interfaces`` mapping
    (v3.4.17): ``{consumes: [string], produces: [string]}``, copied VERBATIM
    from the plan task's ``**Interfaces:**`` block.

    ABSENT is valid, and so is either key on its own — a first task consumes
    nothing, a last task produces nothing anyone else reads."""
    if "interfaces" not in job:
        return []
    # Only a MISSING key is absent — see _validate_global_constraints. A bare
    # `interfaces:` line is None, which is not a mapping and is refused as one.
    iface = job.get("interfaces")
    problems = []
    if not isinstance(iface, dict):
        problems.append(
            "job '%s' interfaces must be a mapping with keys %s (got %r)"
            % (jid, "/".join(INTERFACES_ALLOWED_KEYS), iface)
        )
        return problems
    for key in iface:
        if key not in INTERFACES_ALLOWED_KEYS:
            problems.append(
                "job '%s' interfaces has unknown key '%s' (allowed: %s)"
                % (jid, key, ", ".join(INTERFACES_ALLOWED_KEYS))
            )
    for key in INTERFACES_ALLOWED_KEYS:
        # Same rule one level down: a bare `consumes:` is None, not absent.
        if key not in iface:
            continue
        problems.extend(_string_list_problems(
            iface.get(key), "job '%s' interfaces.%s" % (jid, key)))
    return problems

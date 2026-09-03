#!/usr/bin/env python3
"""
Compound V — T3 classify as a PARENT-invoked Task contract (NOT Python -> Claude) [v2.9 A2].

Tier 3 (T3) is the pre-eval's ONLY model call, reached only when `T1 unclassified ∧ T2
insufficient` (spec §3). It is deliberately NOT a Python-calls-a-model script: the pre-eval
engine (A3) is **T3-agnostic** — it accepts `--t3-category` and, when T3 is needed but the
category is unset, returns `needs_t3` with a ready prompt. The **parent harness** runs ONE
`light`-tier Task with that prompt, parses the enum reply, and re-invokes the engine with the
resolved `--t3-category`. This mirrors the `needs_review` parent-Task contract (CR2-5 / CR1-5).

CRITICAL (N1): this module is **net-new**. `compound-v-resolve-model.py` only RESOLVES a model
name — it NEVER calls a model. Nothing here calls a model on the Claude path either; only the
**optional headless-codex route** (for non-Claude harnesses) spawns an external CLI, and it does
so **exclusively** through the shared process-group timeout supervisor
(`compound-v-run-with-timeout.py`) with stdin closed (`</dev/null`), a read-only sandbox, network
disabled, and a bounded output sink (CR5-8). No bare `subprocess.run(timeout=...)` on the CLI.

This script provides:
  (a) the PROMPT BUILDER  — `build_prompt(request_text, resolved_paths, ...)` — a bounded, tiny
      input (request text + resolved paths + the output-category definitions);
  (b) the STRICT ENUM PARSER — `parse_category(reply_text)` — used by the parent to turn the
      light Task's reply into an enum; and
  (c) the OPTIONAL codex route — `classify_via_codex(...)` — same bounded prompt, spawned through
      the timeout supervisor.

`category ∈ {plumbing, user-facing-minor, user-facing-major, unknown}` (spec §2 T3 truth table).
FAIL-CLOSED EVERYWHERE (Iron-Invariant #5): any error / timeout / unparse / non-enum reply →
`unknown` → the engine treats `unknown` as `FULL_PIPELINE`. T3 alone never manufactures fast-path
eligibility (spec §2, round-3 fix); the enum -> band scoring is A3's authority (this module never
scores).

WHAT THE THIRD TIER DOES AND DOES NOT CHANGE HERE (v3.0 spec §A1)
-----------------------------------------------------------------
The scorer now emits three decisions (`FASTPATH_ELIGIBLE` / `SCOPED_PIPELINE` /
`FULL_PIPELINE`). This module's contract is unchanged: it still returns ONE of four
category enums and never a decision. Two consequences are worth stating precisely rather
than leaving to inference, because the round-3 sentence above was written when there were
only two tiers:

  * `unknown` is still an unconditional `FULL_PIPELINE` — it fails the axes closed, and no
    matrix cell is reachable from an unknown band.
  * "T3 alone never manufactures fast-path eligibility" remains exactly true of the DIRECT
    tier: `plumbing` maps to (low, low), but DIRECT additionally requires taxonomy safety
    coverage, no fired override, `fan_out <= threshold` and a single literal path — none of
    which this module can supply. It is NOT true of SCOPED: `user-facing-minor` maps to
    (medium, medium), a genuine SCOPED cell. That is by design — SCOPED buys a manifest, a
    run directory, the scope gate, the floor and a review pass, so it is not a class a
    model-derived category can route around. Only the auto-route class is, and DIRECT is
    the only tier in it.

Usage:
  compound-v-classify-request.py --build-prompt --request "<text>" [--path P ...] \
                                 [--taxonomy-category C ...]
  compound-v-classify-request.py --parse [--reply "<text>" | --reply-file F | -]   # stdin default
  compound-v-classify-request.py --classify-codex --request "<text>" [--path P ...] \
                                 [--model M] [--timeout S] [--cwd DIR] [--config PATH]
  compound-v-classify-request.py --classify-headless --request "<text>" [--path P ...] \
                                 [--cwd DIR] [--timeout S] [--config PATH] \
                                 [--prompt-file F]
  compound-v-classify-request.py --selftest

`--parse` / `--classify-codex` / `--classify-headless` print JSON `{"category": "<enum>", ...}`
and exit 0 (the category IS the result). Usage errors exit 2.

`--classify-headless` (v3.4.1) is the ONE mode that answers T3 without a parent Task — see
section (d) below for why `hooks/triage-prompt-nudge.sh` needs it and what it does not change.
`CV_CLASSIFY_CLAUDE_BIN` / `CV_CLASSIFY_CODEX_BIN` override which binary each route runs, which
is how the tests plant fakes instead of spending a real model call.

Python 3.9-safe, stdlib only. Soft dependencies (resolver + supervisor) are imported by path with
inline fallbacks so this module never hard-fails.
"""

import argparse
import json
import os
import subprocess
import sys

HEADLESS_ENV_MARKER = "CV_HEADLESS_CLASSIFY"


def _headless_env():
    """The child's environment, marked. The nested `claude -p` loads the SAME
    project hooks as the session that spawned it, so without a marker our own
    UserPromptSubmit hook triaged the classifier's prompt as a change request,
    wrote junk pre-eval records and starved the outer classify of its budget
    (finding 131, 2026-09-03). Every hook exits 0 first thing when it sees this."""
    env = dict(os.environ)
    env[HEADLESS_ENV_MARKER] = "1"
    return env


# --------------------------------------------------------------------------- #
# The T3 output enum — THE single shared contract (Global Constraints: define once).
# spec §2 T3 total truth table maps these to (difficulty, impact) bands; that scoring
# is A3's authority. This module only produces/validates the enum, never the bands.
# --------------------------------------------------------------------------- #
CATEGORIES = ("plumbing", "user-facing-minor", "user-facing-major", "unknown")
FAIL_CLOSED_CATEGORY = "unknown"   # any ambiguity / error / unparse collapses here

# Bounds for the "tiny input" budget (spec §3 rule 2 — bounded enum output, no thinking budget).
MAX_REQUEST_CHARS = 2000
MAX_PATHS = 20
MAX_PATH_CHARS = 200
MAX_TAXONOMY_CATEGORIES = 40
MAX_TAXONOMY_CATEGORY_CHARS = 80
MAX_PROMPT_CHARS = 8000            # hard ceiling on the whole assembled prompt

# Codex route bounds.
CODEX_TIMEOUT_S = 30               # wall-clock cap for the one-shot classify
CODEX_STDOUT_CAP = 1 << 16        # bounded output sink for codex's event stream (CR5-8)
DEFAULT_CODEX_LIGHT_MODEL = "gpt-5.6-luna"   # fallback iff the resolver is unavailable
TIMEOUT_EXIT_CODE = 124           # GNU-timeout / supervisor convention
NOT_FOUND_EXIT_CODE = 127         # the supervisor's "command does not exist" convention

# Headless (v3.4.1, finding 50) bounds. The whole headless budget is 15 s with a 3 s grace,
# because the caller that needs it is `hooks/triage-prompt-nudge.sh` and a hook's budget is
# the outer bound: `hooks/hooks.json` registers UserPromptSubmit with `timeout: 25`, which is
# 15 + 3 plus room for the two engine invocations around it. A 30 s classify does not fit
# inside a hook and never did — that is pre-flight amendment 1, not a preference.
HEADLESS_TIMEOUT_S = 15
HEADLESS_GRACE_S = 3
CLAUDE_STDOUT_CAP = 1 << 16       # bounded output sink for the reply text
DEFAULT_CLAUDE_LIGHT_MODEL = "sonnet"        # fallback iff the resolver is unavailable
# Below this many seconds left, a second backend is not worth starting: it would either be
# killed immediately or push the hook past its registration timeout.
MIN_SECONDS_FOR_A_SECOND_BACKEND = 4

# Human-readable category definitions embedded in the prompt (spec §2 semantics; AC-8:
# impact is what a change IS, not only where it lives).
_CATEGORY_DEFS = [
    ("plumbing",
     "internal-only change with no user-visible or externally-observable behavior "
     "(build config, lint rules, dev tooling, pure refactor, tests, comments)."),
    ("user-facing-minor",
     "a small, low-risk user-visible change (copy tweak, a single style/color, a "
     "self-contained UI adjustment) that does NOT touch auth, payments, data, i18n, "
     "legal/compliance copy, feature flags, or shared design tokens."),
    ("user-facing-major",
     "a user-visible or externally-observable change with real blast radius — auth, "
     "payments, security, data/migrations, i18n placeholders, legal/compliance copy, "
     "feature-flag definitions, shared design tokens/config constants, or anything a "
     "small diff could break widely."),
    ("unknown",
     "you cannot confidently place the change in exactly one of the above categories."),
]


# =========================================================================== #
# (a) PROMPT BUILDER
# =========================================================================== #
def _truncate(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")   # ellipsis marker


def _bounded_paths(resolved_paths):
    out = []
    for p in (resolved_paths or [])[:MAX_PATHS]:
        out.append(_truncate(p, MAX_PATH_CHARS))
    return out


def build_prompt(request_text, resolved_paths=None, taxonomy_categories=None):
    """Build the bounded T3 classify prompt: tiny input = request text + resolved paths +
    the output-category definitions (+ optional taxonomy category hints). The model is
    instructed to reply with EXACTLY ONE token from CATEGORIES and nothing else, so the
    strict parser can consume it. The whole prompt is hard-capped at MAX_PROMPT_CHARS."""
    req = _truncate(request_text, MAX_REQUEST_CHARS)
    paths = _bounded_paths(resolved_paths)

    lines = [
        "You are a one-shot change-impact classifier for a code-change request.",
        "Classify the request into EXACTLY ONE of these categories:",
        "",
    ]
    for name, desc in _CATEGORY_DEFS:
        lines.append("- %s: %s" % (name, desc))
    lines.append("")
    lines.append("REQUEST:")
    lines.append(req if req else "(empty request)")
    lines.append("")
    lines.append("RESOLVED FILE PATHS (may be empty or approximate):")
    if paths:
        for p in paths:
            lines.append("- %s" % p)
    else:
        lines.append("- (none resolved)")

    if taxonomy_categories:
        hints = [
            _truncate(c, MAX_TAXONOMY_CATEGORY_CHARS)
            for c in list(taxonomy_categories)[:MAX_TAXONOMY_CATEGORIES]
        ]
        lines.append("")
        lines.append("PROJECT IMPACT-TAXONOMY CATEGORIES (context only):")
        for h in hints:
            lines.append("- %s" % h)

    lines.append("")
    lines.append(
        "Reply with EXACTLY ONE of these tokens and NOTHING else "
        "(no punctuation, no explanation): "
        + ", ".join(CATEGORIES) + "."
    )
    lines.append("If you are unsure, reply: unknown.")

    prompt = "\n".join(lines)
    if len(prompt) > MAX_PROMPT_CHARS:
        # Hard ceiling: keep the instruction tail (the enum contract) intact, truncate the body.
        tail = ("\n\nReply with EXACTLY ONE of these tokens and NOTHING else: "
                + ", ".join(CATEGORIES) + ".")
        prompt = prompt[: MAX_PROMPT_CHARS - len(tail)] + tail
    return prompt


# =========================================================================== #
# (b) STRICT ENUM PARSER
# =========================================================================== #
_CATEGORY_SET = frozenset(CATEGORIES)


def parse_category(reply_text):
    """Strict enum parser. Returns one of CATEGORIES. Any error / empty / prose / non-enum
    reply collapses to FAIL_CLOSED_CATEGORY ('unknown') — the fail-closed contract.

    Tolerant ONLY of trivial wrapping a light model realistically adds around a single
    token: surrounding whitespace, a single pair of quotes/backticks, a fenced code block,
    and a single trailing sentence-punctuation char. It is deliberately NOT tolerant of
    prose containing an enum word (that must fail closed to 'unknown')."""
    if reply_text is None:
        return FAIL_CLOSED_CATEGORY
    s = str(reply_text).strip()
    if not s:
        return FAIL_CLOSED_CATEGORY

    # Strip a fenced code block: ```...``` (optionally ```lang). Keep the inner text.
    if s.startswith("```") and s.endswith("```") and len(s) >= 6:
        inner = s[3:-3].strip()
        # drop a leading language tag on the first line
        if "\n" in inner:
            first, rest = inner.split("\n", 1)
            if first and " " not in first and first.lower() not in _CATEGORY_SET:
                inner = rest.strip()
        s = inner.strip()

    # Collapse to a single line if the reply is exactly one non-empty line.
    non_empty_lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(non_empty_lines) == 1:
        s = non_empty_lines[0]
    elif len(non_empty_lines) > 1:
        return FAIL_CLOSED_CATEGORY   # multi-line prose is not a single-token reply

    # Strip surrounding matched quotes / backticks.
    for q in ('"', "'", "`"):
        if len(s) >= 2 and s[0] == q and s[-1] == q:
            s = s[1:-1].strip()
            break

    # Strip a single trailing sentence-punctuation char.
    if s and s[-1] in ".!,;:":
        s = s[:-1].strip()

    token = s.lower()
    if token in _CATEGORY_SET:
        return token
    return FAIL_CLOSED_CATEGORY


# =========================================================================== #
# (c) OPTIONAL headless-codex route
# =========================================================================== #
def _script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _supervisor_path():
    return os.path.join(_script_dir(), "compound-v-run-with-timeout.py")


def _resolve_model_module():
    """Import compound-v-resolve-model.py by path (READ-only sibling). None on failure."""
    import importlib.util

    path = os.path.join(_script_dir(), "compound-v-resolve-model.py")
    try:
        spec = importlib.util.spec_from_file_location("compound_v_resolve_model", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001
        return None


def resolve_codex_light_model(config_path=None):
    """Resolve the codex `light`-tier model by REUSING the resolver (never recopy its map);
    fail-safe to DEFAULT_CODEX_LIGHT_MODEL if the resolver is unavailable. This only picks a
    model NAME — it never calls a model (N1)."""
    mod = _resolve_model_module()
    if mod is not None:
        try:
            config_models = None
            if config_path:
                try:
                    config_models = mod.load_config_models(config_path)
                except Exception:  # noqa: BLE001
                    config_models = None
            res = mod.resolve("codex", "light", config_models=config_models)
            model = res.get("model") if isinstance(res, dict) else None
            if isinstance(model, str) and model:
                return model
        except Exception:  # noqa: BLE001
            pass
    return DEFAULT_CODEX_LIGHT_MODEL


def build_codex_command(prompt, model, cwd, supervisor_path, timeout_s,
                        max_output_bytes, events_file, last_msg_file, codex_bin="codex"):
    """Assemble the exact argv: the timeout supervisor wrapping a read-only `codex exec`.

    `codex_bin` is either a str (e.g. "codex") or a list (e.g. [python, fake.py]) so tests
    can inject a fake CLI. Output is bounded (CR5-8): codex's event stream goes to
    `events_file` capped at `max_output_bytes`; the final agent message (the enum reply) goes
    to `last_msg_file` via `--output-last-message`. Network is disabled; sandbox is read-only;
    stdin is closed by the supervisor (DEVNULL) for the whole process group."""
    bin_argv = [codex_bin] if isinstance(codex_bin, str) else list(codex_bin)
    codex_cmd = bin_argv + [
        "exec",
        "--cd", cwd,
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--model", model,
        "--output-last-message", last_msg_file,
        "-c", "sandbox_workspace_write.network_access=false",
        prompt,
    ]
    return [
        sys.executable, supervisor_path,
        "--timeout", str(int(timeout_s)),
        "--grace", "1",
        "--stdout", events_file,
        "--max-output-bytes", str(int(max_output_bytes)),
        "--",
    ] + codex_cmd


def _result(category, **extra):
    out = {"category": category if category in _CATEGORY_SET else FAIL_CLOSED_CATEGORY,
           "backend": "codex"}
    out.update(extra)
    return out


def classify_via_codex(request_text, resolved_paths=None, model=None,
                       timeout_s=CODEX_TIMEOUT_S, cwd=None, codex_bin="codex",
                       supervisor_path=None, max_output_bytes=CODEX_STDOUT_CAP,
                       config_path=None, taxonomy_categories=None, prompt=None):
    """OPTIONAL non-Claude route: run ONE read-only `codex exec` classify through the timeout
    supervisor and parse the enum reply. FAIL-CLOSED: any spawn error / non-zero exit / timeout
    / missing-or-empty reply / non-enum reply → 'unknown'. Never calls a model on the Claude
    path — this is the ONLY model-spawning path in the module, and it is opt-in."""
    import tempfile

    if prompt is None:
        prompt = build_prompt(request_text, resolved_paths, taxonomy_categories)
    if model is None:
        model = resolve_codex_light_model(config_path)
    if supervisor_path is None:
        supervisor_path = _supervisor_path()
    if cwd is None:
        cwd = os.getcwd()

    tmp = tempfile.mkdtemp(prefix="cv-a2-codex-")
    try:
        events_file = os.path.join(tmp, "events.log")
        last_msg_file = os.path.join(tmp, "last.txt")
        cmd = build_codex_command(
            prompt, model, cwd, supervisor_path, timeout_s, max_output_bytes,
            events_file, last_msg_file, codex_bin=codex_bin,
        )
        try:
            # stdin=DEVNULL here too (defense in depth); the supervisor ALSO gives its child
            # DEVNULL stdin in its own process group. Never a bare subprocess timeout on the CLI.
            proc = subprocess.run(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=_headless_env(),
            )
        except (OSError, ValueError):
            return _result(FAIL_CLOSED_CATEGORY, error="spawn_failed", model=model)

        rc = proc.returncode
        if rc == TIMEOUT_EXIT_CODE:
            return _result(FAIL_CLOSED_CATEGORY, timed_out=True, exit_code=rc, model=model)
        if rc != 0:
            return _result(FAIL_CLOSED_CATEGORY, timed_out=False, exit_code=rc, model=model)

        try:
            with open(last_msg_file, "r", encoding="utf-8", errors="replace") as fh:
                reply = fh.read()
        except OSError:
            return _result(FAIL_CLOSED_CATEGORY, timed_out=False, exit_code=rc,
                           error="no_reply", model=model)
        return _result(parse_category(reply), timed_out=False, exit_code=rc, model=model)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# =========================================================================== #
# (d) HEADLESS ONE-SHOT CLASSIFY (v3.4.1, finding 50)
#
# WHY THIS EXISTS, AND WHAT IT DOES NOT CHANGE
# --------------------------------------------
# The module header above is still true of the PIPELINE: `/v:triage` and `/v:orchestrate`
# run T3 as a parent-invoked light Task, and the engine is still T3-agnostic. What this
# section adds is the one caller that CANNOT run a Task — `hooks/triage-prompt-nudge.sh`.
# A hook is a subprocess; it has no Task tool. Until 3.4.1 that meant a `needs_t3` request
# degraded to a printed reminder asking a human to run `/v:triage`, which is the exact
# "prose enforcement wearing a hook's clothes" the native-mechanism pass exists to remove.
# A nested `claude -p` answers the same bounded prompt in ~5 s, so the hook can finish T3
# itself. Nothing else in the pipeline is obliged to use this route.
#
# THE ARGV ORDER IS LOAD-BEARING — live-probed, not reasoned about (2026-09-03).
# `claude --help` declares `--tools <tools...>`: a VARIADIC option. The spec's draft argv put
# the prompt last —
#
#     claude -p --model sonnet --output-format text --tools "" "<prompt>"
#
# — and the parser hands that prompt to `--tools` as a second tools value, leaving no prompt
# at all. Run live, that argv fails with `Error: Input must be provided either through stdin
# or as a prompt argument when using --print`. So the prompt goes IMMEDIATELY after `-p`, and
# every variadic-shaped flag comes after it. `--tools ""` still ships: it is what keeps this
# one-shot from reading or writing anything. The same probe with the corrected order returned
# `plumbing`.
#
# NEVER `--bare`. It is the flag a reader reaches for on seeing "one-shot classify, skip the
# plugins" — and it also skips the LOGIN, so a `--bare` classify fails on exactly the machines
# where it would otherwise work. Its absence is pinned by a selftest.
# =========================================================================== #
def _looks_like_haiku(model):
    """NEVER HAIKU is a project-wide rule. `scripts/lint-frontmatter.py` enforces it in
    frontmatter; nothing enforced it for a model name resolved at RUNTIME until here, and a
    machine-local `.claude/compound-v.json` can say anything. A haiku is not honoured."""
    return "haiku" in str(model or "").lower()


def resolve_claude_light_model(config_path=None):
    """Resolve the Claude `light`-tier model through `compound-v-resolve-model.py` — never a
    map recopied here, never Haiku. Fail-safe to DEFAULT_CLAUDE_LIGHT_MODEL when the resolver
    is unavailable or when what it returns is a haiku. Picks a NAME; never calls a model."""
    mod = _resolve_model_module()
    if mod is not None:
        try:
            config_models = None
            if config_path:
                try:
                    config_models = mod.load_config_models(config_path)
                except Exception:  # noqa: BLE001
                    config_models = None
            res = mod.resolve("claude", "light", config_models=config_models)
            model = res.get("model") if isinstance(res, dict) else None
            if isinstance(model, str) and model and not _looks_like_haiku(model):
                return model
        except Exception:  # noqa: BLE001
            pass
    return DEFAULT_CLAUDE_LIGHT_MODEL


def build_claude_command(prompt, model, cwd, supervisor_path, timeout_s, max_output_bytes,
                         out_file, claude_bin="claude", grace_s=HEADLESS_GRACE_S):
    """Assemble the exact argv: the timeout supervisor wrapping ONE headless `claude -p`.

    `claude_bin` is a str or a list so tests can inject a fake CLI. The prompt is the first
    positional after `-p` (see the header — `--tools` is variadic and swallows a trailing
    prompt). Output is bounded; stdin is closed by the supervisor for the whole group."""
    bin_argv = [claude_bin] if isinstance(claude_bin, str) else list(claude_bin)
    claude_cmd = bin_argv + [
        "-p", prompt,
        "--model", model,
        "--output-format", "text",
        "--tools", "",
    ]
    cmd = [
        sys.executable, supervisor_path,
        "--timeout", str(int(timeout_s)),
        "--grace", str(int(grace_s)),
        "--stdout", out_file,
        "--max-output-bytes", str(int(max_output_bytes)),
    ]
    if cwd:
        cmd += ["--cwd", cwd]
    return cmd + ["--"] + claude_cmd


def _headless_result(category, backend, timed_out=False, exit_code=None, model=None,
                     error=None):
    """The ONE result shape `--classify-headless` prints. `backend` is what actually RAN, so
    `none` means no CLI could be started at all — the caller's cue that the reminder, not a
    fail-closed `unknown`, is the honest degrade. "No classifier ran" and "the classifier
    said it cannot tell" are different claims and the hook routes them differently."""
    out = {
        "category": category if category in _CATEGORY_SET else FAIL_CLOSED_CATEGORY,
        "backend": backend,
        "timed_out": bool(timed_out),
        "exit_code": exit_code,
        "model": model,
    }
    if error:
        out["error"] = error
    return out


def classify_via_claude(request_text, resolved_paths=None, model=None,
                        timeout_s=HEADLESS_TIMEOUT_S, cwd=None, claude_bin="claude",
                        supervisor_path=None, max_output_bytes=CLAUDE_STDOUT_CAP,
                        config_path=None, taxonomy_categories=None, prompt=None):
    """Run ONE headless `claude -p` classify through the timeout supervisor and parse the
    enum. Same fail-closed contract as the codex route: spawn error / non-zero exit / timeout
    / non-enum reply → `unknown`."""
    import tempfile

    if prompt is None:
        prompt = build_prompt(request_text, resolved_paths, taxonomy_categories)
    if model is None:
        model = resolve_claude_light_model(config_path)
    if _looks_like_haiku(model):
        model = DEFAULT_CLAUDE_LIGHT_MODEL
    if supervisor_path is None:
        supervisor_path = _supervisor_path()
    if cwd is None:
        cwd = os.getcwd()

    tmp = tempfile.mkdtemp(prefix="cv-a2-claude-")
    try:
        out_file = os.path.join(tmp, "reply.txt")
        cmd = build_claude_command(prompt, model, cwd, supervisor_path, timeout_s,
                                   max_output_bytes, out_file, claude_bin=claude_bin)
        try:
            # stdin=DEVNULL here too (defense in depth); the supervisor ALSO gives its child
            # DEVNULL stdin in its own process group. Never a bare subprocess timeout.
            proc = subprocess.run(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=_headless_env(),
            )
        except (OSError, ValueError):
            return _headless_result(FAIL_CLOSED_CATEGORY, "claude", error="spawn_failed",
                                    model=model, timed_out=False, exit_code=None)

        rc = proc.returncode
        if rc == TIMEOUT_EXIT_CODE:
            return _headless_result(FAIL_CLOSED_CATEGORY, "claude", timed_out=True,
                                    exit_code=rc, model=model)
        if rc != 0:
            return _headless_result(FAIL_CLOSED_CATEGORY, "claude", timed_out=False,
                                    exit_code=rc, model=model,
                                    error=("not_found" if rc == NOT_FOUND_EXIT_CODE
                                           else "nonzero_exit"))
        try:
            with open(out_file, "r", encoding="utf-8", errors="replace") as fh:
                reply = fh.read()
        except OSError:
            return _headless_result(FAIL_CLOSED_CATEGORY, "claude", timed_out=False,
                                    exit_code=rc, error="no_reply", model=model)
        return _headless_result(parse_category(reply), "claude", timed_out=False,
                                exit_code=rc, model=model)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _resolve_bin(env_name, default_name):
    """The binary a route will run: an explicit env override (how tests plant a fake) or the
    plain name looked up on PATH. `None` when neither resolves, and the route is then SKIPPED
    rather than spawned-and-failed — which is what keeps `backend: none` meaningful.

    An env override that is SET BUT EMPTY disables the route outright. That is not a
    curiosity: it is the only way a test can assert the no-backend degrade on a developer
    machine that really does have `claude` on PATH, and the alternative — falling through to
    PATH on an empty override — is how this selftest spent a real model call the first time
    it ran. An operator gets the same switch for free."""
    import shutil

    override = os.environ.get(env_name)
    if override is not None:
        override = override.strip()
        if not override:
            return None
        if os.path.isabs(override) or os.sep in override:
            return override if os.path.exists(override) else None
        return shutil.which(override)
    return shutil.which(default_name)


def classify_headless(request_text, resolved_paths=None, timeout_s=HEADLESS_TIMEOUT_S,
                      cwd=None, config_path=None, taxonomy_categories=None, prompt=None,
                      claude_bin=None, codex_bin=None, supervisor_path=None):
    """Answer the T3 prompt with NO Task tool: Claude light first, the read-only codex route
    second, `unknown` last.

    The fallback is deliberately narrow. A claude route that TIMED OUT has already spent the
    whole budget, so starting codex behind it would push the caller past its own registration
    timeout and still produce nothing — that case returns at once. A route that could not be
    STARTED, or that failed fast, leaves budget on the clock and the second backend gets what
    is left of it."""
    import time

    if prompt is None:
        prompt = build_prompt(request_text, resolved_paths, taxonomy_categories)

    budget = max(1, int(timeout_s))
    deadline = time.monotonic() + budget
    cbin = claude_bin if claude_bin is not None else _resolve_bin(
        "CV_CLASSIFY_CLAUDE_BIN", "claude")
    xbin = codex_bin if codex_bin is not None else _resolve_bin(
        "CV_CLASSIFY_CODEX_BIN", "codex")

    last = None
    if cbin:
        last = classify_via_claude(
            request_text, resolved_paths, timeout_s=budget, cwd=cwd, claude_bin=cbin,
            config_path=config_path, prompt=prompt, supervisor_path=supervisor_path,
        )
        # The classifier REPORTED — including a literal `unknown` it chose to give. Only a
        # route that never reported at all falls through to the next backend.
        if last.get("exit_code") == 0 and not last.get("timed_out"):
            return last
        if last.get("timed_out"):
            return last

    remaining = int(deadline - time.monotonic())
    if xbin and remaining >= MIN_SECONDS_FOR_A_SECOND_BACKEND:
        res = classify_via_codex(
            request_text, resolved_paths, timeout_s=remaining, cwd=cwd, codex_bin=xbin,
            config_path=config_path, prompt=prompt, supervisor_path=supervisor_path,
        )
        return _headless_result(res.get("category"), "codex",
                                timed_out=bool(res.get("timed_out")),
                                exit_code=res.get("exit_code"), model=res.get("model"),
                                error=res.get("error"))
    if last is not None:
        return last
    return _headless_result(FAIL_CLOSED_CATEGORY, "none", timed_out=False, exit_code=None,
                            model=None, error="no_backend")


# =========================================================================== #
# CLI
# =========================================================================== #
def main(argv):
    # Locale robustness: under a C/POSIX locale (CI, minimal Docker) sys.stdout defaults to ASCII,
    # so writing the prompt text — which contains non-ASCII (em-dash etc.) — would raise
    # UnicodeEncodeError instead of emitting cleanly. Force UTF-8 on the CLI streams. (v2.9)
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if "--selftest" in argv:
        return _selftest()

    p = argparse.ArgumentParser(prog="compound-v-classify-request.py",
                                description="T3 classify: prompt builder + strict enum parser "
                                            "+ optional headless-codex route.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build-prompt", action="store_true",
                      help="emit the bounded T3 classify prompt (for the parent Task)")
    mode.add_argument("--parse", action="store_true",
                      help="parse a light-Task reply into a strict enum (stdin by default)")
    mode.add_argument("--classify-codex", action="store_true",
                      help="OPTIONAL: run the read-only codex route and parse the enum")
    mode.add_argument("--classify-headless", action="store_true",
                      help="answer the T3 prompt with no Task tool: Claude light first, the "
                           "read-only codex route second, 'unknown' last. This is the route "
                           "hooks/triage-prompt-nudge.sh takes, because a hook cannot run a "
                           "Task.")
    mode.add_argument("--selftest", action="store_true")

    p.add_argument("--request", help="the change-request text")
    p.add_argument("--path", action="append", default=[], help="a resolved file path (repeatable)")
    p.add_argument("--taxonomy-category", action="append", default=[],
                   help="a project taxonomy category hint (repeatable, context only)")
    p.add_argument("--reply", help="reply text to --parse (else --reply-file, else stdin)")
    p.add_argument("--reply-file", help="file whose contents are the reply to --parse")
    p.add_argument("stdin_marker", nargs="?", choices=["-"], default=None,
                   help="a bare '-' means read the reply from stdin (also the default)")
    p.add_argument("--model", help="codex model override (else resolved light tier)")
    p.add_argument("--timeout", type=int, default=None,
                   help="wall-clock cap (s). Default: %d for --classify-codex, %d for "
                        "--classify-headless (a hook's budget, see HEADLESS_TIMEOUT_S)."
                        % (CODEX_TIMEOUT_S, HEADLESS_TIMEOUT_S))
    p.add_argument("--cwd", help="sandbox cwd for the spawned CLI (default: current dir)")
    p.add_argument("--config", help="compound-v config JSON for model resolution")
    p.add_argument("--prompt-file",
                   help="a file whose contents ARE the classify prompt, used verbatim "
                        "instead of building one from --request/--path. This is how the "
                        "hook passes the engine's own `t3_prompt` through: the engine "
                        "already built it from the resolved paths and the taxonomy, and "
                        "rebuilding it here from a re-parsed request would be a second, "
                        "slightly different prompt for the same decision.")
    args = p.parse_args(argv)

    if args.build_prompt:
        if args.request is None:
            p.error("--build-prompt requires --request")
        sys.stdout.write(build_prompt(args.request, args.path, args.taxonomy_category or None))
        sys.stdout.write("\n")
        return 0

    if args.parse:
        if args.reply is not None:
            text = args.reply
        elif args.reply_file:
            try:
                with open(args.reply_file, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError as e:
                print("classify-request: cannot read --reply-file: %s" % e, file=sys.stderr)
                return 2
        else:
            text = "" if sys.stdin.isatty() else sys.stdin.read()
        print(json.dumps({"category": parse_category(text)}))
        return 0

    prompt_override = None
    if args.prompt_file:
        try:
            with open(args.prompt_file, "r", encoding="utf-8", errors="replace") as fh:
                prompt_override = fh.read()
        except OSError as e:
            print("classify-request: cannot read --prompt-file: %s" % e, file=sys.stderr)
            return 2
        if not prompt_override.strip():
            print("classify-request: --prompt-file is empty", file=sys.stderr)
            return 2

    if args.classify_codex:
        if args.request is None and prompt_override is None:
            p.error("--classify-codex requires --request or --prompt-file")
        res = classify_via_codex(
            args.request or "", args.path, model=args.model,
            timeout_s=(CODEX_TIMEOUT_S if args.timeout is None else args.timeout),
            cwd=args.cwd, config_path=args.config,
            taxonomy_categories=args.taxonomy_category or None,
            prompt=prompt_override,
        )
        print(json.dumps(res))
        return 0

    if args.classify_headless:
        if args.request is None and prompt_override is None:
            p.error("--classify-headless requires --request or --prompt-file")
        res = classify_headless(
            args.request or "", args.path,
            timeout_s=(HEADLESS_TIMEOUT_S if args.timeout is None else args.timeout),
            cwd=args.cwd, config_path=args.config,
            taxonomy_categories=args.taxonomy_category or None,
            prompt=prompt_override,
        )
        print(json.dumps(res))
        return 0

    p.error("no mode selected")
    return 2


# =========================================================================== #
# Self-test
# =========================================================================== #
def _selftest():
    import tempfile
    import time

    failures = []

    def expect(name, cond):
        print(("  ok   - " if cond else "  FAIL - ") + name)
        if not cond:
            failures.append(name)

    def _usage_error(argv_):
        """True when `main(argv_)` refuses with argparse's usage exit (2)."""
        try:
            devnull = open(os.devnull, "w")
            saved, sys.stderr = sys.stderr, devnull
            try:
                main(argv_)
            finally:
                sys.stderr = saved
                devnull.close()
        except SystemExit as exc:
            return exc.code == 2
        return False

    # --- (b) strict enum parser: accepts the four enums, rejects everything else --- #
    for enum in CATEGORIES:
        expect("parse exact enum: %s" % enum, parse_category(enum) == enum)
    expect("parse tolerates whitespace", parse_category("  plumbing \n") == "plumbing")
    expect("parse tolerates trailing period",
           parse_category("user-facing-major.") == "user-facing-major")
    expect("parse strips code fence + quotes",
           parse_category('```\n"user-facing-minor"\n```') == "user-facing-minor")
    expect("parse is case-insensitive on the token", parse_category("PLUMBING") == "plumbing")
    # non-enum / prose / empty -> unknown (fail-closed)
    expect("parse non-enum prose -> unknown",
           parse_category("I think this is probably plumbing, but maybe user-facing.") == "unknown")
    expect("parse empty -> unknown", parse_category("") == "unknown")
    expect("parse None -> unknown", parse_category(None) == "unknown")
    expect("parse gibberish -> unknown", parse_category("banana") == "unknown")
    expect("parse multiple enums -> unknown",
           parse_category("plumbing user-facing-major") == "unknown")
    expect("parse multi-line prose -> unknown",
           parse_category("Sure!\nplumbing") == "unknown")

    # --- (a) prompt builder: bounded, mentions every enum + the paths + fail-closed instruction --- #
    prompt = build_prompt("Make the primary button red on the pricing page",
                          ["src/ui/button.css", "src/pricing/Page.tsx"])
    expect("prompt is a str", isinstance(prompt, str))
    expect("prompt names every enum", all(e in prompt for e in CATEGORIES))
    expect("prompt includes resolved paths", "src/ui/button.css" in prompt)
    expect("prompt includes the request text", "primary button red" in prompt)
    expect("prompt is bounded (<= MAX_PROMPT_CHARS)", len(prompt) <= MAX_PROMPT_CHARS)
    # A pathological over-long request must be truncated, not passed through unbounded.
    big = build_prompt("x" * 100000, ["p/%d.ts" % i for i in range(1000)])
    expect("prompt bounds a pathological input", len(big) <= MAX_PROMPT_CHARS)
    expect("bounded prompt still carries the enum contract",
           all(e in big for e in CATEGORIES))
    # The prompt must instruct a single-token reply (so the strict parser has a chance).
    expect("prompt instructs single-token / exact reply",
           "exactly one" in prompt.lower() or "only" in prompt.lower())
    # taxonomy category hints are optional + bounded.
    ph = build_prompt("x", ["a.ts"], taxonomy_categories=["auth", "i18n_placeholder"])
    expect("prompt includes taxonomy hints when given", "i18n_placeholder" in ph)

    # --- (c) codex route through the timeout supervisor, via a FAKE codex CLI --- #
    # The fake proves: backend selection (codex exec / read-only sandbox), closed stdin,
    # bounded output, and unknown-on-error / unknown-on-timeout / unknown-on-non-enum.
    fake_src = r'''#!/usr/bin/env python3
import os, sys, time
argv = sys.argv[1:]
am = os.environ.get("FAKE_ARGV_MARK")
if am:
    open(am, "w", encoding="utf-8").write("\x00".join(argv))
sm = os.environ.get("FAKE_STDIN_MARK")
if sm:
    data = sys.stdin.buffer.read()
    open(sm, "w", encoding="utf-8").write(str(len(data)))
out = None
for i, a in enumerate(argv):
    if a == "--output-last-message" and i + 1 < len(argv):
        out = argv[i + 1]
mode = os.environ.get("FAKE_CODEX_MODE", "enum")
sys.stdout.write("E" * 8192)   # exercise the bounded output sink
sys.stdout.flush()
if mode == "slow":
    time.sleep(10)
if mode == "error":
    sys.exit(3)
reply = {"enum": "plumbing", "nonenum": "I believe this is plumbing, probably."}.get(mode, "plumbing")
if out:
    open(out, "w", encoding="utf-8").write(reply + "\n")
sys.exit(0)
'''
    tmp = tempfile.mkdtemp(prefix="cv-a2-selftest-")
    try:
        fake = os.path.join(tmp, "fakecodex.py")
        with open(fake, "w") as fh:
            fh.write(fake_src)
        os.chmod(fake, 0o755)
        argv_mark = os.path.join(tmp, "argv")
        stdin_mark = os.path.join(tmp, "stdin")
        os.environ["FAKE_ARGV_MARK"] = argv_mark
        os.environ["FAKE_STDIN_MARK"] = stdin_mark
        codex_bin = [sys.executable, fake]   # invoked as `python fakecodex.py exec ...`

        # backend selection: the constructed command carries `exec` + read-only sandbox.
        events = os.path.join(tmp, "events.log")
        last = os.path.join(tmp, "last.txt")
        cmd = build_codex_command(
            "PROMPT", "gpt-5.6-luna", tmp, _supervisor_path(), 5, 1024, events, last,
            codex_bin=codex_bin,
        )
        expect("codex cmd routes through the supervisor", _supervisor_path() in cmd)
        expect("codex cmd selects the codex backend (exec)", "exec" in cmd)
        expect("codex cmd uses a read-only sandbox", "read-only" in cmd)
        expect("codex cmd bounds output (--max-output-bytes)", "--max-output-bytes" in cmd)
        expect("codex cmd disables network",
               any("network_access=false" in str(a) for a in cmd))

        # happy path: enum reply -> plumbing; proves closed stdin + bounded output.
        os.environ["FAKE_CODEX_MODE"] = "enum"
        r = classify_via_codex("do a thing", ["src/x.ts"], model="gpt-5.6-luna",
                               cwd=tmp, codex_bin=codex_bin, timeout_s=5,
                               max_output_bytes=1024)
        expect("codex happy path -> plumbing", r["category"] == "plumbing")
        expect("codex proved closed stdin (0 bytes read)",
               os.path.exists(stdin_mark) and open(stdin_mark, encoding="utf-8").read() == "0")
        expect("codex argv recorded exec+read-only",
               os.path.exists(argv_mark)
               and "exec" in open(argv_mark, encoding="utf-8").read().split("\x00")
               and "read-only" in open(argv_mark, encoding="utf-8").read().split("\x00"))

        # output-bound proof: run the route AGAIN with an events file we own so we can size it.
        os.environ["FAKE_CODEX_MODE"] = "enum"
        events2 = os.path.join(tmp, "events2.log")
        last2 = os.path.join(tmp, "last2.txt")
        cmd2 = build_codex_command("PROMPT", "gpt-5.6-luna", tmp, _supervisor_path(),
                                   5, 1024, events2, last2, codex_bin=codex_bin)
        subprocess.run(cmd2, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        expect("codex output bounded to the cap (<=1024, fake emitted 8192)",
               os.path.exists(events2) and os.path.getsize(events2) <= 1024)

        # non-enum reply -> unknown (fail-closed)
        os.environ["FAKE_CODEX_MODE"] = "nonenum"
        r2 = classify_via_codex("do a thing", ["src/x.ts"], model="gpt-5.6-luna",
                                cwd=tmp, codex_bin=codex_bin, timeout_s=5)
        expect("codex non-enum reply -> unknown", r2["category"] == "unknown")

        # error exit -> unknown (fail-closed)
        os.environ["FAKE_CODEX_MODE"] = "error"
        r3 = classify_via_codex("do a thing", ["src/x.ts"], model="gpt-5.6-luna",
                                cwd=tmp, codex_bin=codex_bin, timeout_s=5)
        expect("codex error exit -> unknown", r3["category"] == "unknown")

        # timeout -> unknown, and returns within a fixed bound (supervisor killpg)
        os.environ["FAKE_CODEX_MODE"] = "slow"
        t0 = time.time()
        r4 = classify_via_codex("do a thing", ["src/x.ts"], model="gpt-5.6-luna",
                                cwd=tmp, codex_bin=codex_bin, timeout_s=1)
        elapsed = time.time() - t0
        expect("codex timeout -> unknown", r4["category"] == "unknown")
        expect("codex timeout flagged", r4.get("timed_out") is True)
        expect("codex timeout returns promptly (<8s)", elapsed < 8)

        # missing codex binary -> unknown (never a traceback)
        os.environ["FAKE_CODEX_MODE"] = "enum"
        r5 = classify_via_codex("do a thing", ["src/x.ts"], model="gpt-5.6-luna",
                                cwd=tmp, codex_bin="definitely-not-a-real-codex-xyz",
                                timeout_s=5)
        expect("codex missing-binary -> unknown", r5["category"] == "unknown")
    finally:
        import shutil
        for k in ("FAKE_ARGV_MARK", "FAKE_STDIN_MARK", "FAKE_CODEX_MODE"):
            os.environ.pop(k, None)
        shutil.rmtree(tmp, ignore_errors=True)

    # --- (d) the headless route: argv, model policy, backend order, fail-closed --- #
    #
    # THE ARGV IS PINNED, not merely smoke-tested. Three of its properties are the whole
    # reason this route works at all, and each of them was got wrong once:
    #   * no `--bare` (it skips the login as well as the plugins);
    #   * the prompt IMMEDIATELY after `-p`, because `--tools` is variadic and a trailing
    #     prompt is swallowed as a second tools value (live-probed 2026-09-03);
    #   * a `--model` that is never a haiku, whatever a machine-local config says.
    tmp2 = tempfile.mkdtemp(prefix="cv-a2-headless-")
    try:
        argv = build_claude_command("PROMPT-TEXT", "sonnet", tmp2, _supervisor_path(),
                                    HEADLESS_TIMEOUT_S, 1024,
                                    os.path.join(tmp2, "reply.txt"))
        expect("headless claude argv NEVER carries --bare", "--bare" not in argv)
        expect("headless claude argv is a print run (-p)", "-p" in argv)
        expect("headless claude argv puts the prompt immediately after -p",
               argv[argv.index("-p") + 1] == "PROMPT-TEXT")
        expect("headless claude argv sets --output-format text",
               "--output-format" in argv
               and argv[argv.index("--output-format") + 1] == "text")
        expect("headless claude argv disables tools (--tools \"\")",
               "--tools" in argv and argv[argv.index("--tools") + 1] == "")
        expect("headless claude argv's --tools comes AFTER the prompt (variadic swallow)",
               argv.index("--tools") > argv.index("-p") + 1)
        expect("headless claude argv routes through the supervisor",
               _supervisor_path() in argv)
        expect("headless claude argv bounds output", "--max-output-bytes" in argv)
        expect("headless claude argv carries a grace period",
               "--grace" in argv and int(argv[argv.index("--grace") + 1]) == HEADLESS_GRACE_S)
        expect("headless claude argv's cap is the hook-sized one",
               "--timeout" in argv
               and int(argv[argv.index("--timeout") + 1]) == HEADLESS_TIMEOUT_S)
        expect("headless claude model is NEVER a haiku",
               not _looks_like_haiku(argv[argv.index("--model") + 1]))
        expect("the resolved claude light model is never a haiku",
               not _looks_like_haiku(resolve_claude_light_model()))
        expect("the haiku predicate actually recognises one",
               _looks_like_haiku("claude-haiku-4-5") and not _looks_like_haiku("sonnet"))

        # A haiku that reaches classify_via_claude is swapped before the spawn.
        fake_claude = os.path.join(tmp2, "fakeclaude.py")
        with open(fake_claude, "w") as fh:
            fh.write(r'''#!/usr/bin/env python3
import os, sys, time
argv = sys.argv[1:]
am = os.environ.get("FAKE_CLAUDE_ARGV")
if am:
    open(am, "w", encoding="utf-8").write("\x00".join(argv))
sm = os.environ.get("FAKE_CLAUDE_STDIN")
if sm:
    open(sm, "w", encoding="utf-8").write(str(len(sys.stdin.buffer.read())))
mode = os.environ.get("FAKE_CLAUDE_MODE", "enum")
if mode == "slow":
    time.sleep(30)
if mode == "error":
    sys.stderr.write("boom\n")
    sys.exit(4)
sys.stdout.write({"enum": "plumbing\n",
                  "nonenum": "I would call this plumbing, probably.\n"}.get(mode, "plumbing\n"))
sys.exit(0)
''')
        os.chmod(fake_claude, 0o755)
        cbin = [sys.executable, fake_claude]
        argv_mark2 = os.path.join(tmp2, "argv")
        stdin_mark2 = os.path.join(tmp2, "stdin")
        os.environ["FAKE_CLAUDE_ARGV"] = argv_mark2
        os.environ["FAKE_CLAUDE_STDIN"] = stdin_mark2

        os.environ["FAKE_CLAUDE_MODE"] = "enum"
        r = classify_via_claude("do a thing", ["src/x.ts"], model="haiku", cwd=tmp2,
                                claude_bin=cbin, timeout_s=10)
        expect("headless claude happy path -> plumbing", r["category"] == "plumbing")
        expect("headless claude reports its backend", r["backend"] == "claude")
        expect("a haiku model is swapped before the spawn, never passed through",
               not _looks_like_haiku(r.get("model")))
        expect("headless claude proved closed stdin (0 bytes read)",
               os.path.exists(stdin_mark2)
               and open(stdin_mark2, encoding="utf-8").read() == "0")
        spawned = open(argv_mark2, encoding="utf-8").read().split("\x00")
        expect("the SPAWNED argv carried no --bare", "--bare" not in spawned)
        expect("the SPAWNED argv carried --tools \"\"",
               "--tools" in spawned and spawned[spawned.index("--tools") + 1] == "")

        os.environ["FAKE_CLAUDE_MODE"] = "nonenum"
        r2 = classify_via_claude("do a thing", ["src/x.ts"], model="sonnet", cwd=tmp2,
                                 claude_bin=cbin, timeout_s=10)
        expect("headless claude non-enum reply -> unknown", r2["category"] == "unknown")
        expect("...and it still reports as a route that RAN (exit 0)",
               r2["exit_code"] == 0 and r2["timed_out"] is False)

        os.environ["FAKE_CLAUDE_MODE"] = "slow"
        t1 = time.time()
        r3 = classify_via_claude("do a thing", ["src/x.ts"], model="sonnet", cwd=tmp2,
                                 claude_bin=cbin, timeout_s=1)
        expect("headless claude timeout -> unknown, flagged",
               r3["category"] == "unknown" and r3["timed_out"] is True)
        expect("headless claude timeout returns promptly (<10s)", time.time() - t1 < 10)

        # BACKEND ORDER. claude answers -> codex is never started (the missing codex_bin
        # would fail if it were). A claude that cannot be STARTED falls through to codex.
        os.environ["FAKE_CLAUDE_MODE"] = "enum"
        h1 = classify_headless("do a thing", ["src/x.ts"], cwd=tmp2, timeout_s=10,
                               claude_bin=cbin, codex_bin=None)
        expect("headless prefers claude when it answers", h1["backend"] == "claude")

        os.environ["FAKE_CODEX_MODE"] = "enum"
        fake_codex = os.path.join(tmp2, "fakecodex.py")
        with open(fake_codex, "w") as fh:
            fh.write(fake_src)
        os.chmod(fake_codex, 0o755)
        h2 = classify_headless("do a thing", ["src/x.ts"], cwd=tmp2, timeout_s=10,
                               claude_bin="",
                               codex_bin=[sys.executable, fake_codex])
        expect("headless falls back to codex when no claude binary resolves",
               h2["backend"] == "codex" and h2["category"] == "plumbing")

        # A claude that TIMED OUT does not then start codex: the budget is already spent.
        os.environ["FAKE_CLAUDE_MODE"] = "slow"
        t2 = time.time()
        h3 = classify_headless("do a thing", ["src/x.ts"], cwd=tmp2, timeout_s=2,
                               claude_bin=cbin, codex_bin=[sys.executable, fake_codex])
        expect("a timed-out claude does not then spend the budget on codex",
               h3["backend"] == "claude" and h3["timed_out"] is True)
        expect("...and it still returns promptly (<12s)", time.time() - t2 < 12)

        # Neither CLI available -> backend 'none'. That is NOT the same claim as a model
        # answering `unknown`, and the hook routes the two differently.
        h4 = classify_headless("do a thing", ["src/x.ts"], cwd=tmp2, timeout_s=5,
                               claude_bin="", codex_bin="")
        expect("no backend available -> backend 'none', category unknown",
               h4["backend"] == "none" and h4["category"] == "unknown")
        expect("...and it is not reported as a timeout", h4["timed_out"] is False)

        # CLI smoke through --prompt-file (how the hook passes the engine's own t3_prompt).
        pf = os.path.join(tmp2, "prompt.txt")
        with open(pf, "w", encoding="utf-8") as fh:
            fh.write("classify this\n")
        # Both routes DISABLED by an empty override. Without this the CLI smoke would run
        # whatever `claude` is on the developer's PATH and spend a real model call — which
        # is exactly what it did the first time it ran.
        os.environ["CV_CLASSIFY_CLAUDE_BIN"] = ""
        os.environ["CV_CLASSIFY_CODEX_BIN"] = ""
        expect("an empty env override disables a route rather than falling back to PATH",
               _resolve_bin("CV_CLASSIFY_CLAUDE_BIN", "claude") is None)
        expect("main --classify-headless --prompt-file exits 0",
               main(["--classify-headless", "--prompt-file", pf, "--cwd", tmp2,
                     "--timeout", "5"]) == 0)
        expect("main --classify-headless with neither request nor prompt-file is a usage error",
               _usage_error(["--classify-headless"]))
    finally:
        import shutil
        for k in ("FAKE_CLAUDE_ARGV", "FAKE_CLAUDE_STDIN", "FAKE_CLAUDE_MODE",
                  "FAKE_CODEX_MODE", "CV_CLASSIFY_CLAUDE_BIN", "CV_CLASSIFY_CODEX_BIN"):
            os.environ.pop(k, None)
        shutil.rmtree(tmp2, ignore_errors=True)

    # --- model resolution is best-effort + fail-safe (never raises) --- #
    m = resolve_codex_light_model()
    expect("resolve_codex_light_model returns a non-empty str",
           isinstance(m, str) and len(m) > 0)

    # --- CLI smoke: --parse over stdin path, --build-prompt --- #
    expect("main --parse enum", main(["--parse", "--reply", "plumbing"]) == 0)
    expect("main --build-prompt ok", main(["--build-prompt", "--request", "hi"]) == 0)

    if failures:
        print("\nSELFTEST FAILED: %d case(s)" % len(failures))
        return 1
    print("\nSELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

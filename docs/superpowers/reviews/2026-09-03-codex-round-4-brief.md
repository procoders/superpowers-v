# Adversarial cross-model review — Compound V 3.4.0, runs r8–r11 (2026-09-02/03)

You are reviewing the attached diff (context file) of a Claude Code plugin's enforcement core, written by
Claude Opus workers and reviewed by Claude Opus reviewers across seven passes. You are a different model
family; your job is to find what that family keeps missing. Read the real files in the repo (read-only) to
ground every objection.

The changes claim:
1. scripts/compound-v-scope-check.py — the git-derived scope gate keeps NO carve-outs: no bytecode exemption,
   no exemption for the pipeline's own outcome streams. (Two carve-outs were added and withdrawn after a
   forged .pyc beside the matcher was shown to execute through hooks/lane-guard.sh's loader.)
2. hooks/lane-guard.sh — picks a Python interpreter by VIABILITY (`import yaml` probe), logs which one it
   used, never reads an in-tree __pycache__ (PYTHONPYCACHEPREFIX), fails open only with a log line.
3. scripts/compound-v-integration-gate.py — the authority re-derives every receipt; the pipeline's
   bookkeeping append (merge_pending) now happens in finalize-wave AFTER the authority ran.
4. scripts/compound-v-emit-workflow.py — implementers spawn as agentType <plugin>:implementer with an
   inline-definition fallback; every emitted python command uses -B; register-lane takes a literal --cwd;
   merge-back lands staged deletions; worktrees are pruned only after the commit carrying their diff exists;
   transport prompts set a 10-minute Bash timeout.
5. agents/implementer.md — a new role with maxTurns: 60 and Anthropic's Opus 5 conciseness snippets.

Find: (a) any way a worker can get an out-of-lane write, a forged verdict, or a pruned-but-unmerged worktree
past these changes; (b) any claim in a comment/docstring that the code does not implement; (c) any
regression of an existing guarantee (fail-open contract of the Stop/PreToolUse hooks, the 1.5 s budget,
bash 3.2 portability, Python 3.9 floor); (d) plain nonsense — dead code, contradictory prose, tests that
cannot fail. Report everything in one pass, ranked, with file:line and a reproduction where you can.

# Recon — Qwen Code CLI (Alibaba) as a Compound V backend adapter (2026-08-04)

*This recon is evidence to widen the brainstorm's questions, not a conclusion to converge on. VERIFIED FACTS / CONSTRAINTS are provisionally binding (1B/1C revalidate); UNVERIFIED LEADS are questions until validated; SUGGESTED DIRECTIONS are read last (directions-late) and are some of several possibilities — generate alternatives that ignore them.*

## QUESTIONS TO ASK

- Don't assume Qwen Code is single-vendor like the `zai` adapter — it already ships auth paths for OpenAI/Anthropic/Gemini-compatible APIs, Alibaba's own Coding Plan, OpenRouter, Fireworks AI, and BYOK [F8, unverified]. Pin down *which* auth path this adapter targets before designing the model-string shape, instead of assuming a bare model name like Codex.
- Don't treat `--yolo` as a sandbox — it explicitly is not one [F4]. Ask whether the adapter requires `--sandbox`/`QWEN_SANDBOX` as a hard v1 gate, or accepts the same no-kernel-confinement lower-trust tier as Cursor/Antigravity/opencode.
- Don't reuse z.ai's credit-multiplier design for quota reasoning — the Pro Plan's exact quota numbers were only found on third-party blogs, not an Alibaba-owned page [F9, unverified]. Ask whether to gate `max_parallel` conservatively until an official source confirms.
- Don't assume `--resume <session-id>` validates as a UUID the way Codex's `session_id` does — the docs' own example is UUID-shaped but that's one example, not a stated contract [F10, unverified].
- Don't decide scope alone — ask whether the user wants a brand-new `adapter-qwen.md` (own worktree/scope-gate/failure-classification, like `zai`), or first wants to check whether the already-built `opencode` adapter can simply add an Alibaba/DashScope provider entry (reuse, not new code).

## VERIFIED FACTS / CONSTRAINTS

- [F1] Headless mode: `qwen -p "<prompt>"` runs without the interactive UI, for scripts/CI. `-o text` requests plain-text output.
- [F2] Session control: `qwen --continue -p "…"` resumes the most recent project session; `qwen --resume <session-id> -p "…"` resumes a specific one.
- [F3] Structured output: `--output-format json` returns a JSON array of message objects (system/assistant/result types); `--output-format stream-json` streams events in real time.
- [F4] `--yolo` (or `--approval-mode=yolo`) auto-approves all tool calls (shell, write, edit) but does **not** sandbox by itself — sandboxing is a separate opt-in via `--sandbox`, `QWEN_SANDBOX`, or `tools.sandbox` config. Without it, yolo-mode tools run at the host process's own privilege level.
- [F5] A stderr warning fires on headless + yolo + no-sandbox; suppressible via `QWEN_CODE_SUPPRESS_YOLO_WARNING=1`.
- [F6] Qwen Code is a fork of Google's Gemini CLI (based on v0.8.2), Apache-licensed and open source.
- [F7] Session checkpoints (history, tool outputs, compression state) are written atomically under `~/.qwen/tmp/<project_hash>/checkpoints`; `--resume` reads from there.

## UNVERIFIED LEADS

- [F8] Multiple secondary sources describe Qwen Code as provider-agnostic: Qwen-optimized workflows plus OpenAI/Anthropic/Gemini-compatible APIs, Alibaba's own "Coding Plan" subscription, OpenRouter, Fireworks AI, or BYOK. Not confirmed against QwenLM's own auth/config docs directly in this pass — verify by reading `docs/users/configuration/settings.md` and any auth doc in the primary repo.
- [F9] The Alibaba Cloud Coding Plan "Pro" tier is reported at ≈$50/month with an included request quota, aimed at day-to-day interactive use across tools including Qwen Code; a "Lite" tier is reported at ≈$10/month. Both figures are from third-party pricing roundups, not an Alibaba-owned pricing page — treat as unverified until checked against the primary source, mirroring the caution the `zai` adapter already applies to its own multiplier table.
- [F10] Whether `--resume`'s session id is guaranteed UUID-shaped (as opposed to Codex's confirmed UUID contract) is inferred from one doc example, not a stated format guarantee.
- [F11] Qwen Code reportedly ships "Skills and SubAgents" for a Claude-Code-like workflow — unclear whether this interacts with (or undermines) the planner/executor prompt lock the same way the base CLI's own tool-permission surface does; needs a direct read of that feature's docs.

## SUGGESTED DIRECTIONS

*Non-exhaustive — these are 3 of many possible framings; the brainstorm generates alternatives that ignore them.*

1. **Mirror `adapter-zai.md`, scoped to the plan being purchased.** Pin the adapter to Alibaba's own Coding Plan auth path only (the thing the user is actually paying for); treat every other Qwen Code auth path (OpenRouter/BYOK/Fireworks) as explicitly out of scope for v1.
2. **Mirror `adapter-opencode.md`'s provider-flexible shape.** Since Qwen Code's own docs already describe multiple backend auth paths, design the adapter's model field as an open string from day one instead of a single-vendor assumption — trading some of `zai`'s simplicity for not having to redesign later if BYOK/OpenRouter routing is wanted.
3. **Don't build a new adapter at all — extend `opencode`.** If opencode's own provider list can reach Alibaba/DashScope's OpenAI-compatible endpoint, add it as a provider entry there and reuse the already-built worktree, scope-gate, and env-scrub machinery instead of verifying a whole new CLI's flag set, checkpoint format, and failure-classification needles from scratch.

## SOURCES

- [F1][F2][F3] https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/ — accessed 2026-08-04 — headless `-p`, `--continue`/`--resume`, `--output-format`
- [F4][F5] https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/approval-mode.md and https://github.com/QwenLM/qwen-code/discussions/632 — accessed 2026-08-04 — yolo mode does not imply sandbox
- [F6] https://github.com/QwenLM/qwen-code — accessed 2026-08-04 — "originally based on Google Gemini CLI v0.8.2", Apache license
- [F7] https://qwenlm.github.io/qwen-code-docs/en/users/features/checkpointing/ — accessed 2026-08-04 — checkpoint path and atomic-write behavior
- [F8] https://aiagentstore.ai/compare-ai-agents/gemini-cli-vs-qwen3-coder and https://vibecodinghub.org/tools/qwen-code — accessed 2026-08-04 — provider-flexible auth claim (secondary, not primary-sourced)
- [F9] https://nerova.ai/costs-roi/qwen-cloud-coding-plan-pricing-explained-2026 and https://codingplan.run/plans/qwen-coder — accessed 2026-08-04 — Pro/Lite tier pricing claims (secondary, not primary-sourced)

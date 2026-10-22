# DESIGN.md / Design Tokens / WCAG Knowledge Base

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-06-30 — DESIGN.md extraction + WCAG lint (v:onboard audit)

### @google/design.md (verified 2026-06-30 against repo README + spec.md)
- Real, published npm package `@google/design.md`; Windows alias `designmd`. **Format version is `alpha`** — spec text says so; "components specification is actively evolving." Source: [github.com/google-labs-code/design.md](https://github.com/google-labs-code/design.md), [spec.md](https://github.com/google-labs-code/design.md/blob/main/docs/spec.md).
- **Nine lint rules**: `broken-ref`, `missing-primary`, `contrast-ratio`, `orphaned-tokens`, `token-summary`, `missing-sections`, `missing-typography`, `section-order`, `unknown-key`.
- **Contrast rule**: checks each component's `backgroundColor`/`textColor` pair against **WCAG AA 4.5:1** (normal text). Colors internally converted to sRGB. `lint` exits 1 on error, 0 otherwise.
- **Export is ONE-DIRECTIONAL: DESIGN.md → output** (`json-tailwind` v3, `css-tailwind` v4, `dtcg` W3C). **There is NO reverse extraction** — the tool does NOT parse `tailwind.config`/CSS to GENERATE a DESIGN.md. Reverse extraction is the consumer's job; the linter only validates the authored file, never the extraction's fidelity to source.

### WCAG automated-contrast limits (the linter cannot see these)
- The 4.5:1 pair check assumes **flat backgroundColor on flat textColor**. It is blind to: gradients (contrast varies pixel-to-pixel), opacity/alpha layers (effective contrast drops when blended), background images, runtime/CSS-variable theming (dark mode), and overlap by foreground elements. Sources: [accessibility-test.org](https://accessibility-test.org/blog/support/advanced-guides/color-contrast-in-wcag-2-2-testing-and-fixes-that-actually-work/), [Deque axe color-contrast](https://dequeuniversity.com/rules/axe/4.8/color-contrast).
- A DESIGN.md token file that passes `lint` does **not** prove the rendered UI is accessible; "pick colors from the live page, not the design file" is the accepted practice. → Treating `design.md lint` PASS as a WCAG-compliance guarantee is a false-assurance trap.

### Design-token extraction reliability (tailwind/CSS → tokens)
- **Tailwind v4 is CSS-first**: tokens are native CSS variables via `@theme`. **Tailwind v3**: tokens live in `tailwind.config.{js,ts}` (often a JS function / `theme.extend`, sometimes computed). Extraction must handle BOTH and cannot assume static JSON.
- **Arbitrary values** (`text-[#1a2b3c]`, `text-[var(--x)]`) live in className strings across components, NOT in config → a config-only extractor MISSES real in-use colors and over-reports unused config tokens. Sources: [Tailwind theme docs](https://tailwindcss.com/docs/theme), [tailwind discussion #18748](https://github.com/tailwindlabs/tailwindcss/discussions/18748), [Mavik Labs 2026](https://www.maviklabs.com/blog/design-tokens-tailwind-v4-2026/).
- CSS-variable indirection + runtime theming (light/dark) means a single token can resolve to multiple rendered colors — a static extractor records one. Reliability is "good signal, not ground truth"; extracted tokens need the human gate, never auto-trust.
</content>
</invoke>

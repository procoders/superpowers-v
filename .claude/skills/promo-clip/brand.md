# Design System — Am I AI-Native?

The visual language for **amiainative.dev** (ProCoders): a dark tech/SaaS surface
with gamified AI-neon energy. "California dev at night" — deep navy ground, electric
blue/violet/magenta light, big confident type, subtle motion.

Everything here is the source of truth already living in code. Tokens are defined
once in [`app/globals.css`](app/globals.css) (`@theme`) and consumed as Tailwind v4
utilities (`bg-navy`, `text-blue`, `font-mono`, ...). Fonts are wired in
[`app/[locale]/layout.tsx`](app/[locale]/layout.tsx). There is **no `tailwind.config`
file** — this is Tailwind v4, CSS-first.

---

## 1. Brand essence

| | |
|---|---|
| **Personality** | Confident, playful, technical. A game more than a form. |
| **Ground** | Always dark. `color-scheme: dark` is set globally; there is no light mode. |
| **Light** | Neon accents used as *light sources*, not fills — glow, gradient text, conic rings. |
| **Motion** | Present but calm. Ambient drift + purposeful reveals. Always honors `prefers-reduced-motion`. |
| **Type** | Large white display type; mono for anything code-flavored; pixel + comic for the Academy game. |

---

## 2. Color

Defined in `@theme` in [`app/globals.css`](app/globals.css). Use the Tailwind token
name; never hardcode hex in components.

| Token | Hex | Role |
|---|---|---|
| `navy` | `#0b0b22` | Page ground, the constant backdrop. |
| `navy-2` | `#111133` | Raised surfaces, code blocks, glass base. |
| `navy-3` | `#181842` | Deepest panel fill. |
| `blue` | `#1195f2` | Primary accent, links, the "dev" track. |
| `violet` | `#6565f2` | Secondary accent, mid-gradient, scrollbar. |
| `violet-deep` | `#4e1f90` | Ambient mesh depth only. |
| `magenta` | `#dc02df` | Peak accent, `::selection`, the "certified" tier. |
| `ink` | `#ebebee` | Primary text. |
| `slate` | `#575868` | Muted text, hairline borders, grid lines. |
| `emerald` | `#34d399` | Success / "with V" / the creator track. |

**Accent gradient** (the signature): `blue → violet → magenta`, left to right. It
drives `.text-gradient`, the `.ring-conic` border, and every OG card.

**Semantic vs brand:** `emerald` is the only "success" color and is kept separate
from the blue/violet/magenta accent trio. Track accents: dev = `blue`,
product-owner = `violet`, universal-creator = `emerald`.

---

## 3. Typography

Four families, each with a job. All loaded via `next/font/google` as CSS variables.

| Family | Variable / token | Where |
|---|---|---|
| **Manrope** | `--font-manrope` → `font-display` | Default UI + all headings. |
| **JetBrains Mono** | `--font-jetbrains` → `font-mono` | Commands, `/v:` chips, terminal, code, eyebrows. |
| **Press Start 2P** | `--font-press-start` → `font-pixel` | Academy pixel face + retro game flourishes only. |
| **Balsamiq Sans** | `--font-balsamiq` → `font-comic` | Academy comic bubbles + captions only. |

**Scale & weight:** headings are heavy (`font-weight: 800`) with tight tracking
(`letter-spacing: -0.01em` to `-2.5px` on big display). Eyebrows are mono,
uppercase, wide tracking (`letter-spacing: .14em–.24em`). Body copy targets ~65ch;
SEO prose runs `line-height: 1.75` (see `.prose-seo`).

---

## 4. Background system

Four fixed, non-interactive layers stacked behind content (all in `globals.css`).
Compose them in the layout; never re-implement per page.

- `.bg-mesh` — animated radial gradient mesh (violet-deep / blue / magenta), drifts
  over 24s (`mesh-drift`), `z-index: -2`.
- `.bg-grid` — 56px engineering grid, top-masked so it fades downward, `z-index: -2`.
- `.bg-grain` — inline SVG fractal-noise film at `opacity: 0.06`, `z-index: -1`.
- `.bg-vignette` — sinks the top corners for depth, `z-index: -1`.

---

## 5. Surface & neon utilities

Reusable classes (not one-offs). Prefer these over ad-hoc styles.

| Class | Effect |
|---|---|
| `.glass` | Translucent `navy-2` + hairline border + 12px backdrop blur. |
| `.card-raise` | Inner top-highlight + layered drop shadow. Makes a flat card feel lit. |
| `.text-gradient` | Clips the blue→violet→magenta gradient to text. |
| `.neon-text` | Soft blue/violet text glow. |
| `.glow-blue / -violet / -magenta` | Ring + colored bloom (`--shadow-glow-*`). |
| `.ring-conic` | Animated spinning conic-gradient border (uses `@property --angle`). |
| `.chip-mono` | Pill for a command/keyword: mono, uppercase, blue-tinted. |
| `.blueprint` | Faint 22px grid for framed artifacts (e.g. the hero meter). |

---

## 6. Motion

**Easing:** the house curve is `cubic-bezier(0.22, 1, 0.36, 1)` (a soft overshoot)
for reveals and hovers. Ambient loops use `ease-in-out`.

**Engine:** [`motion`](https://motion.dev) v12 (`motion/react`) for React-driven
reveals (`whileInView`, `useReducedMotion`); pure CSS keyframes for anything that
*must* always settle (comic cascade, level bars, gamification pops) so an
interrupted JS animation can never strand an element invisible.

**Reduced-motion contract (required):** every decorative animation is disabled
under `@media (prefers-reduced-motion: reduce)`. When you add a new animated class,
add it to that block in `globals.css`. Resting state must be the visible state.

Named animations already available: `mesh-drift`, `spin-angle`, `pulse-glow`
(`.animate-pulse-glow`), `float-y` (`.animate-float`), `cascade-in`, `grow-up`
(`.level-bar`), `xp-pop`, `levelup-pop`, `blink-caret`, `konami-fall`, plus the
Academy set (`academy-breathe`, `academy-face-bob`, `persona-*`, `follow-*`, `pdv-*`).

---

## 7. Component patterns

- **Persona picker** (`.persona-card` + `.group`): three "pick your hero" cards.
  Per-card accent arrives as `--accent`; hover lifts `-8px`, borders + spins the
  `.persona-aura`, fills the `.persona-cta` with the accent, and turns the avatar.
- **Level meter** (`.level-bar`): bars grow up from the baseline; L1→L7 walk the
  blue→magenta ramp.
- **Gamification**: `+XP` uses `.xp-pop`; level-ups use `.levelup-pop`; the terminal
  caret uses `.caret-blink`; the pixel walker uses `.pdv*`.
- **Zoomable art** (`.av-zoom`): hover / press-and-hold scales character art up to
  2.6x for inspection. Parent must be `overflow: visible`.

---

## 8. Open Graph cards

Shared social images. Two production paths, one look.

- **Dynamic** (`opengraph-image.tsx`, `next/og` `ImageResponse`): the result badge
  at `/compound-v/result/[uid]`. Font: `assets/fonts/Manrope-Bold.ttf`.
- **Static** (build-time): HTML card → Playwright screenshot at `1200×630`
  `deviceScaleFactor: 2` → JPEG in `public/academy/og/*.jpg`. Playwright must run
  from the project root (bare-specifier ESM resolution).

**Card rules:** `1200×630`, `navy` ground, the radial glow field + faint grid,
Manrope, a top accent bar in the page/track accent, and a footer with
`amiainative.dev/...` + a "Play free" CTA.

---

## 9. Accessibility & i18n

- Dark-only, but keep text at `ink` on `navy`-family grounds for contrast; muted
  text uses `slate` (avoid slate on navy for anything essential).
- Honor `prefers-reduced-motion` (section 6). Give interactive elements a visible
  focus state (`:focus-visible`).
- **9 UI locales**: `en, uk, sq, de, es, fr, ru, hi, pt` (`i18n/routing.ts`), all
  hreflang-linked. Long words in some locales (e.g. RU) can overflow fixed OG
  columns — scale the title by longest-word length (see the badge OG).
- **Copy**: no em-dashes or curly quotes in English UI/marketing copy. Active voice,
  a control says exactly what it does.

---

## 10. Stack

Next.js `16.2.9` (App Router) · React `19` · next-intl `4.13` · Tailwind CSS `4.3`
(CSS-first `@theme`, no config file) · motion `12.40` · Vitest `4.1`. Ground: Vercel.

**Where things live:** tokens + utilities → [`app/globals.css`](app/globals.css);
fonts → [`app/[locale]/layout.tsx`](app/[locale]/layout.tsx); Academy game →
`components/academy/*`; Compound V pages → `components/compound-v/*`; OG art →
`public/academy/og/*` + `*/opengraph-image.tsx`.

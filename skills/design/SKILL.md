---
name: design
user-invocable: false
description: Use inside a Compound V build when the change adds or changes a user interface (pages, screens, components, styles). Keeps the look consistent through the project's DESIGN.md, holds a small craft floor, and ends with a screenshot check. Skip it entirely for libraries, CLIs, APIs and other work with no user interface.
---

# Design

Load this only when the change has a user interface. It adds no questions: the brainstorm asks at most one about
identity, and only for a new project.

## 1. DESIGN.md is the one source of the look

The project's look lives in `DESIGN.md` at the repo root, in Google's open format
(<https://github.com/google-labs-code/design.md>): YAML tokens (`colors`, `typography`, `spacing`, `rounded`,
`components`) between `---` fences, then prose sections in this order: Overview, Colors, Typography, Layout,
Elevation & Depth, Shapes, Components, Do's and Don'ts. Put `DESIGN.md` in the plan's `change_set` whenever you write it.

- **It exists:** follow it. New screens use its tokens and its existing components; a new colour, font or component
  goes into `DESIGN.md` first, with its reason, never only into a stylesheet.
- **Existing UI, no DESIGN.md:** write it from what is there (CSS variables, theme config, the colours, fonts and
  spacing the pages actually repeat), exactly as it is. Do not restyle the project; record the current look.
- **New project:** write it before the first screen, from the spec's `Identity:` line and the subject itself (what a
  real business of this kind looks like, not a generic app). Where the owner left the look to you, say so in Overview.

**Components, once.** Before writing markup, list the project's existing components and partials (buttons, fields,
form rows, cards, tables, page shell, error summary) and build from them. A pattern that would appear a second time
becomes one shared component with parameters, and its first copy is replaced by it; never paste markup or a style
block from one screen into another. The `Components` section of DESIGN.md names each shared component and where it
lives.

Then run `npx @google/design.md@0.4.0 lint DESIGN.md` and fix every error (it checks the structure, token references
and WCAG AA contrast). Load the tokens into the app as CSS custom properties, so a style never hard-codes a value.

## 2. The craft floor

- The business's name and contact details on every client page, the confirmation included; the confirmation says
  what, when, with whom, and how to change or cancel it.
- One obvious primary action per screen; headings with more space above than below; body text 16 px or larger, lines
  of 45–75 characters; contrast at least 4.5:1 (3:1 for large text and controls).
- Long lists of the same choice (dates, times, items) are grouped or paged, never a wall of identical buttons.
- Fields use the right `type`, `inputmode` and `autocomplete`; errors appear beside their field (U2 in the checklist).
- Numbers that line up use tabular figures; dates and money use `Intl` in the business's locale and time zone.
- Staff and operator screens: standard controls, one clear area per job, the day's work visible without scrolling at
  1280 px, the brand's palette on the shell. Grey plus one accent is the default without the polish.
- Unless the brief asks for it, avoid the generic look: purple-to-blue gradients, glass cards, emoji as icons, a
  centred hero with three feature cards, every element in a rounded card.

## 3. The screenshot check

After the Playwright test passes, add one spec to it that saves full-page screenshots of the main screens (the first
client page, each booking or main-form step, a form error, the confirmation, the staff or admin main view) at
1280 × 800 and the client ones again at 390 × 844, into `test-results/design/` (gitignored). At most 8 images. Open them
all in one message and answer, per screen: is the most important thing obvious; does it look like this kind of
business with the name covered; is anything cramped, misaligned, cut off or scrolling sideways on the phone; does it
follow DESIGN.md. Fix what fails, rerun `live_cmd`, and look once more. Report the result in one line.

Ideas adapted from Impeccable (Apache-2.0, Paul Bakaus), Vercel's Web Interface Guidelines (MIT), Anthropic's
`frontend-design` skill (Apache-2.0) and Google's DESIGN.md (Apache-2.0).

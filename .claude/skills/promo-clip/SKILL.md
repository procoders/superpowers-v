---
name: promo-clip
description: Use when asked for a promo clip, ролик, announcement video, teaser or launch video for a product or plugin, or when a task involves Remotion.
---

# Promo clips with Remotion

## Overview

A promo clip is **a script approved on paper, then a Remotion composition reviewed one still
per scene before anything is rendered**. Both failures we hit — three invisible scenes and a
cut nobody could read — were caught by a still or by a human, never by the compiler.

Working reference, read it before writing scenes: `/Users/oleg/Dev/cv-promo/src/Promo.tsx`
(9 scenes, 1920×1080, 30 fps, `TransitionSeries`, inline styles, no CSS framework).
Script: `script-v5-final.md` · pain research + reference ad: `pains-v1.md` in the same repo.

## Workflow

1. **Script table first, no code.** One markdown table, columns `t · frames · on screen ·
   motion/sound`, plus a footer naming palette, fonts and spice level. Get an explicit
   approval on that table. Reason: rewriting a table is minutes, re-animating a scene is an hour.
2. **Scaffold, then install — the scaffold does not install.**
   ```bash
   npx create-video@latest --yes --blank --no-tailwind ~/Dev/cv-promo
   cd ~/Dev/cv-promo && npm install
   npm i @remotion/transitions@4.0.520   # EXACTLY the version of `remotion` in package.json
   ```
   Pin the transitions package to the same version as `remotion`; a drifted pair breaks types.
   `--no-tailwind` because every style here is an inline `style={{}}` object — cv-promo
   scaffolded *with* Tailwind and never used a single class.
3. **One composition, one `<Sequence>` (or `<TransitionSeries.Sequence>`) per scene.**
   Scene durations live in one object; `Root.tsx` imports `FPS` and `DURATION` from it.
4. **Review stills before any render** — one frame per scene, mid-scene, at half scale:
   ```bash
   npx remotion still Promo out/f200.png --frame=200 --scale=0.5
   ```
   Read every PNG. A full render costs minutes; a still costs seconds and shows the same bug.
5. **Render only after the stills pass.**
   ```bash
   npx remotion render Promo out/promo.mp4
   ```

## Three traps that cost us real time

### 1. `<TransitionSeries>` accepts only literal children

`<TransitionSeries>` takes `<TransitionSeries.Sequence>` and `<TransitionSeries.Transition>`
and nothing else. A wrapper component that renders a `Transition` throws at render time
(`only accepts a list of <TransitionSeries.Sequence /> and <TransitionSeries.Transition />`),
and a helper typed over a union of presentations (`fade | wipe | slide`) fails TypeScript.
**Inline every transition.** Verbose beats clever:

```tsx
<TransitionSeries.Sequence durationInFrames={SCENES.pains}><Pains /></TransitionSeries.Sequence>
<TransitionSeries.Transition presentation={wipe({ direction: "from-left" })}
  timing={springTiming({ config: { damping: 200 }, durationInFrames: T })} />
<TransitionSeries.Sequence durationInFrames={SCENES.contrast}><Contrast /></TransitionSeries.Sequence>
```

### 2. Paint order — wrap scene content in its own `<AbsoluteFill>`

An `<AbsoluteFill>` background rendered first paints **above** later static siblings:
positioned elements paint after in-flow ones, so `<Bg />` swallows the text below it. We lost
three scenes to this and only saw it in the stills. Every scene is:

```tsx
<AbsoluteFill>
  <Bg tint={BLUE} />
  <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
    {/* content — now positioned, so it paints after the background */}
  </AbsoluteFill>
</AbsoluteFill>
```
Any `position`/`transform` on the content works; a bare in-flow `<div>` does not.

### 3. Total duration is computed, never typed

Transitions overlap their neighbours, so the timeline is **shorter** than the sum of scenes:

```ts
const T = 12; // transition length, frames
const SCENES = { hook: 80, pains: 175, contrast: 65, v: 50, formula: 60,
                 powers: 155, regen: 50, end: 65, site: 56 };
export const DURATION = Object.values(SCENES).reduce((a, b) => a + b, 0)
                      - T * (Object.keys(SCENES).length - 1);
```
Hand-computing it desynchronises the audio and truncates the end card.

## Readability — the pacing the maintainer actually wants

- **~3.5 s per text screen.** A screen of six typed lines needs **~10 s** (300 frames at 30 fps).
- The shipped 22 s cut gave the six pains 175 frames (5.8 s); the maintainer could not read it
  and asked for **~35 s** total. When in doubt, slow down — nobody complains a promo was legible.
- Retiming changes `DURATION`, so the soundtrack has to be recomposed to the new length too.

## Palette — take it from the product site, never invent

Extract, don't guess: `curl -s https://amiainative.dev` and its linked CSS, then
`grep -oE '#[0-9a-fA-F]{6}' | sort | uniq -c | sort -rn`. Cross-check against in-repo art
(`docs/routing.svg`). Introducing a colour the brand does not own is a rejection.

| token | hex | use |
|---|---|---|
| NAVY / NAVY2 | `#0b0b22` / `#14143a` | background gradient |
| BLUE | `#1195F2` | early nodes, mono labels |
| INDIGO | `#6565F2` | mid nodes, glows |
| MAGENTA | `#DC02DF` | the V, strikes, the payoff |
| GOLD | `#FFC53D` | accents, the gag, "=" |
| PAPER / GREY | `#f7f7fb` / `#8c8fa8` | headline text / secondary text |

**No red anywhere** — the maintainer rejected it, including the "red stamps" that were in the
approved script v5. The script is not the last word; the maintainer is.

## The structure that worked

hook (contrast question) → pains typed out and struck through → two-line contrast beat
("Some will … / Others …", borrowed from the Neoversity reference ad in `pains-v1.md`) →
the reveal → an equation slide (Claude Code + Superpowers + V = SUPE) → feature nodes strung
along a pipeline line with exactly one gag (a rogue write bouncing off, `BLOCKED`) →
"Regenerates. (Crash? Resume.)" → end card → a clean final screen with the site URL and a motto.

One gag per clip. The pains are the hook; the gate is the promise; the URL is last.

## Music — `agy` will compose a track, but only if the prompt forbids refusal

`agy` (Antigravity CLI) has **no audio tool**. It will still deliver a produced `.wav` by
writing and running a Python synth — but only when the prompt demands a produced file *by any
means*. A prompt that politely offers an out ("say CANNOT if you cannot") gets a refusal.

```bash
python3 /Users/oleg/Dev/superpowers-v/scripts/compound-v-run-with-timeout.py \
  --timeout 900 --cwd /tmp/promo-music -- \
  agy --add-dir /tmp/promo-music --print-timeout 900s -p \
  "Produce a finished 22.000 s stereo WAV at /tmp/promo-music/promo-bg.wav by any means \
available to you, including writing and running a Python synthesiser. 120 BPM, D minor, \
dark heroic; a hard silence gap from 19.85 s to 20.00 s (power cut); a sting at 20.000 s; \
master to about -1.2 dBFS."
```

- Run it in an **isolated scratch directory** with `--add-dir` — without it the output lands in
  agy's own scratch (`~/.gemini/antigravity-cli/scratch/`), not your path.
- Always under the process-group supervisor: agy spawns children that outlive a plain `timeout`.
- Ask for **exact duration, BPM, the gap and the sting at the frame the video needs them**.
  Ours (`music/compose_promo_bg.py`, 686 lines of numpy/scipy) hits 22.000 s, gap 19.85–20.00 s,
  sting at 20.0 s — the power-cut flicker of the Regenerates scene.
- Keep a **stdlib-only placeholder WAV generator** for iteration (`music/placeholder-stdlib.wav`)
  so scene timing can be reviewed without re-running a 15-minute composition.
- Wire it as `<Audio src={staticFile("promo-bg.wav")} volume={0.8} />` with the file in `public/`.

## Brand safety (maintainer's rules)

- **No syringe, pill, vial or drug imagery** for the Compound V metaphor — use the magenta **V**
  sigil (gradient text + drop-shadow glow). This is non-negotiable, not a style preference.
- **The Boys flavour in moderation** — "spice level: medium". One wink per scene, not a parody.
- **English on screen**, whatever language the conversation is in.

## Delivery

- Send each still and each MP4 with **SendUserFile as it is produced** — do not batch them to
  the end. The maintainer's timing feedback arrived from watching v1, not from reading a summary.
- **Persist the project outside the session scratchpad** (`~/Dev/cv-promo`). Scratchpads vanish;
  the next iteration needs the composition, the script, the palette and the synth script.

## Common mistakes

| Mistake | What happens | Fix |
|---|---|---|
| Coding before the script table is approved | Scenes get re-animated | Table → approval → code |
| Wrapper component around a `Transition` | Runtime throw: "only accepts a list of…" | Inline the transitions |
| Scene content as a bare in-flow div | Text invisible, render looks "empty" | Wrap in its own `<AbsoluteFill>` |
| Hand-typed `durationInFrames` total | Audio desync, truncated end card | Compute: sum − T×(n−1) |
| Full render before stills | Minutes burned per iteration | `remotion still --scale=0.5` per scene |
| `npm i` skipped after `create-video` | `remotion: command not found` | The scaffold does not install |
| Transitions package on a different version | TypeScript errors on presentations | Pin to the `remotion` version |
| A colour picked by eye | Off-brand, rejected | Extract hexes from the live site CSS |
| Polite escape hatch in the agy music prompt | "I cannot generate audio" | Demand the file "by any means" |

## No strobes — motion the eye reads as a glitch

A per-frame or 3-frame opacity toggle ("power-cut flicker") at 30 fps reads as a rendering defect, not
an effect; the maintainer called v3's 27–30 s "twitching". The same goes for sine shakes above ~2 px.
Use ONE eased dip instead (`interpolate(frame, [0, 6, 12, 22], [1, 0.25, 0.25, 1], { easing: Easing.inOut(Easing.quad) })`),
ease every redraw (`Easing.out(Easing.cubic)`), keep sways ≤ 1.5 px and slow (`Math.sin(frame / 6)`), and
prefer `fade()` over `slide()` into a calm end card.

## Audio: never gate to digital zero

A composed "power-cut" that drops to exact silence in 100 ms and slams back with a full-scale step
(0.88 sample jump) is heard as the sound tearing — the maintainer flagged 27–28 s of v3. Check the
track with a 100 ms RMS envelope and the largest sample-to-sample jump around every hard cut
(`/usr/bin/python3` has numpy). Fix in post: an eased fade-out of ≥150 ms, a quiet low-passed bed
(≈−16 dB, one bar looped through a ~600 Hz one-pole) instead of zeros, and a 25–30 ms cosine fade-in
on the return — the punch stays, the click goes. Ask the composer for the same up front.

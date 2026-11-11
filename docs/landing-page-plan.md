# Landing page + app UI: design plan and status (work in progress)

Brief: a landing page that sells EchoLabs and tells, while scrolling, how it works. Inspired by https://os.yash0.in/ (kinetic display type, scroll-told story, marquee, giant footer wordmark), but with its own identity. Then restyle the Gradio app to match. Design guidance: Anthropic `frontend-design` skill (installed globally).

## Design tokens

| Token | Value | Meaning |
|---|---|---|
| `--ink` (background) | `#12193A` deep studio ultramarine | not near-black, which is the reference's (and the template default's) look |
| `--text` | `#EDEBF5` | |
| `--muted` | `#9BA3C7` | |
| `--vocals` | `#FF7A93` coral | stem colour, used **only** to mean vocals |
| `--drums` | `#F5B841` amber | stem colour: drums |
| `--bass` | `#3FD0B0` teal | stem colour: bass |
| `--other` | `#9C8CFF` periwinkle | stem colour: other instruments |

- **Type:** one family, Bricolage Grotesque (Google Fonts, variable `opsz 12..96, wdth 75..100, wght 200..800`). Condensed and heavy for the kinetic headline, opsz 14 for body text. Tabular figures for numbers.
- **Avoid:**
  - monospace data labels
  - all-caps eyebrow labels
  - one accented word in a headline
  - `→` in buttons
  - fade-up on every section
  - identical rounded cards
- **Numbering:** only the five pipeline steps get numbers, because they are a real sequence.

## Page structure

1. **Nav:** wordmark, then Listen, How it works, Results, Run it, GitHub.
2. **Hero:**
   - Kinetic headline: "Lift the vocals / from one song. / Drop them on another." (one orchestrated load animation).
   - Subline.
   - A **live player**, which is the characteristic thing in the hero:
     - pair tabs for the two directions;
     - an EchoLabs vs Naive-overlay switch that keeps the playhead position;
     - a canvas waveform from `clips.json` peaks, with a "vocals in" marker;
     - chips showing BPM, keys, shift, stretch and key relation.
3. **Marquee** of real facts. CSS only; paused under reduced motion.
4. **How it works:** pinned scroll scene in SVG, built from **real data** in `site/data/story.json`. Steps:
   1. **Separate:** the mixture waveform splits into 4 coloured stem lanes.
   2. **Analyse:** the beat grid draws in (downbeats heavier); tempo and key badges.
   3. **Match:** a Camelot wheel with 6A and 9A highlighted; a −3 semitone arc; 140.0 → 141.9 BPM.
   4. **Beat-warp:** A's drums, bass and other fade out, and B's lanes appear. The vocals waveform is piecewise-warped: `x(t) = lerp(t, mapped(t), p)` using `warp.a` → `warp.out`. A row of 16 per-beat stretch bars (×0.93–×1.12) sits beside the single global ×1.013.
   5. **Mix and credit:** the lanes merge, and a provenance "receipt" built from the real manifest JSON appears.

   Scroll mechanics: the section is about 500vh with a sticky 100vh stage, and progress maps to (step, local p). Under reduced motion, steps snap with no interpolation.
5. **Results** as comparisons, not big-number cards. All values come from `site/data/numbers.json`:
   - vocal separation, 9.06 vs 1.81 dB;
   - beat F-measure: naive 0.365, global 0.525, beat-warp 0.591, with a ceiling marker at 0.706;
   - key clashes, 89% → 34%;
   - key detection 0.588 vs about 0.74 for learned models;
   - "What didn't work": Beat This! 0.518.
6. **Responsible by design:** a provenance receipt, CC BY credits, and the rights checkbox.
7. **Run it:** Colab button and CLI snippet.
8. **Footer:** giant wordmark, credits, GitHub, "Built by Willis Kipgen".

## Status

- [x] Picked and reviewed the design skill (`anthropics/skills@frontend-design`) and studied the reference site.
- [x] `scripts/build_site.py` now emits only data and audio: `site/audio/*`, `site/data/{clips,story,numbers}.json`.
- [x] Removed the old generated `site/index.html`. **The live GitHub Pages site still serves the previous page from `main` until this branch merges.**
- [ ] Hand-write `site/index.html`, `site/styles.css`, `site/main.js` following the plan above.
- [ ] Self-critique with screenshots at desktop and 375 px, in both colour schemes and with reduced motion.
- [ ] Restyle the Gradio app (`space/app.py`) using the same tokens:
  - `gr.themes.Base` with Bricolage Grotesque;
  - "deck" panels for song A (vocals) and song B (instrumental);
  - a result card with chips;
  - `gr.WaveformOptions` in the stem colours.
- [ ] One PR per part (landing page, app UI), each merged only after green CI.

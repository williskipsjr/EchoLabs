# EchoLabs: stem-aware AI mashup engine

Give EchoLabs two songs. It separates them into stems, works out their tempo, beat grid and key, decides how one has to be stretched and transposed to fit the other, and renders **song A's vocals over song B's instrumental**, locked to B's beats.

```
song A ─┐                     ┌─ tempo, beats, downbeat ─┐
        ├─ Demucs separation ─┤                          ├─ match ─ beat-warp + transpose ─ mix ─ remix.wav
song B ─┘   (htdemucs)        └─ key (chroma × profiles) ┘  (stretch, semitones,                 + provenance.json
                                                              Camelot relation, score)
```

| Stage | What it does | Module |
|---|---|---|
| Separate | Hybrid Transformer Demucs splits each song into vocals / drums / bass / other; stems cached by file hash | `separate.py` |
| Analyse | Beats tracked on the **drum stem only**, tempo from a least-squares fit of the beat grid, downbeat phase from low-frequency onset energy, key from energy-weighted chroma correlated with 24 rotated key profiles on **bass + other** (no drums) | `analyze.py` |
| Match | Half/double-time detection, stretch factor, smallest transposition that lands on a compatible Camelot key, and a 0–1 mashup-difficulty score used to rank every pairing in a library | `match.py` |
| Remix | **Beat-warp**: every beat interval of A is stretched onto the matching beat interval of B (time-varying Rubber Band stretch), so A follows B's tempo drift; vocal chain (high-pass, light reverb), mid-range ducking of B while A sings, LUFS loudness matching, limiter | `remix.py` |
| Provenance | Every render writes a JSON manifest: source files and hashes, analysis, every transformation applied, and an explicit *AI-generated derivative* flag | `cli.py` |

## Results

Benchmarks are running; numbers land here as they finish:

- **Separation**: SDR on the MUSDB18 test clips, htdemucs vs the REPET-SIM baseline vs an oracle ideal-ratio-mask upper bound
- **Sync ablation**: beat F-measure, beat offset and key-clash rate over 100 random song pairs for naive / global / beatwarp sync
- **Key detection**: MIREX weighted score on GiantSteps Key (566 human-labelled tracks), full mix vs harmonic-only, two key profiles

## Usage

```bash
uv sync
uv run remixlab analyze song.mp3
uv run remixlab rank my_songs/ --top 10
uv run remixlab mashup vocals_song.mp3 beat_song.mp3 -o outputs/mashup.wav --mode beatwarp
```

Reproduce the evaluations:

```bash
uv run python -m remixlab.evaluation.separation   # MUSDB18 sample downloads automatically (~140 MB)
uv run python -m remixlab.evaluation.sync --pairs 100
uv run python -m remixlab.evaluation.key          # needs GiantSteps Key (see below)
uv run pytest
```

GiantSteps Key: `uv run python -c "import mirdata; mirdata.initialize('giantsteps_key', data_home='data/giantsteps_key').download(partial_download=['audio','keys'])"`

Everything runs on a CPU; no GPU was used.

## Using music responsibly

Remixing someone else's recording is creative work built on theirs. RemixLab is a research tool: use it on music you own, music released for remixing (e.g. Creative Commons stems and a cappellas on ccMixter), or research datasets. Every output carries a provenance manifest naming its sources so the original artists can be credited.

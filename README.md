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

All numbers come from the scripts in `src/echolabs/evaluation/`; raw per-track results are in [`results/`](results/). Everything ran on a laptop CPU.

### 1. Source separation (MUSDB18, 50 test clips)

SDR in dB (BSSEval v4; median over 1 s frames, then over tracks). Higher is better.

| System | Vocals | Drums | Bass | Other | Accompaniment |
|---|---|---|---|---|---|
| **htdemucs** (used by EchoLabs) | **9.06** | **9.46** | **9.45** | 5.69 | **13.70** |
| REPET-SIM (classic DSP baseline) | 1.81 | – | – | – | 4.63 |
| Oracle ideal ratio mask (STFT 4096) | 10.74 | 9.08 | 7.70 | 7.64 | – |

- Demucs beats the classic repetition-based separator by **+7.3 dB on vocals** and **+9.1 dB on accompaniment**.
- It even beats the oracle *mask* on drums and bass. The oracle can only re-weight the mixture's spectrogram at a fixed frequency resolution, while Demucs also works in the waveform domain. So the oracle is an upper bound for spectrogram-masking methods only, not for every separator.
- Separation ran at 0.82× real time on CPU.
- Caveat: these are the 7 s MUSDB18 preview clips, not full songs, so the numbers are not directly comparable to the full-track figures in the Demucs paper.

### 2. Key detection (GiantSteps Key, 566 human-labelled EDM tracks)

MIREX weighted score: 1 for the exact key, 0.5 for a perfect fifth, 0.3 for the relative key, 0.2 for the parallel major/minor key.

| Input | Key profile | MIREX weighted | Exact |
|---|---|---|---|
| Full mix | Krumhansl–Kessler | 0.571 | 49.8% |
| Full mix | Temperley | 0.416 | 33.4% |
| Harmonic only (HPSS) | **Krumhansl–Kessler** | **0.588** | **51.1%** |
| Harmonic only (HPSS) | Temperley | 0.456 | 37.5% |

Paired bootstrap over tracks (10,000 resamples):

- **Krumhansl beats Temperley**: +0.133 [95% CI +0.098, +0.167].
- **Removing percussion helps Temperley**: +0.040 [+0.016, +0.064].
- **For Krumhansl, the +0.017 gain is within noise**: CI [−0.006, +0.041]. This is the profile EchoLabs uses, so the "drums out" choice is not shown to matter for it.

In the best configuration, 23% of errors land on an unrelated key and 14% confuse major with minor. Learned key classifiers reach about 0.74 on this dataset, so this template method is a baseline, not the state of the art.

Labels with mode qualifiers (e.g. "F minor aeolian") are reduced to major/minor. The 34 tracks labelled "other" or with no key are excluded.

### 3. Sync ablation (100 random song pairs from MUSDB18)

For each pair, song A's drum stem is warped with exactly the plan used for its vocals. Its beats are then re-detected and scored against song B's beats: beat F-measure at ±70 ms, with a fixed librosa-based judge. Ground-truth stems are used here so that separation errors don't confound the sync result. Pairs were filtered to tempo gaps a DJ would plausibly mix, i.e. a stretch factor between 0.85 and 1.18.

| Beat tracker | Naive overlay | Global stretch | **Beat-warp** | Self-warp ceiling |
|---|---|---|---|---|
| librosa (default) | 0.365 | 0.525 | **0.591** | 0.706 |
| Beat This! (neural, optional) | 0.326 | 0.480 | 0.518 | 0.709 |

Key-clash rate (Camelot), measured on the warped audio: **89% for the naive overlay → 34% with transposition**.

What the numbers support (paired bootstrap, 95% CI):

- **Global stretch beats naive overlay**: +0.160 [+0.106, +0.212].
- **Beat-warp beats global stretch**: +0.066 [+0.019, +0.114]. Following every beat interval pays off over one constant tempo ratio.
- **The neural tracker did not help**: librosa beat-warp minus Beat This! beat-warp is +0.073 [−0.004, +0.153]. On these 7 s clips the two trackers agree on tempo within 3% for only 52% of pairs. Part of the gap may also come from the judge being librosa-based. Beat This! therefore stays an optional extra (`uv sync --extra neural`).

The **self-warp ceiling** is a song warped onto itself, where the ideal answer is "change nothing". It shows the judge itself is noisy on 7 s clips, at about 0.71. Read every score against that ceiling rather than against 1.0.

On a synthetic click track with known ground truth (`tests/test_pipeline.py`), beat-warp lands each click 11–15 ms from its target, and the test asserts a mean offset under 20 ms. That is below the ~20 ms threshold where two hits start to sound like a "flam". The Rubber Band stretcher itself adds under 5 ms.

## Usage

```bash
uv sync
uv run echolabs analyze song.mp3
uv run echolabs rank my_songs/ --top 10
uv run echolabs mashup vocals_song.mp3 beat_song.mp3 -o outputs/mashup.wav --mode beatwarp
```

Reproduce the evaluations:

```bash
uv run python -m echolabs.evaluation.separation   # MUSDB18 sample downloads automatically (~140 MB)
uv run python -m echolabs.evaluation.sync --pairs 100
uv run python -m echolabs.evaluation.key          # needs GiantSteps Key (see below)
uv run pytest
```

GiantSteps Key: `uv run python -c "import mirdata; mirdata.initialize('giantsteps_key', data_home='data/giantsteps_key').download(partial_download=['audio','keys'])"`

Everything runs on a CPU; no GPU was used.

## Using music responsibly

Remixing someone else's recording is creative work built on theirs. EchoLabs is a research tool: use it on music you own, music released for remixing (e.g. Creative Commons stems and a cappellas on ccMixter), or research datasets. Every output carries a provenance manifest naming its sources so the original artists can be credited.

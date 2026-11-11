"""Benchmark source separation on the MUSDB18 test split (BSSEval v4 SDR).

Three systems are compared on the same clips:
  * htdemucs   - the deep model RemixLab uses
  * repet_sim  - classic signal-processing baseline (vocals / accompaniment only)
  * oracle_irm - ideal ratio mask computed from the true stems: an upper bound
                 for any mask-based separator, not a real system

Reported number per target: median over frames per track, then median over
tracks (the convention used in SiSEC / MUSDB papers).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import librosa
import musdb
import museval
import numpy as np
from tqdm import tqdm

from .. import separate

TARGETS = ("vocals", "drums", "bass", "other")
N_FFT, HOP = 4096, 1024


def _stft(x: np.ndarray) -> np.ndarray:
    return librosa.stft(x, n_fft=N_FFT, hop_length=HOP)


def _istft(X: np.ndarray, length: int) -> np.ndarray:
    return librosa.istft(X, hop_length=HOP, length=length)


def repet_sim(mix: np.ndarray, sr: int = 44100) -> dict[str, np.ndarray]:
    """REPET-SIM (Rafii & Pardo 2012): the accompaniment repeats, the voice doesn't.

    Each frame's repeating part is the median of its most similar frames; what
    is left over is treated as vocals.
    """
    X = _stft(mix)
    mono = np.abs(X).mean(axis=0)
    width = int(librosa.time_to_frames(1.0, sr=sr, hop_length=HOP))
    rep = librosa.decompose.nn_filter(mono, aggregate=np.median, metric="cosine", width=width)
    rep = np.minimum(mono, rep)
    mask_v = librosa.util.softmask(mono - rep, 2 * rep, power=2)
    mask_a = librosa.util.softmask(rep, mono - rep, power=2)
    n = mix.shape[-1]
    return {"vocals": _istft(X * mask_v, n), "accompaniment": _istft(X * mask_a, n)}


def oracle_irm(refs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Ideal ratio mask from the ground-truth stems (upper bound)."""
    specs = {k: _stft(v) for k, v in refs.items()}
    mix = sum(specs.values())
    power = {k: np.abs(v) ** 2 for k, v in specs.items()}
    total = sum(power.values()) + 1e-10
    n = next(iter(refs.values())).shape[-1]
    return {k: _istft(mix * power[k] / total, n) for k in refs}


def _sdr(refs: dict[str, np.ndarray], ests: dict[str, np.ndarray]) -> dict[str, float]:
    names = list(ests)
    R = np.stack([refs[k].T for k in names])
    E = np.stack([ests[k].T for k in names])
    sdr, *_ = museval.evaluate(R, E, win=44100, hop=44100)
    return {k: float(np.nanmedian(sdr[i])) for i, k in enumerate(names)}


def run(root: str, limit: int | None, out: Path) -> dict:
    db = musdb.DB(root=root, subsets="test")
    tracks = db.tracks[:limit] if limit else db.tracks
    per_track, sep_seconds, audio_seconds = [], 0.0, 0.0
    separate.get_model()  # load once so model start-up isn't counted as separation time

    for t in tqdm(tracks, desc="tracks"):
        mix = t.audio.T.astype(np.float32)
        refs = {k: t.targets[k].audio.T.astype(np.float32) for k in TARGETS}
        refs_va = {"vocals": refs["vocals"], "accompaniment": refs["drums"] + refs["bass"] + refs["other"]}

        t0 = time.perf_counter()
        demucs = separate.separate_array(mix)
        sep_seconds += time.perf_counter() - t0
        audio_seconds += mix.shape[-1] / t.rate

        row = {"track": t.name}
        for system, refs_, ests in (
            ("htdemucs", refs, demucs),
            ("htdemucs", refs_va, {"accompaniment": separate.instrumental(demucs)}),
            ("repet_sim", refs_va, repet_sim(mix)),
            ("oracle_irm", refs, oracle_irm(refs)),
        ):
            for k, v in _sdr(refs_, ests).items():
                row[f"{system}/{k}"] = v
        per_track.append(row)

    keys = sorted({k for r in per_track for k in r if k != "track"})
    summary = {k: round(float(np.nanmedian([r[k] for r in per_track if k in r])), 2) for k in keys}
    result = {
        "dataset": "MUSDB18 (7 s sample), test split",
        "n_tracks": len(per_track),
        "metric": "SDR in dB (BSSEval v4), median over frames then tracks",
        "median_sdr_db": summary,
        "htdemucs_realtime_factor_cpu": round(audio_seconds / sep_seconds, 2),
        "per_track": per_track,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default="data/musdb18_sample")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out", type=Path, default=Path("results/separation.json"))
    args = p.parse_args()
    r = run(args.root, args.limit, args.out)
    print(json.dumps({k: v for k, v in r.items() if k != "per_track"}, indent=2))


if __name__ == "__main__":
    main()

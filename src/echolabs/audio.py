"""Audio I/O helpers. All audio inside EchoLabs is float32, shape (channels, samples)."""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import pyloudnorm
import soundfile as sf

SR = 44100  # Demucs works at 44.1 kHz, so everything else does too.


def load(path: str | Path, sr: int = SR) -> np.ndarray:
    """Load any format ffmpeg/libsndfile can read as stereo float32 at `sr`."""
    y, _ = librosa.load(str(path), sr=sr, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y])
    return y.astype(np.float32)


def save(path: str | Path, audio: np.ndarray, sr: int = SR) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio.T, sr, subtype="PCM_16")


def to_mono(audio: np.ndarray) -> np.ndarray:
    return audio.mean(axis=0) if audio.ndim == 2 else audio


def loudness(audio: np.ndarray, sr: int = SR) -> float:
    """Integrated loudness in LUFS (ITU-R BS.1770). -inf for silence."""
    meter = pyloudnorm.Meter(sr)
    # The meter needs at least one 400 ms block.
    if audio.shape[-1] < int(0.4 * sr):
        return float("-inf")
    return float(meter.integrated_loudness(audio.T))


def set_loudness(audio: np.ndarray, target_lufs: float, sr: int = SR) -> np.ndarray:
    current = loudness(audio, sr)
    if not np.isfinite(current):
        return audio
    gain = 10 ** ((target_lufs - current) / 20)
    return (audio * gain).astype(np.float32)


def fade(audio: np.ndarray, sr: int = SR, fade_in: float = 0.05, fade_out: float = 1.0) -> np.ndarray:
    out = audio.copy()
    n_in, n_out = int(fade_in * sr), int(fade_out * sr)
    n_in, n_out = min(n_in, out.shape[-1]), min(n_out, out.shape[-1])
    if n_in:
        out[..., :n_in] *= np.linspace(0, 1, n_in, dtype=np.float32)
    if n_out:
        out[..., -n_out:] *= np.linspace(1, 0, n_out, dtype=np.float32)
    return out

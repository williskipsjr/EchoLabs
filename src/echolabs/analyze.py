"""Musical analysis: tempo, beat grid, downbeat phase and key.

Working on separated stems instead of the full mix is the main idea here:
beats are tracked on the drum stem (no vocals or pads smearing the onsets) and
key is estimated on bass + other (no drums adding noise to the chroma).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache

import librosa
import numpy as np

from . import audio as A

TRACKERS = ("beatthis", "librosa")

PITCHES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# Key profiles: how strongly each scale degree is expected in a major / minor key.
PROFILES = {
    # Krumhansl & Kessler (1982), from listener probe-tone ratings.
    "krumhansl": (
        [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
        [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    ),
    # Temperley (1999), revised for corpus statistics.
    "temperley": (
        [5.0, 2.0, 3.5, 2.0, 4.5, 4.0, 2.0, 4.5, 2.0, 3.5, 1.5, 4.0],
        [5.0, 2.0, 3.5, 4.5, 2.0, 4.0, 2.0, 4.5, 3.5, 2.0, 1.5, 4.0],
    ),
}


@dataclass
class Key:
    tonic: int  # pitch class, 0 = C
    mode: str  # "major" | "minor"
    confidence: float  # correlation gap between best and runner-up key

    @property
    def name(self) -> str:
        return f"{PITCHES[self.tonic]} {self.mode}"

    @property
    def camelot(self) -> str:
        return camelot(self.tonic, self.mode)


@dataclass
class Analysis:
    tempo: float  # BPM
    beats: np.ndarray  # beat times in seconds
    downbeat_phase: int  # index of the first beat that starts a bar (0-3)
    key: Key
    duration: float

    def summary(self) -> dict:
        return {
            "tempo_bpm": round(self.tempo, 2),
            "n_beats": len(self.beats),
            "downbeat_phase": self.downbeat_phase,
            "key": self.key.name,
            "camelot": self.key.camelot,
            "key_confidence": round(self.key.confidence, 3),
            "duration_s": round(self.duration, 2),
        }


def camelot(tonic: int, mode: str) -> str:
    """Camelot wheel code used by DJs: adjacent numbers are harmonically compatible."""
    relative_major = tonic if mode == "major" else (tonic + 3) % 12
    number = (7 * relative_major + 8) % 12 or 12
    return f"{number}{'B' if mode == 'major' else 'A'}"


def estimate_key(harmonic: np.ndarray, sr: int = A.SR, profile: str = "krumhansl") -> Key:
    """Correlate the average chroma vector against all 24 rotated key profiles."""
    y = librosa.resample(A.to_mono(harmonic), orig_sr=sr, target_sr=22050)
    chroma = librosa.feature.chroma_cqt(y=y, sr=22050, bins_per_octave=36)
    # Weight frames by energy so silent / noisy frames don't vote.
    weights = chroma.sum(axis=0)
    mean = (chroma * weights).sum(axis=1) / (weights.sum() + 1e-9)

    major, minor = (np.asarray(p) for p in PROFILES[profile])
    scores = []
    for mode, prof in (("major", major), ("minor", minor)):
        for tonic in range(12):
            r = np.corrcoef(mean, np.roll(prof, tonic))[0, 1]
            scores.append((r, tonic, mode))
    scores.sort(reverse=True)
    (best, tonic, mode), (second, *_) = scores[0], scores[1]
    return Key(tonic, mode, float(best - second))


def track_beats(drums: np.ndarray, sr: int = A.SR, start_bpm: float = 120.0, hop: int = 256) -> tuple[float, np.ndarray]:
    y = librosa.resample(A.to_mono(drums), orig_sr=sr, target_sr=22050)
    onset_env = librosa.onset.onset_strength(y=y, sr=22050, hop_length=hop, aggregate=np.median)
    tempo, frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=22050, hop_length=hop, start_bpm=start_bpm, units="frames"
    )
    beats = librosa.frames_to_time(frames, sr=22050, hop_length=hop)
    return _tempo_from_beats(beats, fallback=float(np.atleast_1d(tempo)[0])), beats


def _tempo_from_beats(beats: np.ndarray, fallback: float = 120.0) -> float:
    """Tempo = slope of a straight line through the beat times.

    Individual beat times are quantised to the analysis hop; the fit averages
    that error away (a median inter-beat interval at hop 512 was off by ~2% at 120 BPM).
    """
    if len(beats) > 3:
        return 60.0 / float(np.polyfit(np.arange(len(beats)), beats, 1)[0])
    return fallback


@lru_cache(maxsize=1)
def _beat_this():
    try:
        from beat_this.inference import Audio2Beats
    except ImportError as e:
        raise ImportError("tracker='beatthis' needs the neural extra: uv sync --extra neural") from e

    return Audio2Beats(checkpoint_path="final0", device="cpu", dbn=False)


def track_beats_neural(mix: np.ndarray, sr: int = A.SR) -> tuple[float, np.ndarray, np.ndarray]:
    """Beats and downbeats from Beat This! (Foscarin et al., ISMIR 2024).

    Run it on the full mix: it was trained on mixtures, and on an isolated
    drum stem it tends to lock onto double tempo.
    """
    beats, downbeats = _beat_this()(A.to_mono(mix), sr)
    beats, downbeats = np.asarray(beats, dtype=float), np.asarray(downbeats, dtype=float)
    return _tempo_from_beats(beats), beats, downbeats


def _phase_from_downbeats(beats: np.ndarray, downbeats: np.ndarray, tol: float = 0.07) -> int | None:
    """Index (mod 4) of the first beat that the model also marked as a downbeat."""
    for i, t in enumerate(beats):
        if len(downbeats) and np.min(np.abs(downbeats - t)) < tol:
            return i % 4
    return None


def downbeat_phase(beats: np.ndarray, low_end: np.ndarray, sr: int = A.SR) -> int:
    """Guess which of every 4 beats is the downbeat.

    Heuristic: bass notes and kick drums land on the "one" more than anywhere
    else, so pick the phase whose beats carry the most low-frequency onset energy.
    """
    if len(beats) < 8:
        return 0
    y = librosa.resample(A.to_mono(low_end), orig_sr=sr, target_sr=22050)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=22050, n_fft=2048)
    low = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[freqs < 150]), sr=22050)
    idx = np.clip(librosa.time_to_frames(beats, sr=22050, hop_length=512), 0, len(low) - 1)
    strength = low[idx]
    return int(np.argmax([strength[p::4].mean() for p in range(4)]))


def analyze_stems(
    stems: dict[str, np.ndarray], sr: int = A.SR, key_profile: str = "krumhansl", tracker: str = "librosa"
) -> Analysis:
    if tracker not in TRACKERS:
        raise ValueError(f"tracker must be one of {TRACKERS}")
    phase = None
    if tracker == "beatthis":
        tempo, beats, downbeats = track_beats_neural(sum(stems.values()), sr)
        phase = _phase_from_downbeats(beats, downbeats)
    if tracker == "librosa" or len(beats) < 4:
        tempo, beats = track_beats(stems["drums"], sr)
    if phase is None:
        phase = downbeat_phase(beats, stems["drums"] + stems["bass"], sr)
    key = estimate_key(stems["bass"] + stems["other"], sr, key_profile)
    return Analysis(tempo, beats, phase, key, stems["drums"].shape[-1] / sr)


def key_to_dict(key: Key) -> dict:
    return asdict(key) | {"name": key.name, "camelot": key.camelot}

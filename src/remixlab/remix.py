"""Render a mashup: song A's vocals over song B's instrumental.

Three sync modes (compared in `evaluation/sync.py`):
  * naive    - line up the first downbeats, no stretching
  * global   - one constant stretch factor from the two tempo estimates
  * beatwarp - every beat interval of A is stretched onto the matching beat
               interval of B, so A follows B's tempo drift exactly
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pedalboard as pb

from . import audio as A
from .analyze import Analysis
from .match import Match

MODES = ("naive", "global", "beatwarp")


@dataclass
class Plan:
    a_start: float  # where the vocal segment starts in A (s)
    a_end: float  # where it ends in A (s)
    out_start: float  # where it lands in the output (s)
    out_len: int  # output length in samples (= length of B)
    knots_a: np.ndarray  # A-time breakpoints of the warp (s)
    knots_out: np.ndarray  # matching output-time breakpoints (s)
    semitones: int
    mode: str

    def summary(self) -> dict:
        return {
            "mode": self.mode,
            "a_segment_s": [round(self.a_start, 2), round(self.a_end, 2)],
            "vocals_enter_at_s": round(self.out_start, 2),
            "semitones": self.semitones,
            "n_warp_segments": len(self.knots_a) - 1,
        }


def effective_beats(ana: Analysis, multiplier: float) -> tuple[np.ndarray, int]:
    """A's beat grid re-expressed at the tempo it will be matched at (half/double time)."""
    beats, phase = ana.beats, ana.downbeat_phase
    if multiplier == 2.0 and len(beats) > 1:
        mids = (beats[:-1] + beats[1:]) / 2
        grid = np.empty(len(beats) + len(mids))
        grid[0::2], grid[1::2] = beats, mids
        return grid, (2 * phase) % 4
    if multiplier == 0.5:
        return beats[phase % 2 :: 2], (phase // 2) % 4
    return beats, phase


def vocal_onset(vocals: np.ndarray, sr: int = A.SR, floor_db: float = -35.0) -> float:
    """First moment the separated vocal is clearly audible."""
    mono = A.to_mono(vocals)
    hop = int(0.05 * sr)
    n = len(mono) // hop
    if n == 0:
        return 0.0
    rms = np.sqrt((mono[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms / (rms.max() + 1e-12))
    active = np.flatnonzero(db > floor_db)
    return float(active[0] * hop / sr) if len(active) else 0.0


def _downbeats(beats: np.ndarray, phase: int) -> np.ndarray:
    return np.arange(phase, len(beats), 4)


def make_plan(a_vocals: np.ndarray, a: Analysis, b: Analysis, m: Match, mode: str = "beatwarp", intro_bars: int = 1) -> Plan:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    ga, pa = effective_beats(a, m.tempo_multiplier)
    gb, pb_ = b.beats, b.downbeat_phase
    out_len = int(round(b.duration * A.SR))
    if len(ga) < 2 or len(gb) < 2:
        raise ValueError("not enough beats detected to align these songs")

    # A: the downbeat at (or just before) the moment the singing starts.
    onset = vocal_onset(a_vocals)
    da = _downbeats(ga, pa)
    before = da[ga[da] <= onset + 0.05]
    ia = int(before[-1]) if len(before) else int(da[0]) if len(da) else 0

    # Keep one beat of pre-roll so pickup notes before the downbeat survive.
    ibi_a = float(np.median(np.diff(ga)))
    a_start = max(0.0, ga[ia] - ibi_a)

    # B: vocals come in on a downbeat after `intro_bars` bars of instrumental.
    db_ = _downbeats(gb, pb_)
    if len(db_) == 0:
        db_ = np.arange(len(gb))
    ib = int(db_[min(intro_bars, len(db_) - 1)])

    if mode == "beatwarp":
        n = min(len(ga) - 1 - ia, len(gb) - 1 - ib)
        knots_a = ga[ia : ia + n + 1]
        knots_out = gb[ib : ib + n + 1]
        first_factor = (knots_a[1] - knots_a[0]) / (knots_out[1] - knots_out[0]) if n >= 1 else m.stretch
        out_start = gb[ib] - (ga[ia] - a_start) / first_factor
        knots_a = np.concatenate([[a_start], knots_a])
        knots_out = np.concatenate([[out_start], knots_out])
    else:
        factor = 1.0 if mode == "naive" else m.stretch
        out_start = gb[ib] - (ga[ia] - a_start) / factor
        a_end = min(a.duration, a_start + (b.duration - out_start) * factor)
        knots_a = np.array([a_start, a_end])
        knots_out = out_start + (knots_a - a_start) / factor

    # If the pre-roll would start before t=0, trim it.
    if knots_out[0] < 0:
        f0 = (knots_a[1] - knots_a[0]) / (knots_out[1] - knots_out[0])
        knots_a[0] += -knots_out[0] * f0
        knots_out[0] = 0.0

    semitones = 0 if mode == "naive" else m.semitones
    return Plan(float(knots_a[0]), float(knots_a[-1]), float(knots_out[0]), out_len, knots_a, knots_out, semitones, mode)


def apply_plan(stem: np.ndarray, plan: Plan, sr: int = A.SR) -> np.ndarray:
    """Warp any stem of A into B's timeline (used for vocals, and for evaluation)."""
    s0, s1 = int(plan.a_start * sr), int(plan.a_end * sr)
    seg = np.ascontiguousarray(stem[:, s0:s1])
    out = np.zeros((stem.shape[0], plan.out_len), dtype=np.float32)
    if seg.shape[-1] < 2048:
        return out

    # Per-sample stretch factor: within each knot interval, A-duration / output-duration.
    durations_a = np.diff(plan.knots_a)
    durations_out = np.diff(plan.knots_out)
    factors = durations_a / np.maximum(durations_out, 1e-6)
    t = plan.a_start + np.arange(seg.shape[-1]) / sr
    idx = np.clip(np.searchsorted(plan.knots_a, t, side="right") - 1, 0, len(factors) - 1)
    stretch: float | np.ndarray = factors[idx].astype(np.float64)
    if np.allclose(stretch, stretch[0]):
        stretch = float(stretch[0])

    if isinstance(stretch, float) and stretch == 1.0 and plan.semitones == 0:
        warped = seg
    else:
        warped = pb.time_stretch(seg, sr, stretch_factor=stretch, pitch_shift_in_semitones=float(plan.semitones))

    o0 = int(round(plan.out_start * sr))
    n = min(warped.shape[-1], plan.out_len - o0)
    if n > 0:
        out[:, o0 : o0 + n] = warped[:, :n]
    return out


def _duck(vocals: np.ndarray, sr: int = A.SR, depth_db: float = 4.0) -> np.ndarray:
    """Gain curve that dips the instrumental's mid-range while someone is singing."""
    env = np.abs(A.to_mono(vocals))
    win = int(0.2 * sr)
    env = np.convolve(env, np.ones(win) / win, mode="same")
    active = np.clip(env / (np.percentile(env, 95) + 1e-9), 0, 1)
    return (10 ** (-depth_db * active / 20)).astype(np.float32)


def render(
    a_stems: dict[str, np.ndarray],
    a: Analysis,
    b_stems: dict[str, np.ndarray],
    b: Analysis,
    m: Match,
    mode: str = "beatwarp",
    intro_bars: int = 1,
    target_lufs: float = -14.0,
) -> tuple[np.ndarray, Plan]:
    plan = make_plan(a_stems["vocals"], a, b, m, mode, intro_bars)
    vocals = apply_plan(a_stems["vocals"], plan)

    # Light vocal chain: remove bleed rumble, a touch of room to glue it to the new beat.
    vocal_fx = pb.Pedalboard(
        [
            pb.HighpassFilter(cutoff_frequency_hz=120),
            pb.Reverb(room_size=0.25, wet_level=0.08, dry_level=1.0),
        ]
    )
    vocals = vocal_fx(vocals, A.SR)

    duck = _duck(vocals)
    beat = b_stems["drums"] + b_stems["bass"] + b_stems["other"] * duck
    beat = A.set_loudness(beat, target_lufs - 2)
    vocals = A.set_loudness(vocals, target_lufs - 3)

    mix = beat + vocals
    # JUCE's limiter adds make-up gain, so tame peaks with it, then set the ceiling ourselves.
    mix = pb.Pedalboard([pb.Limiter(threshold_db=-2.0, release_ms=100)])(mix, A.SR)
    mix = A.set_loudness(mix, target_lufs)
    mix *= min(1.0, 10 ** (-1 / 20) / (np.abs(mix).max() + 1e-9))  # true ceiling at -1 dBFS
    return A.fade(mix), plan

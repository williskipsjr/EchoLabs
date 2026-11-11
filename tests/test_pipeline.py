"""Tests on synthetic audio where the right answer is known exactly."""

import numpy as np
import pytest

from echolabs import analyze, match, remix
from echolabs.audio import SR

NOTE = {n: i for i, n in enumerate(analyze.PITCHES)}
NOTE.update({"Db": 1, "D#": 3, "G#": 8, "A#": 10})


def clicks(bpm: float, seconds: float, jitter: float = 0.0, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Stereo click track; returns (audio, true click times). `jitter` adds tempo drift."""
    rng = np.random.default_rng(seed)
    times, t = [], 0.1
    while t < seconds - 0.1:
        times.append(t)
        t += 60 / bpm * (1 + jitter * rng.standard_normal())
    y = np.zeros(int(seconds * SR), dtype=np.float32)
    burst = (np.hanning(400) * np.sin(2 * np.pi * 1500 * np.arange(400) / SR)).astype(np.float32)
    for t in times:
        i = int(t * SR)
        y[i : i + 400] += burst[: len(y) - i]
    return np.stack([y, y]), np.array(times)


def chords(progression: list[list[str]], seconds_each: float = 1.5) -> np.ndarray:
    t = np.arange(int(seconds_each * SR)) / SR
    parts = []
    for chord in progression:
        tone = sum(np.sin(2 * np.pi * 261.63 * 2 ** (NOTE[n] / 12) * t) for n in chord)
        parts.append(tone * np.hanning(len(t)))
    y = np.concatenate(parts).astype(np.float32) * 0.2
    return np.stack([y, y])


def test_camelot_wheel():
    assert analyze.camelot(NOTE["C"], "major") == "8B"
    assert analyze.camelot(NOTE["A"], "minor") == "8A"
    assert analyze.camelot(NOTE["B"], "major") == "1B"
    assert analyze.camelot(NOTE["E"], "minor") == "9A"


@pytest.mark.parametrize(
    "progression, expected",
    [
        ([["C", "E", "G"], ["F", "A", "C"], ["G", "B", "D"], ["C", "E", "G"]], "C major"),
        ([["A", "C", "E"], ["D", "F", "A"], ["E", "G#", "B"], ["A", "C", "E"]], "A minor"),
        ([["D", "F#", "A"], ["G", "B", "D"], ["A", "C#", "E"], ["D", "F#", "A"]], "D major"),
    ],
)
def test_key_estimation(progression, expected):
    assert analyze.estimate_key(chords(progression)).name == expected


def test_tempo_from_click_track():
    y, _ = clicks(120, 12)
    tempo, beats = analyze.track_beats(y)
    assert abs(tempo - 120) < 2
    assert len(beats) > 15


def test_key_relations_and_transpose():
    c_major = analyze.Key(NOTE["C"], "major", 1.0)
    assert match.key_relation(c_major, analyze.Key(NOTE["G"], "major", 1.0)) == "adjacent"
    assert match.key_relation(c_major, analyze.Key(NOTE["A"], "minor", 1.0)) == "relative"
    assert match.key_relation(c_major, analyze.Key(NOTE["F#"], "major", 1.0)) == "clash"
    shift, rel = match.best_transpose(analyze.Key(NOTE["D"], "major", 1.0), c_major)
    assert rel in ("same", "adjacent") and abs(shift) <= 2


def _analysis_from_truth(times: np.ndarray, seconds: float) -> analyze.Analysis:
    tempo = 60 / float(np.median(np.diff(times)))
    return analyze.Analysis(tempo, times, 0, analyze.Key(0, "major", 1.0), seconds)


def test_beatwarp_follows_drifting_tempo_better_than_global():
    """A drifts around 100 BPM, B is steady 120 BPM: beat-wise warp should land on B's grid."""
    a_audio, a_times = clicks(100, 16, jitter=0.04, seed=1)
    b_audio, b_times = clicks(120, 16)
    a, b = _analysis_from_truth(a_times, 16), _analysis_from_truth(b_times, 16)
    m = match.match(a, b, transpose=False)

    errors = {}
    for mode in ("global", "beatwarp"):
        plan = remix.make_plan(a_audio, a, b, m, mode=mode, intro_bars=1)
        warped = np.abs(remix.apply_plan(a_audio, plan)[0])
        ref = b_times[(b_times >= plan.out_start + 0.3) & (b_times <= plan.knots_out[-1] - 0.3)]
        # Where did each warped click actually land? Loudest sample near each target beat.
        half = int(0.2 * SR)
        landed = [(int(t * SR) - half + np.argmax(warped[int(t * SR) - half : int(t * SR) + half])) / SR for t in ref]
        errors[mode] = float(np.mean(np.abs(np.array(landed) - ref)))
    assert errors["beatwarp"] < 0.02  # under ~20 ms two hits stop sounding like a flam
    assert errors["beatwarp"] < errors["global"] / 2

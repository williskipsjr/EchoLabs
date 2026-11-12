"""Generate the data behind the landing page in site/ (served by GitHub Pages).

The page itself (site/index.html, styles.css, main.js) is hand-written. This
script produces everything it plays and plots, from real EchoLabs runs:

  site/audio/*.mp3, *.json   30 s mashup excerpts + their provenance manifests
  site/data/clips.json       waveform peaks and the facts shown under each clip
  site/data/story.json       real stems, beats and warp knots for the scroll story
  site/data/numbers.json     headline benchmark numbers, read from results/*.json

    uv run python scripts/build_site.py
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from echolabs import analyze, match, pipeline, remix, separate
from echolabs import audio as A

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "space" / "examples"
SITE = ROOT / "site"
EXCERPT_S, LEAD_IN_S = 30.0, 6.0
STORY_BARS = 4

SONGS = {
    "gabriel": {
        "file": "el_manny_quiere_money.mp3",
        "artist": "Gabriel Shellington",
        "title": "EL MANNY QUIERE MONEY",
        "url": "https://ccmixter.org/files/gabriel_shelligton/71296",
    },
    "malre": {
        "file": "same_block_new_bodies.mp3",
        "artist": "MalreDeszik",
        "title": "Same block, new bodies (ft. Synomo, IAComplexe)",
        "url": "https://ccmixter.org/files/MalreDeszik/71346",
    },
}
PAIRS = [("gabriel", "malre"), ("malre", "gabriel")]
MODES = ("beatwarp", "naive")


def peaks(audio: np.ndarray, n: int) -> list[float]:
    """RMS envelope in `n` bins, scaled so the loudest bin is 1."""
    mono = A.to_mono(audio)
    size = max(1, len(mono) // n)
    rms = np.sqrt((mono[: size * n].reshape(n, size) ** 2).mean(axis=1))
    return [round(float(v), 3) for v in rms / (rms.max() + 1e-9)]


def render_clip(vocals: str, beat: str, mode: str) -> dict:
    result = pipeline.mashup(EXAMPLES / SONGS[vocals]["file"], EXAMPLES / SONGS[beat]["file"], mode=mode, intro_bars=2)
    m = result.manifest
    start = max(0.0, m["plan"]["vocals_enter_at_s"] - LEAD_IN_S)
    name = f"{vocals}_vocals_x_{beat}_beat_{mode}"
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "mix.wav"
        A.save(wav, result.mix)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", str(EXCERPT_S), "-i", str(wav),
             "-af", f"afade=t=in:d=0.3,afade=t=out:st={EXCERPT_S - 2}:d=2", "-b:a", "160k",
             str(SITE / "audio" / f"{name}.mp3")],
            check=True,
        )  # fmt: skip
    m["excerpt_s"] = [round(start, 2), round(start + EXCERPT_S, 2)]
    (SITE / "audio" / f"{name}.json").write_text(json.dumps(m, indent=2))
    excerpt = result.mix[:, int(start * A.SR) : int((start + EXCERPT_S) * A.SR)]
    return {
        "src": f"audio/{name}.mp3",
        "manifest": f"audio/{name}.json",
        "peaks": peaks(excerpt, 240),
        "vocals_enter_s": round(m["plan"]["vocals_enter_at_s"] - start, 2),
        "vocals": m["sources"]["vocals"]["analysis"],
        "beat": m["sources"]["instrumental"]["analysis"],
        "match": m["match"],
        "plan": m["plan"],
    }


def story(vocals: str = "gabriel", beat: str = "malre") -> dict:
    """Real stems, beat grids and warp knots for the scroll-driven explainer."""
    a_stems = separate.separate_file(EXAMPLES / SONGS[vocals]["file"])
    b_stems = separate.separate_file(EXAMPLES / SONGS[beat]["file"])
    a, b = analyze.analyze_stems(a_stems), analyze.analyze_stems(b_stems)
    m = match.match(a, b)
    plan = remix.make_plan(a_stems["vocals"], a, b, m, mode="beatwarp", intro_bars=2)

    # Window A: the first bars of the vocal segment. Window B: where they land.
    n_knots = min(STORY_BARS * 4 + 1, len(plan.knots_a) - 1)
    a_beats = np.asarray(plan.knots_a[1 : n_knots + 1])
    o_beats = np.asarray(plan.knots_out[1 : n_knots + 1])
    a_win, b_win = (float(a_beats[0]), float(a_beats[-1])), (float(o_beats[0]), float(o_beats[-1]))

    def cut(x: np.ndarray, win: tuple[float, float]) -> np.ndarray:
        return x[:, int(win[0] * A.SR) : int(win[1] * A.SR)]

    def rel(t: np.ndarray, win: tuple[float, float]) -> list[float]:
        return [round(float((v - win[0]) / (win[1] - win[0])), 4) for v in t if win[0] - 1e-6 <= v <= win[1] + 1e-6]

    n = 400
    mixture = sum(a_stems.values())
    return {
        "a": {
            "song": SONGS[vocals] | {"tempo": round(a.tempo, 1), "key": a.key.name, "camelot": a.key.camelot},
            "seconds": round(a_win[1] - a_win[0], 2),
            "mix": peaks(cut(mixture, a_win), n),
            "stems": {k: peaks(cut(a_stems[k], a_win), n) for k in ("vocals", "drums", "bass", "other")},
            "beats": rel(a.beats, a_win),
        },
        "b": {
            "song": SONGS[beat] | {"tempo": round(b.tempo, 1), "key": b.key.name, "camelot": b.key.camelot},
            "seconds": round(b_win[1] - b_win[0], 2),
            "stems": {k: peaks(cut(b_stems[k], b_win), n) for k in ("drums", "bass", "other")},
            "beats": rel(b.beats, b_win),
        },
        "warp": {
            "a": rel(a_beats, a_win),
            "out": rel(o_beats, b_win),
            "factors": [round(float(x), 3) for x in np.diff(a_beats) / np.diff(o_beats)],
        },
        "match": m.summary() | {"camelot_after": analyze.camelot((a.key.tonic + m.semitones) % 12, a.key.mode)},
    }


def headline_numbers() -> dict:
    sep = json.loads((ROOT / "results/separation.json").read_text())
    key = json.loads((ROOT / "results/key.json").read_text())
    sync = json.loads((ROOT / "results/sync_trackers.json").read_text())
    s = sync["summary"]["librosa"]
    return {
        "separation": {
            "n": sep["n_tracks"],
            "htdemucs": {k: sep["median_sdr_db"][f"htdemucs/{k}"] for k in ("vocals", "drums", "bass", "other", "accompaniment")},
            "repet_sim": {k: sep["median_sdr_db"][f"repet_sim/{k}"] for k in ("vocals", "accompaniment")},
            "oracle": {k: sep["median_sdr_db"][f"oracle_irm/{k}"] for k in ("vocals", "drums", "bass", "other")},
            "realtime_factor_cpu": sep["htdemucs_realtime_factor_cpu"],
        },
        "sync": {
            "n": s["beatwarp"]["n"],
            "f": {k: s[k]["mean_beat_f_measure"] for k in ("naive", "global", "beatwarp")},
            "ceiling": s["self_warp_ceiling"]["mean_beat_f_measure"],
            "beatthis_beatwarp": sync["summary"]["beatthis"]["beatwarp"]["mean_beat_f_measure"],
            "clash": {k: s[k]["key_clash_rate"] for k in ("naive", "beatwarp")},
        },
        "key": {"n": key["n_tracks"]} | dict(key["summary"]),
    }


def main() -> None:
    for sub in ("audio", "data"):
        (SITE / sub).mkdir(parents=True, exist_ok=True)
    clips = []
    for vocals, beat in PAIRS:
        takes = {mode: render_clip(vocals, beat, mode) for mode in MODES}
        clips.append({"vocals_from": SONGS[vocals], "beat_from": SONGS[beat], "takes": takes})
        print("rendered", vocals, "x", beat)
    (SITE / "data" / "clips.json").write_text(json.dumps(clips))
    (SITE / "data" / "story.json").write_text(json.dumps(story()))
    (SITE / "data" / "numbers.json").write_text(json.dumps(headline_numbers(), indent=1))
    print("wrote site/data/{clips,story,numbers}.json")


if __name__ == "__main__":
    main()

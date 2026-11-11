# ruff: noqa: E501  (the embedded HTML template reads better unwrapped)
"""Build the static listening page in site/ (served by GitHub Pages).

Renders the demo pair in both directions with beat-warp and with the naive
overlay, cuts a short excerpt around where the vocals come in, and writes
index.html with each clip's provenance. Headline numbers are read from
results/*.json so the page can't drift from the benchmarks.

    uv run python scripts/build_site.py
"""

from __future__ import annotations

import html
import json
import subprocess
import tempfile
from pathlib import Path

from echolabs import audio as A
from echolabs import pipeline

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "space" / "examples"
SITE = ROOT / "site"
EXCERPT_S, LEAD_IN_S = 30.0, 6.0

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
MODES = [("beatwarp", "Beat-warp + transpose"), ("naive", "Naive overlay")]


def render_clip(vocals: str, beat: str, mode: str) -> dict:
    result = pipeline.mashup(EXAMPLES / SONGS[vocals]["file"], EXAMPLES / SONGS[beat]["file"], mode=mode, intro_bars=2)
    m = result.manifest
    start = max(0.0, m["plan"]["vocals_enter_at_s"] - LEAD_IN_S)
    name = f"{vocals}_vocals_x_{beat}_beat_{mode}"
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "mix.wav"
        A.save(wav, result.mix)
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                f"{start:.2f}",
                "-t",
                str(EXCERPT_S),
                "-i",
                str(wav),
                "-af",
                f"afade=t=in:d=0.3,afade=t=out:st={EXCERPT_S - 2}:d=2",
                "-b:a",
                "160k",
                str(SITE / "audio" / f"{name}.mp3"),
            ],
            check=True,
        )
    m["excerpt_s"] = [round(start, 2), round(start + EXCERPT_S, 2)]
    (SITE / "audio" / f"{name}.json").write_text(json.dumps(m, indent=2))
    return {"name": name, "manifest": m}


def chips(m: dict) -> str:
    v, b = m["sources"]["vocals"]["analysis"], m["sources"]["instrumental"]["analysis"]
    p, mt = m["plan"], m["match"]
    items = [
        f"{v['tempo_bpm']:.0f} → {b['tempo_bpm']:.0f} BPM",
        f"{v['key']} → {b['key']}",
        f"stretch ×{p['mean_stretch_applied']:.3f}",
        f"{p['semitones']:+d} semitones" if p["semitones"] else "no pitch shift",
        f"keys: {mt['key_relation']}",
    ]
    if p["mode"] == "beatwarp":
        items.append(f"{p['n_warp_segments']} beat segments")
    return "".join(f'<li class="chip{" bad" if "clash" in i else ""}">{html.escape(i)}</li>' for i in items)


def headline_numbers() -> dict:
    sep = json.loads((ROOT / "results/separation.json").read_text())["median_sdr_db"]
    key = json.loads((ROOT / "results/key.json").read_text())["summary"]["harmonic/krumhansl"]
    sync = json.loads((ROOT / "results/sync_trackers.json").read_text())["summary"]["librosa"]
    return {
        "vocals_sdr": sep["htdemucs/vocals"],
        "repet_sdr": sep["repet_sim/vocals"],
        "key_mirex": key["mirex_weighted"],
        "naive_f": sync["naive"]["mean_beat_f_measure"],
        "global_f": sync["global"]["mean_beat_f_measure"],
        "beatwarp_f": sync["beatwarp"]["mean_beat_f_measure"],
        "ceiling_f": sync["self_warp_ceiling"]["mean_beat_f_measure"],
        "clash_naive": round(100 * sync["naive"]["key_clash_rate"]),
        "clash_beatwarp": round(100 * sync["beatwarp"]["key_clash_rate"]),
    }


def page(clips: dict, n: dict) -> str:
    cards = []
    for vocals, beat in PAIRS:
        cols = []
        for mode, label in MODES:
            c = clips[(vocals, beat, mode)]
            cols.append(f"""
        <div class="take {mode}">
          <h3>{label}</h3>
          <audio controls preload="none" src="audio/{c["name"]}.mp3"></audio>
          <ul class="chips">{chips(c["manifest"])}</ul>
          <a class="small" href="audio/{c["name"]}.json">provenance manifest</a>
        </div>""")
        v, b = SONGS[vocals], SONGS[beat]
        cards.append(f"""
    <section class="card">
      <h2>{html.escape(v["artist"])}'s vocals <span class="x">×</span> {html.escape(b["artist"])}'s beat</h2>
      <div class="takes">{"".join(cols)}
      </div>
    </section>""")
    credits = "".join(
        f'<li>“{html.escape(s["title"])}” by {html.escape(s["artist"])} (<a href="{s["url"]}">ccMixter</a>)</li>'
        for s in SONGS.values()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EchoLabs: stem-aware AI mashups</title>
<meta name="description" content="Listen to EchoLabs mashups: Demucs stem separation, beat-by-beat warping and key-matched transposition, compared with a naive overlay.">
<style>
  :root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#57534e; --card:#ffffff; --line:#e7e5e4; --accent:#4f46e5; --bad:#b91c1c; --chip:#f5f5f4; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0c0a09; --fg:#f5f5f4; --muted:#a8a29e; --card:#1c1917; --line:#292524; --accent:#a5b4fc; --bad:#fca5a5; --chip:#292524; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 980px; margin: 0 auto; padding: 40px 16px 64px; }}
  h1 {{ font-size: 2rem; margin: 0 0 4px; letter-spacing: -0.02em; }}
  .lede {{ color: var(--muted); margin: 0 0 20px; max-width: 70ch; }}
  .links a {{ display:inline-block; margin: 0 8px 8px 0; padding: 8px 14px; border:1px solid var(--line); border-radius: 8px; color: var(--fg); text-decoration:none; background: var(--card); }}
  .links a.primary {{ background: var(--accent); color: var(--bg); border-color: var(--accent); }}
  .card {{ background: var(--card); border:1px solid var(--line); border-radius: 12px; padding: 20px; margin: 20px 0; }}
  h2 {{ font-size: 1.1rem; margin: 0 0 14px; }}
  .x {{ color: var(--muted); }}
  .takes {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
  .take {{ border:1px solid var(--line); border-radius: 10px; padding: 14px; }}
  .take.beatwarp {{ border-color: var(--accent); }}
  h3 {{ font-size: .95rem; margin: 0 0 10px; }}
  audio {{ width: 100%; }}
  .chips {{ list-style:none; padding:0; margin: 10px 0 8px; display:flex; flex-wrap: wrap; gap: 6px; }}
  .chip {{ background: var(--chip); border-radius: 999px; padding: 2px 10px; font-size: .82rem; }}
  .chip.bad {{ color: var(--bad); }}
  .small {{ font-size: .82rem; color: var(--muted); }}
  .table-wrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .92rem; }}
  td {{ text-align:left; padding: 8px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }}
  td.num {{ font-variant-numeric: tabular-nums; white-space: nowrap; font-weight: 600; }}
  footer {{ color: var(--muted); font-size: .85rem; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<main>
  <h1>EchoLabs</h1>
  <p class="lede">Stem-aware AI mashups. EchoLabs separates two songs with Demucs, finds tempo, beats and key, then stretches one song's vocals <em>beat by beat</em> onto the other's instrumental and transposes them to a compatible key. Each pair below is played twice: once with EchoLabs and once as a naive overlay with no sync and no transposition.</p>
  <p class="links">
    <a class="primary" href="https://colab.research.google.com/github/williskipsjr/EchoLabs/blob/main/notebooks/echolabs_demo.ipynb">Try it with your own songs (Colab)</a>
    <a href="https://github.com/williskipsjr/EchoLabs">Code &amp; benchmarks on GitHub</a>
  </p>
{"".join(cards)}

  <section class="card">
    <h2>Measured, not eyeballed</h2>
    <div class="table-wrap"><table>
      <tr><td>Vocal separation (MUSDB18, 50 clips)</td><td class="num">{n["vocals_sdr"]:.2f} dB SDR</td><td>vs {n["repet_sdr"]:.2f} dB for a classic DSP separator</td></tr>
      <tr><td>Beat alignment (100 song pairs)</td><td class="num">F = {n["beatwarp_f"]:.3f}</td><td>beat-warp vs {n["global_f"]:.3f} global stretch and {n["naive_f"]:.3f} naive; the judge's own ceiling is {n["ceiling_f"]:.3f}</td></tr>
      <tr><td>Key clashes (Camelot wheel)</td><td class="num">{n["clash_naive"]}% → {n["clash_beatwarp"]}%</td><td>naive overlay vs transposed</td></tr>
      <tr><td>Key detection (GiantSteps, 566 tracks)</td><td class="num">{n["key_mirex"]:.3f} MIREX</td><td>classic template baseline; learned models reach about 0.74</td></tr>
    </table></div>
  </section>

  <footer>
    <p>Example songs are used under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>; the clips above are remixed excerpts made by EchoLabs:</p>
    <ul>{credits}</ul>
    <p>Every mashup ships with a provenance manifest naming its sources and every transformation applied. Only remix music you have the rights to use.</p>
  </footer>
</main>
</body>
</html>
"""


def main() -> None:
    (SITE / "audio").mkdir(parents=True, exist_ok=True)
    clips = {}
    for vocals, beat in PAIRS:
        for mode, _ in MODES:
            clips[(vocals, beat, mode)] = render_clip(vocals, beat, mode)
            print("rendered", clips[(vocals, beat, mode)]["name"])
    (SITE / "index.html").write_text(page(clips, headline_numbers()))
    print(f"wrote {SITE / 'index.html'}")


if __name__ == "__main__":
    main()

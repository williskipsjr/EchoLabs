"""EchoLabs web demo: upload two songs, get one's vocals over the other's beat.

Run locally:  uv run --extra demo python space/app.py
Deployed as a Hugging Face Space from this folder (see space/README.md).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import gradio as gr

from echolabs import audio as A
from echolabs import pipeline, remix

# Separation runs at roughly real time on a CPU, so cap how much of each song is used.
MAX_SECONDS = float(os.environ.get("ECHOLABS_MAX_SECONDS", 60))

MODE_LABELS = {
    "Beat-warp (follows every beat)": "beatwarp",
    "Global stretch (one tempo ratio)": "global",
    "Naive overlay (no sync, for comparison)": "naive",
}


def _describe(manifest: dict) -> str:
    v = manifest["sources"]["vocals"]["analysis"]
    b = manifest["sources"]["instrumental"]["analysis"]
    m, p = manifest["match"], manifest["plan"]
    shift = f"{m['semitones']:+d} semitones" if m["semitones"] else "no pitch shift"
    return (
        f"**Vocals song:** {v['tempo_bpm']} BPM, {v['key']} ({v['camelot']})  \n"
        f"**Beat song:** {b['tempo_bpm']} BPM, {b['key']} ({b['camelot']})  \n"
        f"**What EchoLabs did:** stretched the vocals ×{m['stretch']:.3f}"
        f"{' (half/double-time)' if m['tempo_multiplier'] != 1 else ''}, {shift} "
        f"→ key relation **{m['key_relation']}**, sync **{p['mode']}** over {p['n_warp_segments']} segments, "
        f"vocals enter at {p['vocals_enter_at_s']} s.  \n"
        f"**Mashup score:** {m['score']:.2f} / 1"
    )


def run(vocals_file, beat_file, mode_label, transpose, intro_bars, has_rights, progress=gr.Progress()):  # noqa: B008 (Gradio injects progress via this default)
    if not has_rights:
        raise gr.Error("Please confirm you have the rights to use both recordings.")
    if not vocals_file or not beat_file:
        raise gr.Error("Upload both songs first.")

    progress(0.1, desc=f"Separating stems (first {int(MAX_SECONDS)} s of each song)…")
    try:
        result = pipeline.mashup(
            vocals_file,
            beat_file,
            mode=MODE_LABELS[mode_label],
            transpose=transpose,
            intro_bars=int(intro_bars),
            max_seconds=MAX_SECONDS,
        )
    except ValueError as e:  # e.g. too few beats found to align
        raise gr.Error(f"Couldn't align these songs: {e}") from e

    progress(0.95, desc="Writing files…")
    out_dir = Path(tempfile.mkdtemp(prefix="echolabs_"))
    wav, manifest_path = out_dir / "mashup.wav", out_dir / "mashup_provenance.json"
    A.save(wav, result.mix)
    manifest_path.write_text(json.dumps(result.manifest, indent=2))
    return str(wav), _describe(result.manifest), str(manifest_path)


with gr.Blocks(title="EchoLabs: AI mashup engine") as demo:
    gr.Markdown(
        "# EchoLabs\n"
        "Stem-aware AI mashups. EchoLabs separates both songs with **Demucs**, finds tempo, beats and key, "
        "then **beat-warps** the first song's vocals onto the second song's instrumental and transposes them "
        "to a compatible key.\n\n"
        f"Runs on CPU: expect roughly a minute or two per song. Only the first {int(MAX_SECONDS)} s of each upload is used. "
        "[Code and benchmarks](https://github.com/williskipsjr/EchoLabs)"
    )
    with gr.Row():
        vocals_in = gr.Audio(label="Song A: take the vocals from", type="filepath")
        beat_in = gr.Audio(label="Song B: take the instrumental from", type="filepath")
    with gr.Row():
        mode_in = gr.Radio(list(MODE_LABELS), value=next(iter(MODE_LABELS)), label="Sync method")
        with gr.Column():
            transpose_in = gr.Checkbox(value=True, label="Transpose vocals to a compatible key")
            intro_in = gr.Slider(0, 8, value=2, step=1, label="Bars of instrumental before the vocals come in")
    rights_in = gr.Checkbox(label="I own these recordings or have permission to remix them (e.g. Creative Commons).", value=False)
    go = gr.Button("Make mashup", variant="primary")

    mix_out = gr.Audio(label="Mashup", type="filepath")
    info_out = gr.Markdown()
    manifest_out = gr.File(label="Provenance manifest (sources + every transformation applied)")

    go.click(
        run,
        inputs=[vocals_in, beat_in, mode_in, transpose_in, intro_in, rights_in],
        outputs=[mix_out, info_out, manifest_out],
    )
    gr.Markdown(
        "Every mashup comes with a provenance file naming its source recordings and marking the output as an "
        "AI-generated derivative, so the original artists can be credited. "
        f"Sync methods: {', '.join(remix.MODES)}."
    )

demo.queue(default_concurrency_limit=1)

if __name__ == "__main__":
    demo.launch()

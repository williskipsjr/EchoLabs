"""EchoLabs web demo: upload two songs, get one's vocals over the other's beat.

Run locally:  uv run --extra demo python space/app.py
In a notebook: app.demo.launch(**app.LAUNCH_OPTIONS, share=True)
(Gradio 6 takes the theme and CSS at launch time, so launch through LAUNCH_OPTIONS.)
"""

from __future__ import annotations

import html
import inspect
import json
import os
import tempfile
from pathlib import Path

import gradio as gr

from echolabs import audio as A
from echolabs import pipeline

# Separation runs at roughly real time on a CPU, so cap how much of each song is used.
MAX_SECONDS = float(os.environ.get("ECHOLABS_MAX_SECONDS", 60))
EXAMPLES = Path(__file__).parent / "examples"
SITE = "https://williskipsjr.github.io/EchoLabs/"

MODE_LABELS = {
    "Beat-warp: follow every beat": "beatwarp",
    "Global stretch: one tempo ratio": "global",
    "Naive overlay: no sync, for comparison": "naive",
}

# Same tokens as the landing page (site/styles.css): studio blue, and four stem
# colours that always mean vocals, drums, bass and everything else.
INK, INK_2, INK_3, LINE = "#12193a", "#19224b", "#222c5c", "#2c376b"
TEXT, MUTED, WAVE_REST = "#edebf5", "#a3abcd", "#6872ab"
VOCALS, DRUMS, BASS, OTHER = "#ff7a93", "#f5b841", "#3fd0b0", "#9c8cff"


def _theme() -> gr.themes.Base:
    font = [gr.themes.GoogleFont("Bricolage Grotesque"), "system-ui", "sans-serif"]
    colours = {
        "body_background_fill": INK,
        "body_text_color": TEXT,
        "body_text_color_subdued": MUTED,
        "background_fill_primary": INK,
        "background_fill_secondary": INK_2,
        "block_background_fill": INK_2,
        "block_border_color": LINE,
        "block_label_background_fill": INK_2,
        "block_label_text_color": MUTED,
        "block_title_text_color": TEXT,
        "border_color_primary": LINE,
        "border_color_accent": MUTED,
        "color_accent": VOCALS,
        "color_accent_soft": INK_3,
        "input_background_fill": INK,
        "input_border_color": LINE,
        "input_placeholder_color": MUTED,
        "button_primary_background_fill": TEXT,
        "button_primary_background_fill_hover": "#ffffff",
        "button_primary_text_color": INK,
        "button_primary_border_color": TEXT,
        "button_secondary_background_fill": "transparent",
        "button_secondary_background_fill_hover": INK_3,
        "button_secondary_text_color": TEXT,
        "button_secondary_border_color": LINE,
        "checkbox_background_color": INK,
        "checkbox_background_color_selected": VOCALS,
        "checkbox_border_color": MUTED,
        "checkbox_border_color_selected": VOCALS,
        "checkbox_label_background_fill": INK_2,
        "checkbox_label_background_fill_selected": INK_3,
        "checkbox_label_text_color": TEXT,
        "slider_color": VOCALS,
        "link_text_color": TEXT,
        "link_text_color_hover": "#ffffff",
        "panel_background_fill": INK_2,
        "panel_border_color": LINE,
        "table_even_background_fill": INK_2,
        "table_odd_background_fill": INK,
        "table_border_color": LINE,
        "error_background_fill": INK_2,
        "error_border_color": VOCALS,
        "error_text_color": VOCALS,
    }
    # The studio is dark by design: give light and dark mode the same values
    # (only for the variables that have a separate dark-mode setting).
    theme = gr.themes.Base(font=font, radius_size=gr.themes.sizes.radius_lg)
    settable = set(inspect.signature(theme.set).parameters)
    dark = {f"{k}_dark": v for k, v in colours.items() if f"{k}_dark" in settable}
    return theme.set(**colours, **dark)


CSS = f"""
.gradio-container {{ max-width: 1180px !important; margin: 0 auto; }}
#header {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 8px 0 4px; }}
#header .brand {{ display: flex; align-items: center; gap: 12px; font-weight: 800; font-size: 1.5rem;
  font-variation-settings: "wdth" 78, "opsz" 72; letter-spacing: -0.01em; }}
#header .brand svg {{ width: 28px; height: 28px; }}
#header a {{ color: {MUTED}; text-decoration: none; font-size: 0.95rem; }}
#header a:hover {{ color: {TEXT}; }}
#tagline h1 {{ font-size: clamp(2rem, 5vw, 3.4rem); line-height: 0.95; font-weight: 800; margin: 18px 0 8px;
  font-variation-settings: "wdth" 75, "opsz" 96; letter-spacing: -0.012em; }}
#tagline p {{ color: {MUTED}; max-width: 62ch; margin: 0 0 8px; }}
.deck {{ border-top: 4px solid var(--deck) !important; border-radius: 14px !important; padding: 14px !important;
  background: {INK_2} !important; }}
.deck-a {{ --deck: {VOCALS}; }}
.deck-b {{ --deck: {DRUMS}; }}
.deck-head h3 {{ margin: 0 0 2px; font-size: 1.15rem; }}
.deck-head p {{ margin: 0; color: {MUTED}; font-size: 0.92rem; }}
.deck-head .tag {{ display: inline-block; width: 10px; height: 10px; border-radius: 3px; background: var(--deck);
  margin-right: 8px; }}
.field-msg:empty {{ display: none; }}
.field-msg p {{ margin: 6px 2px 0; color: {VOCALS}; font-weight: 600; font-size: 0.92rem; }}
#make {{ min-height: 52px; font-size: 1.05rem; font-weight: 700; }}
#result {{ background: {INK_2} !important; border: 1px solid {LINE} !important; border-radius: 14px !important; }}
#result-audio, #result-file {{ border: 0 !important; box-shadow: none !important; }}
#result-file {{ border-top: 1px solid {LINE} !important; }}
.progress-text, .eta-bar + *, .meta-text, .meta-text-center {{ font-family: inherit !important; }}
.progress-text {{ color: {TEXT} !important; font-size: 0.95rem !important; }}
.progress-level-inner {{ color: {TEXT} !important; font-family: inherit !important; }}
.progress-bar {{ background: {VOCALS} !important; }}
.result-empty {{ border: 1px dashed {LINE}; border-radius: 14px; padding: 22px; color: {MUTED}; }}
.result-empty strong {{ color: {TEXT}; }}
.result-card h3 {{ margin: 4px 0 10px; font-size: 1.15rem; }}
.chips {{ list-style: none; padding: 0; margin: 0 0 10px; display: flex; flex-wrap: wrap; gap: 6px; }}
.chips li {{ font-size: 0.88rem; padding: 4px 12px; border-radius: 999px; background: {INK_3}; color: {TEXT}; }}
.chips li.clash {{ color: {VOCALS}; }}
.chips li.match {{ color: {BASS}; }}
.result-card p {{ color: {MUTED}; margin: 0; font-size: 0.95rem; }}
#credits {{ color: {MUTED}; font-size: 0.88rem; border-top: 1px solid {LINE}; padding-top: 14px; margin-top: 8px; }}
#credits a {{ color: {TEXT}; }}
"""

HEADER = f"""
<div id="header">
  <div class="brand">
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="2" y="7" width="3.2" height="10" rx="1.6" fill="{VOCALS}"/>
      <rect x="7.6" y="3" width="3.2" height="18" rx="1.6" fill="{DRUMS}"/>
      <rect x="13.2" y="9" width="3.2" height="6" rx="1.6" fill="{BASS}"/>
      <rect x="18.8" y="5" width="3.2" height="14" rx="1.6" fill="{OTHER}"/>
    </svg>
    EchoLabs studio
  </div>
  <a href="{SITE}">How it works</a>
</div>
<div id="tagline">
  <h1>Put one song's vocals on another song's beat.</h1>
  <p>EchoLabs separates both songs into stems, stretches the vocals beat by beat onto the new instrumental
  and shifts them into a matching key. Only the first {int(MAX_SECONDS)} seconds of each song are used,
  so a mashup takes about a minute or two.</p>
</div>
"""

EMPTY_RESULT = """
<div class="result-empty">
  <strong>Your mashup will appear here.</strong><br>
  Add a song for the vocals and a song for the beat, then choose <strong>Make mashup</strong>.
  No songs to hand? Try one of the Creative Commons examples below.
</div>
"""


def _deck_head(title: str, helper: str) -> str:
    return f'<div class="deck-head"><h3><span class="tag"></span>{title}</h3><p>{helper}</p></div>'


def _field_msg(text: str = "") -> str:
    return f'<p role="alert">{html.escape(text)}</p>' if text else ""


def _result_card(manifest: dict) -> str:
    v, b = manifest["sources"]["vocals"]["analysis"], manifest["sources"]["instrumental"]["analysis"]
    m, p = manifest["match"], manifest["plan"]
    clash = m["key_relation"] == "clash"
    chips = [
        (f"{round(v['tempo_bpm'])} → {round(b['tempo_bpm'])} BPM", ""),
        (f"{v['key']} → {b['key']}", ""),
        (f"Vocals moved {p['semitones']:+d} semitones".replace("-", "−") if p["semitones"] else "No pitch shift", ""),
        (f"Stretched ×{p['mean_stretch_applied']:.3f}", ""),
        ("Keys clash" if clash else "Keys match", "clash" if clash else "match"),
    ]
    items = "".join(f'<li class="{c}">{html.escape(t)}</li>' for t, c in chips)
    how = {
        "beatwarp": f"stretched beat by beat across {p['n_warp_segments']} beats",
        "global": "stretched by one tempo ratio",
        "naive": "laid over the beat without any stretching",
    }[p["mode"]]
    return (
        f'<div class="result-card"><h3>What EchoLabs did</h3><ul class="chips">{items}</ul>'
        f"<p>The vocals were {how} and come in at {p['vocals_enter_at_s']} s. "
        f"Mixed to {manifest['output_lufs']} LUFS. The receipt below names both sources and every change.</p></div>"
    )


def run(vocals_file, beat_file, mode_label, transpose, intro_bars, has_rights, progress=gr.Progress()):  # noqa: B008 (Gradio injects progress via this default)
    # Validate first and show each problem next to its own field.
    msgs = {
        "a": "" if vocals_file else "Add song A. The vocals come from this song.",
        "b": "" if beat_file else "Add song B. The instrumental comes from this song.",
        "rights": "" if has_rights else "Tick this box to confirm you can remix both songs.",
    }
    if any(msgs.values()):
        return (gr.update(), gr.update(), gr.update(visible=False), *(_field_msg(t) for t in msgs.values()))

    try:
        result = pipeline.mashup(
            vocals_file,
            beat_file,
            mode=MODE_LABELS[mode_label],
            transpose=transpose,
            intro_bars=int(intro_bars),
            max_seconds=MAX_SECONDS,
            on_step=lambda fraction, message: progress(fraction, desc=message),
        )
    except ValueError as e:  # e.g. too few beats found to line the songs up
        raise gr.Error(f"These two songs couldn't be lined up: {e}. Try a song with a steadier beat.") from e

    out_dir = Path(tempfile.mkdtemp(prefix="echolabs_"))
    wav, manifest_path = out_dir / "mashup.wav", out_dir / "mashup_provenance.json"
    A.save(wav, result.mix)
    manifest_path.write_text(json.dumps(result.manifest, indent=2))
    return str(wav), _result_card(result.manifest), gr.update(value=str(manifest_path), visible=True), "", "", ""


with gr.Blocks(title="EchoLabs studio") as demo:
    gr.HTML(HEADER)

    with gr.Row(equal_height=True):
        with gr.Column(elem_classes=["deck", "deck-a"]):
            gr.HTML(_deck_head("Song A: the vocals", "EchoLabs keeps the singing from this song."))
            vocals_in = gr.Audio(label="Song A", type="filepath", sources=["upload", "microphone"])
            vocals_msg = gr.HTML(elem_classes=["field-msg"])
        with gr.Column(elem_classes=["deck", "deck-b"]):
            gr.HTML(_deck_head("Song B: the beat", "EchoLabs keeps the drums, bass and everything else."))
            beat_in = gr.Audio(label="Song B", type="filepath", sources=["upload", "microphone"])
            beat_msg = gr.HTML(elem_classes=["field-msg"])

    with gr.Accordion("Options", open=False):
        mode_in = gr.Radio(
            list(MODE_LABELS),
            value=next(iter(MODE_LABELS)),
            label="How to line the vocals up with the beat",
            info="Beat-warp sounds tightest. The naive overlay is there so you can hear the difference.",
        )
        transpose_in = gr.Checkbox(
            value=True,
            label="Move the vocals into a matching key",
            info="Uses the smallest pitch shift that lands on a compatible key on the Camelot wheel.",
        )
        intro_in = gr.Slider(0, 8, value=2, step=1, label="Bars of beat before the vocals come in")

    rights_in = gr.Checkbox(
        label="I own these recordings or have permission to remix them, for example a Creative Commons licence."
    )
    rights_msg = gr.HTML(elem_classes=["field-msg"])
    go = gr.Button("Make mashup", variant="primary", elem_id="make")

    with gr.Group(elem_id="result"):
        mix_out = gr.Audio(
            label="Your mashup",
            elem_id="result-audio",
            type="filepath",
            interactive=False,
            waveform_options=gr.WaveformOptions(waveform_color=WAVE_REST, waveform_progress_color=VOCALS),
        )
        info_out = gr.HTML(EMPTY_RESULT)
        manifest_out = gr.File(
            label="Provenance receipt (JSON): both sources and every change", visible=False, elem_id="result-file"
        )

    go.click(
        run,
        inputs=[vocals_in, beat_in, mode_in, transpose_in, intro_in, rights_in],
        outputs=[mix_out, info_out, manifest_out, vocals_msg, beat_msg, rights_msg],
        # One progress readout, in the result area, instead of an overlay on every output.
        show_progress_on=[info_out],
    )

    # CC BY 4.0 songs from ccMixter; see examples/ATTRIBUTION.md. Compare the
    # same pair with beat-warp and with the naive overlay to hear the difference.
    beatwarp, naive = list(MODE_LABELS)[0], list(MODE_LABELS)[2]
    gabriel, malre = str(EXAMPLES / "el_manny_quiere_money.mp3"), str(EXAMPLES / "same_block_new_bodies.mp3")
    gr.Examples(
        examples=[
            [gabriel, malre, beatwarp, True, 2, True],
            [gabriel, malre, naive, False, 2, True],
            [malre, gabriel, beatwarp, True, 2, True],
        ],
        inputs=[vocals_in, beat_in, mode_in, transpose_in, intro_in, rights_in],
        label="Try an example: Creative Commons songs from ccMixter (CC BY 4.0)",
    )
    gr.HTML(
        '<div id="credits">Every mashup comes with a provenance receipt that names its source recordings and marks '
        "the result as AI-generated, so the original artists can be credited. Example songs: "
        "“EL MANNY QUIERE MONEY” by Gabriel Shellington and “Same block, new bodies” by MalreDeszik, used under "
        '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. '
        '<a href="https://github.com/williskipsjr/EchoLabs">Code and benchmarks</a>.</div>'
    )

demo.queue(default_concurrency_limit=1)

# The theme's font loader only requests weights; load the width and optical-size
# axes too so headings can use the same condensed cut as the landing page.
HEAD = (
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:'
    'opsz,wdth,wght@12..96,75..100,200..800&display=swap">'
)

LAUNCH_OPTIONS = {"theme": _theme(), "css": CSS, "head": HEAD}

if __name__ == "__main__":
    demo.launch(**LAUNCH_OPTIONS)

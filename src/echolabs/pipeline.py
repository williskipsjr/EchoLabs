"""End-to-end mashup: two audio files in, mixed audio plus a provenance manifest out.

Shared by the CLI and the web demo so both produce identical results.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from . import __version__, analyze, match, remix, separate
from . import audio as A


@dataclass
class MashupResult:
    mix: np.ndarray
    manifest: dict
    vocals_analysis: analyze.Analysis
    beat_analysis: analyze.Analysis


def analyse_file(path: str | Path, max_seconds: float | None = None) -> tuple[dict[str, np.ndarray], analyze.Analysis]:
    stems = separate.separate_file(path, max_seconds=max_seconds)
    return stems, analyze.analyze_stems(stems)


def build_manifest(
    a_path: Path,
    b_path: Path,
    a: analyze.Analysis,
    b: analyze.Analysis,
    m: match.Match,
    plan: remix.Plan,
    mix: np.ndarray,
) -> dict:
    """Provenance: who the music came from and exactly what was done to it."""
    return {
        "generated_by": f"EchoLabs {__version__}",
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "ai_generated_derivative": True,
        "sources": {
            "vocals": {"file": a_path.name, "sha1_16": separate.file_hash(a_path), "analysis": a.summary()},
            "instrumental": {"file": b_path.name, "sha1_16": separate.file_hash(b_path), "analysis": b.summary()},
        },
        "match": m.summary(),
        "plan": plan.summary(),
        "output_lufs": round(A.loudness(mix), 1),
        "note": "Only remix music you have the rights to use. Credit the original artists.",
    }


def mashup(
    vocals_from: str | Path,
    beat_from: str | Path,
    mode: str = "beatwarp",
    transpose: bool = True,
    intro_bars: int = 4,
    max_seconds: float | None = None,
    on_step: Callable[[float, str], None] | None = None,
) -> MashupResult:
    """Run the whole pipeline. `on_step(fraction_done, message)` reports progress
    before each stage; separation dominates the run time, hence the uneven split."""
    step = on_step or (lambda fraction, message: None)
    a_path, b_path = Path(vocals_from), Path(beat_from)
    step(0.0, "Separating song A into vocals, drums, bass and other")
    a_stems, a = analyse_file(a_path, max_seconds)
    step(0.45, "Separating song B into vocals, drums, bass and other")
    b_stems, b = analyse_file(b_path, max_seconds)
    step(0.9, "Matching tempo and key")
    # Naive mode applies no pitch shift, so score the key relation of the untouched audio.
    m = match.match(a, b, transpose=transpose and mode != "naive")
    step(0.93, "Warping the vocals onto the beat and mixing")
    mix, plan = remix.render(a_stems, a, b_stems, b, m, mode=mode, intro_bars=intro_bars)
    step(0.98, "Writing the provenance receipt")
    return MashupResult(mix, build_manifest(a_path, b_path, a, b, m, plan, mix), a, b)

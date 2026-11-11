"""Source separation with Demucs (Hybrid Transformer Demucs, `htdemucs`).

Stems are cached on disk keyed by the file's content hash, because separation
is by far the slowest step on a CPU.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch

from . import audio as A

STEMS = ("drums", "bass", "other", "vocals")
CACHE_DIR = Path("data/cache/stems")


@lru_cache(maxsize=2)
def get_model(name: str = "htdemucs"):
    from demucs.pretrained import get_model as _get

    model = _get(name)
    model.eval()
    return model


def separate_array(mix: np.ndarray, model_name: str = "htdemucs", shifts: int = 1) -> dict[str, np.ndarray]:
    """Separate a stereo 44.1 kHz mix into the four Demucs stems."""
    from demucs.apply import apply_model

    model = get_model(model_name)
    wav = torch.from_numpy(mix)
    # Same normalisation the Demucs CLI applies before inference.
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    wav = (wav - mean) / std
    with torch.inference_mode():
        # Use a GPU when one exists (e.g. Colab); separation is ~real time on CPU.
        device = "cuda" if torch.cuda.is_available() else "cpu"
        out = apply_model(model, wav[None], shifts=shifts, split=True, overlap=0.25, progress=False, device=device)[0]
    out = out.cpu() * std + mean
    return {name: out[i].numpy().astype(np.float32) for i, name in enumerate(model.sources)}


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def separate_file(path: str | Path, model_name: str = "htdemucs", max_seconds: float | None = None) -> dict[str, np.ndarray]:
    """Separate a file, reusing cached stems when the same file was seen before.

    `max_seconds` keeps only the start of the song, which bounds CPU time
    (the web demo uses it; separation runs at roughly real time on a CPU).
    """
    path = Path(path)
    suffix = f"_{int(max_seconds)}s" if max_seconds else ""
    cache = CACHE_DIR / f"{file_hash(path)}_{model_name}{suffix}"
    if all((cache / f"{s}.wav").exists() for s in STEMS):
        return {s: A.load(cache / f"{s}.wav") for s in STEMS}
    mix = A.load(path)
    if max_seconds:
        mix = np.ascontiguousarray(mix[:, : int(max_seconds * A.SR)])
    stems = separate_array(mix, model_name)
    for name, wav in stems.items():
        A.save(cache / f"{name}.wav", wav)
    return stems


def instrumental(stems: dict[str, np.ndarray]) -> np.ndarray:
    return stems["drums"] + stems["bass"] + stems["other"]

"""Key-detection accuracy on GiantSteps Key (604 EDM tracks, human-labelled keys).

Ablation: {full mix, harmonic part only (HPSS, drums suppressed)} x
{Krumhansl, Temperley profiles}. Scored with the MIREX weighted key score
(1.0 exact, 0.5 perfect fifth, 0.3 relative, 0.2 parallel major/minor).
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import librosa
import mir_eval
import mirdata
import numpy as np
from tqdm import tqdm

from .. import analyze

SR = 22050
CONDITIONS = [(src, prof) for src in ("full_mix", "harmonic") for prof in analyze.PROFILES]


def _normalise_label(label: str) -> str | None:
    """Keep 'tonic major|minor'; drop mode qualifiers like 'F minor aeolian'.

    Labels that aren't major/minor (e.g. 'D dorian', or no key) are excluded,
    because the estimator only predicts the 24 major/minor keys.
    """
    tokens = label.split()
    if len(tokens) < 2 or tokens[1] not in ("major", "minor"):
        return None
    try:
        key = f"{tokens[0]} {tokens[1]}"
        mir_eval.key.validate_key(key)
        return key
    except ValueError:
        return None


def _predict(path: str) -> dict[str, str]:
    y, _ = librosa.load(path, sr=SR, mono=True)
    sources = {"full_mix": y, "harmonic": librosa.effects.harmonic(y, margin=2.0)}
    return {f"{src}/{prof}": analyze.estimate_key(sources[src], sr=SR, profile=prof).name for src, prof in CONDITIONS}


def run(data_home: str, limit: int | None, workers: int, out: Path) -> dict:
    ds = mirdata.initialize("giantsteps_key", data_home=data_home)
    tracks = []
    for tid in ds.track_ids:
        t = ds.track(tid)
        label = _normalise_label(t.key) if t.key else None
        if label and Path(t.audio_path).exists():
            tracks.append((tid, t.audio_path, label))
    tracks = tracks[:limit] if limit else tracks

    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for (tid, _, label), preds in tqdm(zip(tracks, pool.map(_predict, [p for _, p, _ in tracks])), total=len(tracks)):
            row = {"track": tid, "label": label}
            for cond, est in preds.items():
                row[cond] = est
                row[f"{cond}/score"] = mir_eval.key.weighted_score(label, est)
            rows.append(row)

    summary = {}
    for src, prof in CONDITIONS:
        c = f"{src}/{prof}"
        scores = np.array([r[f"{c}/score"] for r in rows])
        summary[c] = {"mirex_weighted": round(float(scores.mean()), 3), "exact_accuracy": round(float((scores == 1.0).mean()), 3)}

    result = {"dataset": "GiantSteps Key", "n_tracks": len(rows), "summary": summary, "per_track": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-home", default="data/giantsteps_key")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", type=Path, default=Path("results/key.json"))
    args = p.parse_args()
    r = run(args.data_home, args.limit, args.workers, args.out)
    print(json.dumps({k: v for k, v in r.items() if k != "per_track"}, indent=2))


if __name__ == "__main__":
    main()

"""Does the mashup actually line up? Ablation of naive / global / beatwarp sync.

For each (A, B) pair we warp A's *drum* stem with exactly the plan used for its
vocals, re-track beats on the warped drums, and score them against B's beats:

  * beat F-measure (mir_eval, +-70 ms window) inside the region where A plays
  * median |offset| between each warped-A beat and its nearest B beat, in ms
  * key relation between transposed A (bass + other) and B, re-estimated on
    the warped audio: fraction of pairs that clash on the Camelot wheel

Ground-truth MUSDB stems are used so this isolates the sync stage from
separation errors (separation is benchmarked in `evaluation/separation.py`).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import mir_eval
import musdb
import numpy as np
from tqdm import tqdm

from .. import analyze, match, remix
from .. import audio as A

STEMS = ("drums", "bass", "other", "vocals")


def _stems(track) -> dict[str, np.ndarray]:
    return {k: track.targets[k].audio.T.astype(np.float32) for k in STEMS}


def _score_pair(sa, a, sb, b, m, mode) -> dict:
    plan = remix.make_plan(sa["vocals"], a, b, m, mode)
    lo, hi = plan.out_start, plan.knots_out[-1]
    drums = remix.apply_plan(sa["drums"], plan)
    # Finer hop (5.8 ms) than the analysis default so offsets aren't quantised to 23 ms.
    _, warped_beats = analyze.track_beats(drums, hop=128)
    _, b_beats = analyze.track_beats(sb["drums"], hop=128)
    est = warped_beats[(warped_beats >= lo) & (warped_beats <= hi)]
    ref = b_beats[(b_beats >= lo) & (b_beats <= hi)]
    f = mir_eval.beat.f_measure(ref, est) if len(ref) and len(est) else 0.0
    offsets = [np.min(np.abs(ref - t)) * 1000 for t in est] if len(ref) and len(est) else [np.nan]

    harmonic = remix.apply_plan(sa["bass"] + sa["other"], plan)
    window = harmonic[:, int(lo * A.SR) : int(hi * A.SR)]
    rel = match.key_relation(analyze.estimate_key(window), b.key) if window.shape[-1] > A.SR else "n/a"
    return {"f_measure": float(f), "offset_ms": float(np.mean(offsets)), "key_relation": rel}


def run(root: str, n_pairs: int, seed: int, out: Path) -> dict:
    db = musdb.DB(root=root)
    by_name = {t.name: t for t in db.tracks}
    # Stems for all 144 clips would need ~1.4 GB, so analyse one at a time and reload on demand.
    ana, singing = {}, set()
    for name, t in tqdm(by_name.items(), desc="analyse"):
        s = _stems(t)
        ana[name] = analyze.analyze_stems(s)
        if A.loudness(s["vocals"]) > -35:
            singing.add(name)

    # Vocal source must actually contain singing; tempo gap must be DJ-plausible.
    candidates = []
    for va in sorted(singing):
        for ib in sorted(ana):
            if va == ib or len(ana[va].beats) < 6 or len(ana[ib].beats) < 6:
                continue
            m = match.match(ana[va], ana[ib])
            if 0.85 <= m.stretch <= 1.18:
                candidates.append((va, ib, m))
    random.Random(seed).shuffle(candidates)
    pairs = candidates[:n_pairs]

    rows = []
    for va, ib, m in tqdm(pairs, desc="pairs"):
        sa, sb = _stems(by_name[va]), _stems(by_name[ib])
        row = {"vocals_from": va, "beat_from": ib, "stretch": round(m.stretch, 3), "semitones": m.semitones}
        for mode in remix.MODES:
            try:
                for k, v in _score_pair(sa, ana[va], sb, ana[ib], m, mode).items():
                    row[f"{mode}/{k}"] = v
            except ValueError as e:  # too few beats to align
                row[f"{mode}/error"] = str(e)
        rows.append(row)

    summary = {}
    for mode in remix.MODES:
        ok = [r for r in rows if f"{mode}/f_measure" in r]
        rels = [r[f"{mode}/key_relation"] for r in ok if r[f"{mode}/key_relation"] != "n/a"]
        summary[mode] = {
            "mean_beat_f_measure": round(float(np.mean([r[f"{mode}/f_measure"] for r in ok])), 3),
            "mean_offset_ms": round(float(np.nanmean([r[f"{mode}/offset_ms"] for r in ok])), 1),
            "key_clash_rate": round(rels.count("clash") / len(rels), 3) if rels else None,
            "n_pairs": len(ok),
        }

    result = {
        "dataset": "MUSDB18 7 s sample (ground-truth stems), random DJ-plausible pairs",
        "n_candidate_pairs": len(candidates),
        "seed": seed,
        "summary": summary,
        "pairs": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default="data/musdb18_sample")
    p.add_argument("--pairs", type=int, default=100)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, default=Path("results/sync.json"))
    args = p.parse_args()
    r = run(args.root, args.pairs, args.seed, args.out)
    print(json.dumps({k: v for k, v in r.items() if k != "pairs"}, indent=2))


if __name__ == "__main__":
    main()

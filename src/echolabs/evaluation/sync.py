"""Does the mashup actually line up? Ablation of naive / global / beatwarp sync.

For each (A, B) pair we warp A's *drum* stem with exactly the plan used for its
vocals, re-track beats on the warped drums, and score them against B's beats:

  * beat F-measure (mir_eval, +-70 ms window) inside the region where A plays
  * median |offset| between each warped-A beat and its nearest B beat, in ms
  * key relation between transposed A (bass + other) and B, re-estimated on
    the warped audio: fraction of pairs that clash on the Camelot wheel

Each beat tracker plans the warp on the same pairs; the judge is fixed. A
self-warp run (a song onto itself, ideal = identity) measures the metric's
noise floor, i.e. the best score any method could get from this judge.

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


def _summarise(rows: list[dict], prefix: str) -> dict:
    ok = [r for r in rows if f"{prefix}/f_measure" in r]
    rels = [r[f"{prefix}/key_relation"] for r in ok if r[f"{prefix}/key_relation"] != "n/a"]
    return {
        "mean_beat_f_measure": round(float(np.mean([r[f"{prefix}/f_measure"] for r in ok])), 3),
        "mean_offset_ms": round(float(np.nanmean([r[f"{prefix}/offset_ms"] for r in ok])), 1),
        "key_clash_rate": round(rels.count("clash") / len(rels), 3) if rels else None,
        "n": len(ok),
    }


def run(root: str, n_pairs: int, seed: int, trackers: list[str], n_ceiling: int, out: Path) -> dict:
    db = musdb.DB(root=root)
    by_name = {t.name: t for t in db.tracks}
    # Stems for all 144 clips would need ~1.4 GB, so analyse one at a time and reload on demand.
    ana = {tr: {} for tr in trackers}
    singing = set()
    for name, t in tqdm(by_name.items(), desc="analyse"):
        s = _stems(t)
        for tr in trackers:
            ana[tr][name] = analyze.analyze_stems(s, tracker=tr)
        if A.loudness(s["vocals"]) > -35:
            singing.add(name)

    # Pairs are chosen once, from the first tracker's tempos, so every tracker is
    # scored on exactly the same pairs. Vocal source must contain singing and the
    # tempo gap must be DJ-plausible.
    ref = ana[trackers[0]]
    candidates = []
    for va in sorted(singing):
        for ib in sorted(ref):
            if va == ib or len(ref[va].beats) < 6 or len(ref[ib].beats) < 6:
                continue
            if 0.85 <= match.match(ref[va], ref[ib]).stretch <= 1.18:
                candidates.append((va, ib))
    random.Random(seed).shuffle(candidates)
    pairs = candidates[:n_pairs]

    rows = []
    for va, ib in tqdm(pairs, desc="pairs"):
        sa, sb = _stems(by_name[va]), _stems(by_name[ib])
        row = {"vocals_from": va, "beat_from": ib}
        for tr in trackers:
            m = match.match(ana[tr][va], ana[tr][ib])
            row[f"{tr}/stretch"], row[f"{tr}/semitones"] = round(m.stretch, 3), m.semitones
            for mode in remix.MODES:
                try:
                    for k, v in _score_pair(sa, ana[tr][va], sb, ana[tr][ib], m, mode).items():
                        row[f"{tr}/{mode}/{k}"] = v
                except ValueError as e:  # too few beats to align
                    row[f"{tr}/{mode}/error"] = str(e)
        rows.append(row)

    # Noise floor of the metric: warp a song onto itself (ideal = identity) and
    # see what the judge reports. No sync method can score above this.
    ceiling_rows = []
    for name in random.Random(seed + 1).sample(sorted(singing), min(n_ceiling, len(singing))):
        s = _stems(by_name[name])
        row = {"track": name}
        for tr in trackers:
            a = ana[tr][name]
            if len(a.beats) >= 6:
                for k, v in _score_pair(s, a, s, a, match.match(a, a), "beatwarp").items():
                    row[f"{tr}/self/{k}"] = v
        ceiling_rows.append(row)

    summary = {
        tr: {mode: _summarise(rows, f"{tr}/{mode}") for mode in remix.MODES}
        | {"self_warp_ceiling": _summarise(ceiling_rows, f"{tr}/self")}
        for tr in trackers
    }
    result = {
        "dataset": "MUSDB18 7 s sample (ground-truth stems), random DJ-plausible pairs",
        "judge": "librosa beat tracker (hop 128) on warped A drums vs B drums, +-70 ms F-measure",
        "n_candidate_pairs": len(candidates),
        "seed": seed,
        "summary": summary,
        "pairs": rows,
        "ceiling": ceiling_rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default="data/musdb18_sample")
    p.add_argument("--pairs", type=int, default=100)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--trackers", nargs="+", choices=analyze.TRACKERS, default=list(analyze.TRACKERS))
    p.add_argument("--ceiling-tracks", type=int, default=30)
    p.add_argument("--out", type=Path, default=Path("results/sync.json"))
    args = p.parse_args()
    r = run(args.root, args.pairs, args.seed, args.trackers, args.ceiling_tracks, args.out)
    print(json.dumps({k: v for k, v in r.items() if k not in ("pairs", "ceiling")}, indent=2))


if __name__ == "__main__":
    main()

"""Command line: `echolabs analyze`, `echolabs rank`, `echolabs mashup`."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, analyze, match, remix, separate
from . import audio as A

AUDIO_EXT = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}


def _analyse(path: Path) -> tuple[dict, analyze.Analysis]:
    stems = separate.separate_file(path)
    return stems, analyze.analyze_stems(stems)


def cmd_analyze(args) -> None:
    for path in args.files:
        _, ana = _analyse(Path(path))
        print(json.dumps({"file": str(path)} | ana.summary()))


def cmd_rank(args) -> None:
    files = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in AUDIO_EXT)
    analyses = {p.name: _analyse(p)[1] for p in files}
    for vocals, beat, m in match.rank_pairs(analyses)[: args.top]:
        print(
            f"{m.score:.2f}  vocals: {vocals:30s} beat: {beat:30s}  "
            f"stretch x{m.stretch:.3f}  shift {m.semitones:+d} st  key {m.key_relation}"
        )


def cmd_mashup(args) -> None:
    t0 = time.perf_counter()
    a_path, b_path = Path(args.vocals_from), Path(args.beat_from)
    a_stems, a = _analyse(a_path)
    b_stems, b = _analyse(b_path)
    m = match.match(a, b, transpose=not args.no_transpose)
    mix, plan = remix.render(a_stems, a, b_stems, b, m, mode=args.mode, intro_bars=args.intro_bars)

    out = Path(args.out)
    A.save(out, mix)
    # Provenance: who the music came from and exactly what was done to it.
    manifest = {
        "generated_by": f"RemixLab {__version__}",
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "ai_generated_derivative": True,
        "sources": {
            "vocals": {"file": a_path.name, "sha1_16": separate._file_hash(a_path), "analysis": a.summary()},
            "instrumental": {"file": b_path.name, "sha1_16": separate._file_hash(b_path), "analysis": b.summary()},
        },
        "match": m.summary(),
        "plan": plan.summary(),
        "output_lufs": round(A.loudness(mix), 1),
        "note": "Only remix music you have the rights to use. Credit the original artists.",
    }
    out.with_suffix(".json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest["match"] | manifest["plan"], indent=2))
    print(f"wrote {out} (+ provenance {out.with_suffix('.json').name}) in {time.perf_counter() - t0:.1f}s")


def main() -> None:
    p = argparse.ArgumentParser(prog="echolabs", description="Stem-aware AI mashup engine")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("analyze", help="tempo, beats, downbeat and key of songs")
    s.add_argument("files", nargs="+")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("rank", help="rank every vocal/beat pairing in a folder")
    s.add_argument("folder")
    s.add_argument("--top", type=int, default=10)
    s.set_defaults(func=cmd_rank)

    s = sub.add_parser("mashup", help="put one song's vocals over another's instrumental")
    s.add_argument("vocals_from")
    s.add_argument("beat_from")
    s.add_argument("-o", "--out", default="outputs/mashup.wav")
    s.add_argument("--mode", choices=remix.MODES, default="beatwarp")
    s.add_argument("--intro-bars", type=int, default=4)
    s.add_argument("--no-transpose", action="store_true")
    s.set_defaults(func=cmd_mashup)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

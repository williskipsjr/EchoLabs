"""Command line: `echolabs analyze`, `echolabs rank`, `echolabs mashup`."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import audio as A
from . import match, pipeline, remix

AUDIO_EXT = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}


def cmd_analyze(args) -> None:
    for path in args.files:
        _, ana = pipeline.analyse_file(Path(path))
        print(json.dumps({"file": str(path)} | ana.summary()))


def cmd_rank(args) -> None:
    files = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in AUDIO_EXT)
    analyses = {p.name: pipeline.analyse_file(p)[1] for p in files}
    for vocals, beat, m in match.rank_pairs(analyses)[: args.top]:
        print(
            f"{m.score:.2f}  vocals: {vocals:30s} beat: {beat:30s}  "
            f"stretch x{m.stretch:.3f}  shift {m.semitones:+d} st  key {m.key_relation}"
        )


def cmd_mashup(args) -> None:
    t0 = time.perf_counter()
    result = pipeline.mashup(
        args.vocals_from,
        args.beat_from,
        mode=args.mode,
        transpose=not args.no_transpose,
        intro_bars=args.intro_bars,
        max_seconds=args.max_seconds,
    )
    out = Path(args.out)
    A.save(out, result.mix)
    out.with_suffix(".json").write_text(json.dumps(result.manifest, indent=2))
    print(json.dumps(result.manifest["match"] | result.manifest["plan"], indent=2))
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
    s.add_argument("--max-seconds", type=float, default=None, help="only use the first N seconds of each song")
    s.set_defaults(func=cmd_mashup)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

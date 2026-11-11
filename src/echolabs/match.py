"""Decide how two songs can be combined: tempo ratio, transposition, compatibility."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .analyze import Analysis, Key, camelot


@dataclass
class Match:
    tempo_multiplier: float  # treat A as half / normal / double time: 0.5, 1 or 2
    stretch: float  # >1 speeds A up; applied after the multiplier
    semitones: int  # pitch shift applied to A
    key_relation: str  # "same" | "adjacent" | "relative" | "clash"
    score: float  # 0..1, higher = easier, cleaner mashup

    def summary(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


# How much each kind of key relationship costs (Camelot wheel neighbours).
KEY_RELATION_SCORE = {"same": 1.0, "adjacent": 0.85, "relative": 0.8, "clash": 0.3}


def key_relation(a: Key | tuple[int, str], b: Key | tuple[int, str]) -> str:
    ca = camelot(*a) if isinstance(a, tuple) else a.camelot
    cb = camelot(*b) if isinstance(b, tuple) else b.camelot
    na, la, nb, lb = int(ca[:-1]), ca[-1], int(cb[:-1]), cb[-1]
    if ca == cb:
        return "same"
    if la == lb and (na - nb) % 12 in (1, 11):
        return "adjacent"
    if na == nb:
        return "relative"
    return "clash"


def best_transpose(a: Key, b: Key, max_shift: int = 6) -> tuple[int, str]:
    """Smallest pitch shift of A that makes it harmonically compatible with B.

    Large shifts make vocals sound unnatural (chipmunk / formant artefacts), so
    a better key relation is only taken if it doesn't cost many extra semitones.
    """
    best = None
    for s in range(-max_shift, max_shift + 1):
        rel = key_relation(((a.tonic + s) % 12, a.mode), b)
        cost = (1 - KEY_RELATION_SCORE[rel]) * 4 + abs(s) * 0.5
        if best is None or cost < best[0]:
            best = (cost, s, rel)
    return best[1], best[2]


def _shift_penalty(semitones: int) -> float:
    return float(np.exp(-abs(semitones) / 4))


def _stretch_penalty(stretch: float) -> float:
    # ~8% stretch is nearly transparent; beyond ~25% artefacts are obvious.
    return float(np.exp(-abs(np.log(stretch)) / 0.12))


def match(a: Analysis, b: Analysis, transpose: bool = True) -> Match:
    """How should A (vocal source) be transformed to sit on B (instrumental)?"""
    multiplier = min((0.5, 1.0, 2.0), key=lambda m: abs(np.log(b.tempo / (a.tempo * m))))
    stretch = b.tempo / (a.tempo * multiplier)
    if transpose:
        semitones, rel = best_transpose(a.key, b.key)
    else:
        semitones, rel = 0, key_relation(a.key, b.key)
    score = _stretch_penalty(stretch) * _shift_penalty(semitones) * KEY_RELATION_SCORE[rel]
    return Match(multiplier, stretch, semitones, rel, score)


def rank_pairs(analyses: dict[str, Analysis]) -> list[tuple[str, str, Match]]:
    """All (vocals-from, beat-from) pairs in a library, best mashups first."""
    pairs = [(va, ib, match(analyses[va], analyses[ib])) for va in analyses for ib in analyses if va != ib]
    return sorted(pairs, key=lambda p: p[2].score, reverse=True)

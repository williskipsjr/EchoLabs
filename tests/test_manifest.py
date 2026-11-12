"""The provenance manifest must name both sources and flag the output as AI-generated."""

import json

import numpy as np

from echolabs import analyze, match, pipeline, remix
from echolabs.audio import SR


def _analysis(tempo: float) -> analyze.Analysis:
    beats = np.arange(0.5, 8.0, 60 / tempo)
    return analyze.Analysis(tempo, beats, 0, analyze.Key(0, "major", 0.2), 8.0)


def test_manifest_records_sources_and_transformations(tmp_path):
    a_path, b_path = tmp_path / "singer.wav", tmp_path / "producer.wav"
    a_path.write_bytes(b"vocals-from")
    b_path.write_bytes(b"beat-from")
    a, b = _analysis(100), _analysis(110)
    m = match.match(a, b)
    vocals = np.zeros((2, 8 * SR), dtype=np.float32)
    plan = remix.make_plan(vocals, a, b, m, mode="beatwarp", intro_bars=1)
    mix = np.random.default_rng(0).standard_normal((2, 8 * SR)).astype(np.float32) * 0.1

    manifest = pipeline.build_manifest(a_path, b_path, a, b, m, plan, mix)

    assert manifest["ai_generated_derivative"] is True
    assert manifest["sources"]["vocals"]["file"] == "singer.wav"
    assert manifest["sources"]["instrumental"]["file"] == "producer.wav"
    assert manifest["sources"]["vocals"]["sha1_16"] != manifest["sources"]["instrumental"]["sha1_16"]
    assert manifest["match"]["stretch"] == round(110 / 100, 3)
    assert manifest["plan"]["mode"] == "beatwarp"
    json.dumps(manifest)  # must be serialisable as written next to the audio


def test_plan_reports_the_stretch_actually_applied():
    a, b = _analysis(100), _analysis(110)
    m = match.match(a, b)
    vocals = np.zeros((2, 8 * SR), dtype=np.float32)
    naive = remix.make_plan(vocals, a, b, m, mode="naive", intro_bars=1).summary()
    glob = remix.make_plan(vocals, a, b, m, mode="global", intro_bars=1).summary()
    assert naive["mean_stretch_applied"] == 1.0 and naive["semitones"] == 0
    assert glob["mean_stretch_applied"] == round(m.stretch, 3)


def test_mashup_reports_each_stage_in_order(monkeypatch, tmp_path):
    """on_step must fire for every stage, in order, with non-decreasing progress."""
    a, b = _analysis(100), _analysis(110)
    stems = {k: np.zeros((2, 8 * SR), dtype=np.float32) for k in ("drums", "bass", "other", "vocals")}
    calls = iter([(stems, a), (stems, b)])
    monkeypatch.setattr(pipeline, "analyse_file", lambda path, max_seconds=None: next(calls))
    for name in ("a.wav", "b.wav"):
        (tmp_path / name).write_bytes(name.encode())

    seen = []
    result = pipeline.mashup(tmp_path / "a.wav", tmp_path / "b.wav", intro_bars=1, on_step=lambda f, m: seen.append((f, m)))

    fractions = [f for f, _ in seen]
    assert fractions == sorted(fractions) and fractions[0] == 0.0 and fractions[-1] < 1.0
    assert [m.split()[0] for _, m in seen] == ["Separating", "Separating", "Matching", "Warping", "Writing"]
    assert result.manifest["plan"]["mode"] == "beatwarp"

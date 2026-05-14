"""Tests for prepare_predict_inputs and its helpers."""
from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from dlc_3d_bp.lp.predict_runner import _load_view_names


def _write_cfg(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip())
    return p


def test_load_view_names_multiview(tmp_path):
    cfg = _write_cfg(tmp_path / "config.yaml", """
        data:
          view_names:
            - cam0
            - cam1
    """)
    assert _load_view_names(cfg.parent) == ["cam0", "cam1"]


def test_load_view_names_singleview_default(tmp_path):
    cfg = _write_cfg(tmp_path / "config.yaml", """
        data:
          csv_file: labels.csv
    """)
    assert _load_view_names(cfg.parent) == []


def test_load_view_names_missing_config(tmp_path):
    assert _load_view_names(tmp_path) == []


from dlc_3d_bp.lp.predict_runner import _resolve_siblings


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p


def test_resolve_siblings_pairs_camN(tmp_path):
    """One cam0 input + cam1 sibling on disk → both paths returned."""
    d = tmp_path / "vids"
    a = _touch(d / "khoai_cam0_20260507.avi")
    b = _touch(d / "khoai_cam1_20260507.avi")
    out = _resolve_siblings([a], view_names=["cam0", "cam1"])
    assert out["pairs"] == [[a, b]]
    assert out["warnings"] == []


def test_resolve_siblings_warns_on_missing(tmp_path):
    """One cam0 input but no cam1 sibling → session dropped, warning recorded."""
    d = tmp_path / "vids"
    a = _touch(d / "khoai_cam0_20260507.avi")
    out = _resolve_siblings([a], view_names=["cam0", "cam1"])
    assert out["pairs"] == []
    assert any("cam1" in w for w in out["warnings"])


def test_resolve_siblings_dedupes_when_user_supplies_both(tmp_path):
    """User supplies both views → still one pair, not two."""
    d = tmp_path / "vids"
    a = _touch(d / "khoai_cam0_20260507.avi")
    b = _touch(d / "khoai_cam1_20260507.avi")
    out = _resolve_siblings([a, b], view_names=["cam0", "cam1"])
    assert out["pairs"] == [[a, b]]
    assert out["warnings"] == []


def test_resolve_siblings_passthrough_unknown_pattern(tmp_path):
    """Filename without _camN_ → passed through alone with a warning."""
    d = tmp_path / "vids"
    a = _touch(d / "weird_filename.avi")
    out = _resolve_siblings([a], view_names=["cam0", "cam1"])
    assert out["pairs"] == [[a]]
    assert any("no view token" in w.lower() for w in out["warnings"])


def test_resolve_siblings_singleview_returns_each(tmp_path):
    """view_names == [] → each input becomes its own one-element 'pair'."""
    d = tmp_path / "vids"
    a = _touch(d / "v1.avi"); b = _touch(d / "v2.avi")
    out = _resolve_siblings([a, b], view_names=[])
    assert out["pairs"] == [[a], [b]]


from dlc_3d_bp.lp.predict_runner import _transcode_to_mp4


def test_transcode_skips_when_mp4_exists(tmp_path, monkeypatch):
    """If <stem>.mp4 already exists next to <stem>.avi, no ffmpeg call."""
    d = tmp_path / "vids"; d.mkdir()
    src = d / "video.avi"; src.write_bytes(b"\x00")
    cached = d / "video.mp4"; cached.write_bytes(b"\x00")

    called = []
    def _fake_run(cmd, **_kw):
        called.append(cmd)
        raise AssertionError("ffmpeg should not be invoked when mp4 cache exists")
    monkeypatch.setattr("subprocess.run", _fake_run)

    out, transcoded = _transcode_to_mp4(src)
    assert out == cached
    assert transcoded is False
    assert called == []


def test_transcode_invokes_ffmpeg_stream_copy(tmp_path, monkeypatch):
    """Non-mp4 input + no cache → ffmpeg -c copy invoked, output path returned."""
    d = tmp_path / "vids"; d.mkdir()
    src = d / "video.avi"; src.write_bytes(b"\x00")

    seen = {}
    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        # Pretend ffmpeg succeeded and produced an mp4
        (d / "video.mp4").write_bytes(b"\x00")
        class _R:
            returncode = 0
            stderr = ""
        return _R()
    monkeypatch.setattr("subprocess.run", _fake_run)

    out, transcoded = _transcode_to_mp4(src)
    assert out == d / "video.mp4"
    assert transcoded is True
    assert "ffmpeg" in seen["cmd"][0]
    assert "-c" in seen["cmd"] and "copy" in seen["cmd"]


def test_transcode_falls_back_on_copy_failure(tmp_path, monkeypatch):
    """If -c copy fails, retry with libx264."""
    d = tmp_path / "vids"; d.mkdir()
    src = d / "video.avi"; src.write_bytes(b"\x00")

    calls = []
    def _fake_run(cmd, **kw):
        calls.append(cmd)
        class _R:
            stderr = "muxer not compatible"
        # First call (stream copy) fails; second call (re-encode) succeeds
        if "-c" in cmd and "copy" in cmd:
            _R.returncode = 1
        else:
            (d / "video.mp4").write_bytes(b"\x00")
            _R.returncode = 0
        return _R()
    monkeypatch.setattr("subprocess.run", _fake_run)

    out, transcoded = _transcode_to_mp4(src)
    assert out == d / "video.mp4"
    assert transcoded is True
    assert len(calls) == 2
    assert any("libx264" in c for c in calls[1])


def test_transcode_mp4_input_is_identity(tmp_path):
    """MP4 input → returns the same path, no transcode."""
    d = tmp_path / "vids"; d.mkdir()
    src = d / "video.mp4"; src.write_bytes(b"\x00")
    out, transcoded = _transcode_to_mp4(src)
    assert out == src
    assert transcoded is False

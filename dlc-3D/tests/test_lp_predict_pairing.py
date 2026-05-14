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

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

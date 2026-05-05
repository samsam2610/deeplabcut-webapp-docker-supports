"""Unit tests for the sibling-h5 path resolver."""
from pathlib import Path

from dlc_3d_bp.routes import _resolve_sibling_h5


def test_substitutes_cam_token_in_basename(tmp_path: Path):
    cam0 = tmp_path / "OM-2_cam0_20260424_DLC_resnet50_DREADDApr27shuffle1_50000.h5"
    cam1 = tmp_path / "OM-2_cam1_20260424_DLC_resnet50_DREADDApr27shuffle1_50000.h5"
    cam0.write_bytes(b"")
    cam1.write_bytes(b"")
    out = _resolve_sibling_h5(str(cam0), 1)
    assert out == {"path": str(cam1), "exists": True}


def test_returns_path_with_exists_false_when_sibling_missing(tmp_path: Path):
    cam0 = tmp_path / "OM-2_cam0_20260424_DLC_resnet50_DREADDApr27shuffle1_50000.h5"
    cam0.write_bytes(b"")
    expected_sibling = tmp_path / "OM-2_cam1_20260424_DLC_resnet50_DREADDApr27shuffle1_50000.h5"
    out = _resolve_sibling_h5(str(cam0), 1)
    assert out == {"path": str(expected_sibling), "exists": False}


def test_no_cam_token_in_path_returns_none(tmp_path: Path):
    f = tmp_path / "no_cam_token.h5"
    f.write_bytes(b"")
    assert _resolve_sibling_h5(str(f), 0) == {"path": None, "exists": False}


def test_same_cam_index_returns_input_path(tmp_path: Path):
    cam0 = tmp_path / "OM-2_cam0_20260424.h5"
    cam0.write_bytes(b"")
    out = _resolve_sibling_h5(str(cam0), 0)
    assert out == {"path": str(cam0), "exists": True}

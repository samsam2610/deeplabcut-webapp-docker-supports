import numpy as np
import pandas as pd
import pytest

from dlc_3d_bp.labelled_session import load_labelled_session

BPS = ["Snout", "Wrist", "MCP-1"]


def _make_session(tmp_path, rows):
    """rows: list of (cam, videoframe, xy-list-or-None-per-bodypart)."""
    d = tmp_path / "sess"
    d.mkdir()
    (d / "calibration.toml").write_text("[cam_0]\n[cam_1]\n")
    index, data = [], []
    for cam, frame, coords in rows:
        name = "img_cam{}_{:04d}_{}.png".format(cam, len(index), frame)
        (d / name).write_bytes(b"")
        index.append(name)
        flat = []
        for c in coords:
            flat += [np.nan, np.nan] if c is None else [c[0], c[1]]
        data.append(flat)
    cols = pd.MultiIndex.from_product(
        [["Ali"], BPS, ["x", "y"]], names=["scorer", "bodyparts", "coords"])
    pd.DataFrame(data, columns=cols, index=index).to_hdf(
        d / "CollectedData_Ali.h5", key="df_with_missing", mode="w")
    return d


def test_returns_only_frames_labelled_in_both_cameras(tmp_path):
    d = _make_session(tmp_path, [
        (0, 100, [(1, 2), (3, 4), None]),
        (1, 100, [(5, 6), (7, 8), None]),
        (0, 200, [(1, 1), None, None]),      # cam0 only -> excluded
    ])
    s = load_labelled_session(str(d))
    assert [p["frame"] for p in s["pairs"]] == [100]
    assert s["bodyparts"] == BPS
    assert s["calibration_path"].endswith("calibration.toml")


def test_coordinates_are_per_camera_and_nan_where_unlabelled(tmp_path):
    d = _make_session(tmp_path, [
        (0, 7, [(1, 2), None, (5, 6)]),
        (1, 7, [(9, 8), (7, 6), None]),
    ])
    p = load_labelled_session(str(d))["pairs"][0]
    assert p["cam0_xy"].shape == (3, 2)
    assert np.allclose(p["cam0_xy"][0], [1, 2])
    assert np.isnan(p["cam0_xy"][1]).all(), "unlabelled must stay NaN"
    assert np.allclose(p["cam1_xy"][1], [7, 6])
    assert np.isnan(p["cam1_xy"][2]).all()


def test_image_paths_point_at_the_right_files(tmp_path):
    d = _make_session(tmp_path, [
        (0, 42, [(1, 2), (3, 4), (5, 6)]),
        (1, 42, [(1, 2), (3, 4), (5, 6)]),
    ])
    p = load_labelled_session(str(d))["pairs"][0]
    assert "img_cam0_" in p["cam0_image"] and p["cam0_image"].endswith("_42.png")
    assert "img_cam1_" in p["cam1_image"] and p["cam1_image"].endswith("_42.png")


def test_a_session_with_no_paired_frames_yields_none(tmp_path):
    d = _make_session(tmp_path, [(0, 1, [(1, 2), None, None])])
    assert load_labelled_session(str(d))["pairs"] == []

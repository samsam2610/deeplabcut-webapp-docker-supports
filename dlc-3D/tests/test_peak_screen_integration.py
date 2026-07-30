"""The screen inside run_reprojection, driven by a synthetic sidecar.

Reuses the geometry fixture pattern already proven in
tests/test_reprojection_io.py::test_run_reprojection_rescues_and_rejects so the
rescues we screen are real rather than mocked. The suite has no test-to-test
import convention (tests/__init__.py exists, which makes such imports
fragile), so the small fixture helpers (CALIB, BODYPARTS, SCORER, _write_calib,
_make_df, _write_h5) are copied here rather than imported.
"""
import numpy as np
import pandas as pd
import pytest

from dlc_3d_bp import peaks_io as pio
from dlc_3d_bp import reprojection as rp
from dlc_3d_bp.epipolar_core import Cam, project_point

CALIB = """
[cam_0]
name = "0"
size = [ 800, 600,]
matrix = [ [ 2382.07, 0.0, 399.5,], [ 0.0, 2382.07, 299.5,], [ 0.0, 0.0, 1.0,],]
distortions = [ -0.0355, 0.0, 0.0, 0.0, 0.0,]
rotation = [ 0.0041, 0.0031, -0.0240,]
translation = [ -0.844, 1.414, -13.840,]

[cam_1]
name = "1"
size = [ 800, 600,]
matrix = [ [ 2308.44, 0.0, 399.5,], [ 0.0, 2308.44, 299.5,], [ 0.0, 0.0, 1.0,],]
distortions = [ -0.1512, 0.0, 0.0, 0.0, 0.0,]
rotation = [ 0.0370, -0.4901, -0.0016,]
translation = [ 149.34, 23.07, 104.69,]

[metadata]
adjusted = false
error = 0.0735
"""

BODYPARTS = ["Snout", "Pellet"]
SCORER = "DLC_TestNet_shuffle1_snapshot_best-180"


def _write_calib(tmp_path):
    p = tmp_path / "calibration.toml"
    p.write_text(CALIB)
    return p


def _make_df(xy, lik):
    """xy: (n_frames, n_bodyparts, 2); lik: (n_frames, n_bodyparts)."""
    cols = pd.MultiIndex.from_product(
        [[SCORER], BODYPARTS, ["x", "y", "likelihood"]],
        names=["scorer", "bodyparts", "coords"],
    )
    data = np.empty((xy.shape[0], len(BODYPARTS) * 3), dtype=np.float32)
    for j in range(len(BODYPARTS)):
        data[:, j * 3 + 0] = xy[:, j, 0]
        data[:, j * 3 + 1] = xy[:, j, 1]
        data[:, j * 3 + 2] = lik[:, j]
    return pd.DataFrame(data, columns=cols)


def _write_h5(path, df):
    df.to_hdf(str(path), key="df_with_missing", format="table", mode="w")


def _build_pair(tmp_path):
    """300 frames of a moving 3D point, exactly consistent in both views, then
    damage the target view: frames 100-109 get a confident but geometrically
    impossible position (REJECT), frames 200-209 keep the correct position but
    a low likelihood (RESCUE). Mirrors
    test_reprojection_io.py::test_run_reprojection_rescues_and_rejects.
    """
    calib = _write_calib(tmp_path)
    cams = rp.load_calibration(calib)
    ref_cam, tgt_cam = cams["cam_0"], cams["cam_1"]

    n = 300
    t = np.linspace(0.0, 1.0, n)
    xyz = np.c_[10.0 + 2.0 * t, -5.0 + 2.0 * t, 250.0 + 5.0 * t]

    ref_xy = np.stack([project_point(ref_cam, xyz)] * 2, axis=1)
    tgt_xy = np.stack([project_point(tgt_cam, xyz)] * 2, axis=1)
    ref_lik = np.full((n, 2), 0.99, dtype=np.float32)
    tgt_lik = np.full((n, 2), 0.99, dtype=np.float32)

    tgt_xy[100:110, 0] += 250.0          # far off the epipolar line
    tgt_lik[200:210, 0] = 0.10           # correct place, low confidence

    ref_h5 = tmp_path / "s_cam0_x.h5"
    tgt_h5 = tmp_path / "s_cam1_x.h5"
    _write_h5(ref_h5, _make_df(ref_xy, ref_lik))
    _write_h5(tgt_h5, _make_df(tgt_xy, tgt_lik))
    return calib, ref_h5, tgt_h5


def _sidecar_for(h5_path, frames, bodyparts, xy_per_frame, k=3):
    """Write a sidecar whose peak 0 is at xy_per_frame and whose rest are NaN."""
    n, b = len(frames), len(bodyparts)
    xy = np.full((n, b, k, 2), np.nan, np.float32)
    score = np.zeros((n, b, k), np.float32)
    for i in range(n):
        for j in range(b):
            xy[i, j, 0] = xy_per_frame[i]
            score[i, j, 0] = 0.9
    pio.write_peaks_npz(
        pio.peaks_sidecar_path(h5_path), np.asarray(frames, np.int32),
        xy, score, list(bodyparts),
        {"k": k, "min_distance": 3, "snapshot": "s.pt",
         "stride": 2.0, "locref_std": 7.2801})


def test_align_maps_sparse_sidecar_rows_onto_dense_frame_positions():
    peaks = {
        "frames": np.array([0, 2], np.int32),
        "xy": np.array([[[[1.0, 2.0]]], [[[3.0, 4.0]]]], np.float32),
        "score": np.array([[[0.7]], [[0.8]]], np.float32),
        "bodyparts": ["nose"],
        "meta": {},
    }
    xy, score, covered = rp.align_peaks_to_frames(4, peaks, "nose")
    assert xy.shape == (4, 1, 2) and score.shape == (4, 1)
    np.testing.assert_array_equal(covered, [True, False, True, False])
    np.testing.assert_allclose(xy[0, 0], [1.0, 2.0])
    np.testing.assert_allclose(xy[2, 0], [3.0, 4.0])
    assert np.isnan(xy[1]).all()
    assert score[1, 0] == 0.0


def test_align_returns_all_uncovered_for_an_unknown_bodypart():
    peaks = {
        "frames": np.array([0], np.int32),
        "xy": np.zeros((1, 1, 2, 2), np.float32),
        "score": np.zeros((1, 1, 2), np.float32),
        "bodyparts": ["nose"], "meta": {},
    }
    xy, score, covered = rp.align_peaks_to_frames(3, peaks, "elbow")
    assert not covered.any()
    assert np.isnan(xy).all()


def test_summary_reports_no_screen_when_require_peaks_is_off(tmp_path):
    calib, ref_h5, tgt_h5 = _build_pair(tmp_path)
    out = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                              out_dir=tmp_path, require_peaks=False)
    assert out["peak_screen"] is None


def test_missing_sidecar_leaves_every_rescue_standing(tmp_path):
    """require_peaks with no sidecar must not silently void every rescue."""
    calib, ref_h5, tgt_h5 = _build_pair(tmp_path)
    # run_reprojection has never created out_dir itself (write_pose_h5 requires
    # it to pre-exist); the base fixture always passes an already-existing
    # tmp_path, so these fresh subdirectories need creating explicitly.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    base = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                               out_dir=tmp_path / "a", require_peaks=False)
    screened = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                                   out_dir=tmp_path / "b", require_peaks=True)
    assert screened["counts"]["RESCUE"] == base["counts"]["RESCUE"]
    assert screened["peak_screen"]["covered"] == 0


def test_a_sidecar_with_peaks_far_off_the_line_refuses_every_rescue(tmp_path):
    """Peaks parked far from any epipolar line must produce NO_EVIDENCE."""
    calib, ref_h5, tgt_h5 = _build_pair(tmp_path)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    base = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                               out_dir=tmp_path / "a", require_peaks=False)
    if base["counts"]["RESCUE"] == 0:
        pytest.skip("fixture produced no rescues to screen")

    df, meta = rp.read_pose_h5(tgt_h5)
    n = len(df)
    _sidecar_for(tgt_h5, list(range(n)), meta["bodyparts"],
                 [(9e4, 9e4)] * n)

    screened = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                                   out_dir=tmp_path / "b", require_peaks=True)
    assert screened["counts"]["RESCUE"] == 0
    assert screened["counts"]["NO_EVIDENCE"] == base["counts"]["RESCUE"]
    assert screened["peak_screen"]["refused"] == base["counts"]["RESCUE"]


def test_the_screen_never_changes_a_marker_position(tmp_path):
    """Refusing a rescue must leave x/y exactly as the geometry run left them
    minus the rescue, and must never write a peak's coordinates."""
    calib, ref_h5, tgt_h5 = _build_pair(tmp_path)
    (tmp_path / "b").mkdir()
    df, meta = rp.read_pose_h5(tgt_h5)
    n = len(df)
    _sidecar_for(tgt_h5, list(range(n)), meta["bodyparts"], [(9e4, 9e4)] * n)

    screened = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                                   out_dir=tmp_path / "b", require_peaks=True)
    out_df, out_meta = rp.read_pose_h5(screened["outputs"]["tgt_h5"])
    sc = out_meta["scorer"]
    for bp in out_meta["bodyparts"]:
        x = out_df[(sc, bp, "x")].to_numpy(dtype=float)
        assert not np.isclose(x[np.isfinite(x)], 9e4).any(), bp


def test_verdict_names_cover_the_two_new_codes():
    from dlc_3d_bp import epipolar_core as ec
    assert ec.VERDICT_NAMES[6] == "NO_EVIDENCE"
    assert ec.VERDICT_NAMES[7] == "CORRECTED"

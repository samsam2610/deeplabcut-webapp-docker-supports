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


def _build_pair(tmp_path, damage_side="tgt"):
    """300 frames of a moving 3D point, exactly consistent in both views, then
    damage one view: frames 100-109 get a confident but geometrically
    impossible position (REJECT), frames 200-209 keep the correct position but
    a low likelihood (RESCUE).

    damage_side="tgt" (default) mirrors
    test_reprojection_io.py::test_run_reprojection_rescues_and_rejects.
    damage_side="ref" produces the mirror-image fixture needed to exercise the
    flipped (overrides={"Snout": "ref"}) path: there the judged/corrected side
    is the reference camera, so the reference view must be the damaged one to
    get any RESCUE candidates out of it, while the target view stays fully
    clean and plays the "trusted" role.
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

    damaged_xy = ref_xy if damage_side == "ref" else tgt_xy
    damaged_lik = ref_lik if damage_side == "ref" else tgt_lik
    damaged_xy[100:110, 0] += 250.0          # far off the epipolar line
    damaged_lik[200:210, 0] = 0.10           # correct place, low confidence

    ref_h5 = tmp_path / "s_cam0_x.h5"
    tgt_h5 = tmp_path / "s_cam1_x.h5"
    _write_h5(ref_h5, _make_df(ref_xy, ref_lik))
    _write_h5(tgt_h5, _make_df(tgt_xy, tgt_lik))
    return calib, ref_h5, tgt_h5


def _true_xy(h5_path, bodypart):
    """Read a bodypart's own (x, y) straight out of a pose h5, per-frame."""
    df, meta = rp.read_pose_h5(h5_path)
    sc = meta["scorer"]
    x = df[(sc, bodypart, "x")].to_numpy(dtype=float)
    y = df[(sc, bodypart, "y")].to_numpy(dtype=float)
    return list(zip(x.tolist(), y.tolist()))


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
    """require_peaks with no sidecar must not silently void every rescue.

    Compares the FULL counts dict (not just RESCUE) and the actual output h5
    contents byte-for-byte, so a change that shuffled some OTHER verdict, or
    that touched the written coordinates while leaving RESCUE's count alone,
    would be caught here."""
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

    # A geometry-only run never emits NO_EVIDENCE/CORRECTED, so both dicts
    # carry those keys at 0; the loop still requires them to match.
    assert set(screened["counts"]) == set(base["counts"])
    for name, count in base["counts"].items():
        assert screened["counts"][name] == count, name
    assert screened["peak_screen"]["covered"] == 0

    base_ref_df, _ = rp.read_pose_h5(base["outputs"]["ref_h5"])
    base_tgt_df, _ = rp.read_pose_h5(base["outputs"]["tgt_h5"])
    scr_ref_df, _ = rp.read_pose_h5(screened["outputs"]["ref_h5"])
    scr_tgt_df, _ = rp.read_pose_h5(screened["outputs"]["tgt_h5"])
    pd.testing.assert_frame_equal(base_ref_df, scr_ref_df)
    pd.testing.assert_frame_equal(base_tgt_df, scr_tgt_df)


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


def test_true_target_peaks_keep_the_rescues(tmp_path):
    """Positive control for the unflipped path.

    Every other integration test either has no sidecar (covered == 0) or
    peaks parked at 9e4, where any distance formula refuses. Neither
    distinguishes the real screen from an implementation that always refuses
    (e.g. distances forced to a huge constant): both would pass. Only a
    sidecar carrying the TRUE marker position, checked for KEEP, exercises the
    discriminative claim through the actual run_reprojection wiring.
    """
    calib, ref_h5, tgt_h5 = _build_pair(tmp_path)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    base = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                               out_dir=tmp_path / "a", require_peaks=False)
    if base["counts"]["RESCUE"] == 0:
        pytest.skip("fixture produced no rescues to screen")

    # The RESCUE frames (200-209) never had their position damaged, only
    # their likelihood, so what's already in tgt_h5 there IS the same
    # project_point(tgt_cam, xyz) value the fixture computed.
    df, meta = rp.read_pose_h5(tgt_h5)
    n = len(df)
    _sidecar_for(tgt_h5, list(range(n)), meta["bodyparts"],
                 _true_xy(tgt_h5, "Snout"))

    screened = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                                   out_dir=tmp_path / "b", require_peaks=True)
    assert screened["counts"]["RESCUE"] == base["counts"]["RESCUE"]
    assert screened["peak_screen"]["bodyparts"]["Snout"]["kept"] > 0


def test_flipped_path_with_peaks_far_off_the_line_refuses_the_rescues(tmp_path):
    """Same as test_a_sidecar_with_peaks_far_off_the_line_refuses_every_rescue
    but through overrides={"Snout": "ref"}, so the judged/corrected side is
    the REFERENCE camera and the sidecar must live on ref_h5. No existing test
    exercised require_peaks with an override at all before this."""
    calib, ref_h5, tgt_h5 = _build_pair(tmp_path, damage_side="ref")
    overrides = {"Snout": "ref"}
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    base = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                               out_dir=tmp_path / "a", overrides=overrides,
                               require_peaks=False)
    if base["counts"]["RESCUE"] == 0:
        pytest.skip("fixture produced no flipped rescues to screen")

    df, meta = rp.read_pose_h5(ref_h5)
    n = len(df)
    _sidecar_for(ref_h5, list(range(n)), meta["bodyparts"], [(9e4, 9e4)] * n)

    screened = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                                   out_dir=tmp_path / "b", overrides=overrides,
                                   require_peaks=True)
    assert screened["counts"]["RESCUE"] == 0
    assert screened["counts"]["NO_EVIDENCE"] == base["counts"]["RESCUE"]
    assert screened["peak_screen"]["refused"] == base["counts"]["RESCUE"]


def test_flipped_path_with_true_peaks_keeps_the_rescues(tmp_path):
    """Decisive positive control for the flipped path.

    With overrides={"Snout": "ref"}, the correct selectors are
    judged_peaks=peaks_by_side["ref"], cam_judged=cam_ref, u_inducing=u_tgt,
    F_judged=F["ref"]. Feeding the sidecar the TRUE ref-view marker position
    means: with the correct selectors the peak's epipolar distance is ~0 (it
    IS the point that made the rescue's own distance small) and the rescue is
    KEPT; swap any one of F_judged/cam_judged/u_inducing to its opposite and
    the peak gets measured in the wrong space or against the wrong line, the
    distance jumps past t_ok, and the rescue is wrongly refused. That is what
    makes this test fail under each of those three mutations individually
    (verified manually; see task-3-report.md)."""
    calib, ref_h5, tgt_h5 = _build_pair(tmp_path, damage_side="ref")
    overrides = {"Snout": "ref"}
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    base = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                               out_dir=tmp_path / "a", overrides=overrides,
                               require_peaks=False)
    if base["counts"]["RESCUE"] == 0:
        pytest.skip("fixture produced no flipped rescues to screen")

    df, meta = rp.read_pose_h5(ref_h5)
    n = len(df)
    _sidecar_for(ref_h5, list(range(n)), meta["bodyparts"],
                 _true_xy(ref_h5, "Snout"))

    screened = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                                   out_dir=tmp_path / "b", overrides=overrides,
                                   require_peaks=True)
    assert screened["counts"]["RESCUE"] == base["counts"]["RESCUE"]
    assert screened["peak_screen"]["bodyparts"]["Snout"]["kept"] > 0


def test_the_screen_never_changes_a_marker_position(tmp_path):
    """Veto-only guarantee, checked against the real no-op path.

    p_xy (the sidecar peak coordinates) only ever reaches
    ec.epipolar_distance; apply_verdicts gets xy_j straight from the source
    DataFrame, so there is no code path by which a peak's coordinates could
    reach the output h5 — hunting for a sentinel value in the output (the
    previous version of this test) can never fail regardless of what the
    screen does. The actual guarantee is comparative: x/y for every bodypart,
    in BOTH output h5s, must be identical to the unscreened run, even though
    the verdict codes differ (RESCUE -> NO_EVIDENCE on the refused frames).
    Only likelihood is allowed to differ there, since apply_verdicts lifts it
    to rescue_floor for RESCUE but passes it through unchanged for
    NO_EVIDENCE.
    """
    calib, ref_h5, tgt_h5 = _build_pair(tmp_path)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    base = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                               out_dir=tmp_path / "a", require_peaks=False)
    if base["counts"]["RESCUE"] == 0:
        pytest.skip("fixture produced no rescues to screen")

    df, meta = rp.read_pose_h5(tgt_h5)
    n = len(df)
    _sidecar_for(tgt_h5, list(range(n)), meta["bodyparts"], [(9e4, 9e4)] * n)

    screened = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                                   out_dir=tmp_path / "b", require_peaks=True)
    assert screened["counts"]["NO_EVIDENCE"] > 0  # the refusal actually happened

    base_ref_df, base_meta_ref = rp.read_pose_h5(base["outputs"]["ref_h5"])
    base_tgt_df, base_meta_tgt = rp.read_pose_h5(base["outputs"]["tgt_h5"])
    scr_ref_df, scr_meta_ref = rp.read_pose_h5(screened["outputs"]["ref_h5"])
    scr_tgt_df, scr_meta_tgt = rp.read_pose_h5(screened["outputs"]["tgt_h5"])

    for base_df, base_meta, scr_df, scr_meta in (
        (base_ref_df, base_meta_ref, scr_ref_df, scr_meta_ref),
        (base_tgt_df, base_meta_tgt, scr_tgt_df, scr_meta_tgt),
    ):
        b_sc, s_sc = base_meta["scorer"], scr_meta["scorer"]
        for bp in base_meta["bodyparts"]:
            np.testing.assert_array_equal(
                base_df[(b_sc, bp, "x")].to_numpy(),
                scr_df[(s_sc, bp, "x")].to_numpy(), err_msg=bp)
            np.testing.assert_array_equal(
                base_df[(b_sc, bp, "y")].to_numpy(),
                scr_df[(s_sc, bp, "y")].to_numpy(), err_msg=bp)

    b_sc, s_sc = base_meta_tgt["scorer"], scr_meta_tgt["scorer"]
    base_like = base_tgt_df[(b_sc, "Snout", "likelihood")].to_numpy()
    scr_like = scr_tgt_df[(s_sc, "Snout", "likelihood")].to_numpy()
    assert not np.array_equal(base_like, scr_like)


def test_summary_records_sidecar_snapshot_provenance(tmp_path):
    """A stale sidecar from an earlier snapshot is never validated against the
    pose h5 (the naming conventions differ and a brittle match would wrongly
    refuse valid sidecars) but its provenance must round-trip into the audit
    JSON so it is at least visible."""
    calib, ref_h5, tgt_h5 = _build_pair(tmp_path)
    df, meta = rp.read_pose_h5(tgt_h5)
    n = len(df)
    _sidecar_for(tgt_h5, list(range(n)), meta["bodyparts"], [(9e4, 9e4)] * n)

    out = rp.run_reprojection(ref_h5, tgt_h5, calib, "cam_0", "cam_1",
                              out_dir=tmp_path, require_peaks=True)
    assert out["peak_screen"]["snapshot"] == {"ref": None, "tgt": "s.pt"}


def test_verdict_names_cover_the_two_new_codes():
    from dlc_3d_bp import epipolar_core as ec
    assert ec.VERDICT_NAMES[6] == "NO_EVIDENCE"
    assert ec.VERDICT_NAMES[7] == "CORRECTED"

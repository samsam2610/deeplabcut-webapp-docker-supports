from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dlc_3d_bp.epipolar_core import Cam, project_point
from dlc_3d_bp.reprojection import (
    load_calibration,
    read_pose_h5,
    run_reprojection,
    write_pose_h5,
)

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


def test_load_calibration_builds_cams():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        cams = load_calibration(_write_calib(Path(td)))

    assert set(cams) == {"cam_0", "cam_1"}
    assert isinstance(cams["cam_0"], Cam)
    assert cams["cam_0"].K.shape == (3, 3)
    assert cams["cam_0"].K[0, 0] == pytest.approx(2382.07)
    assert cams["cam_1"].dist.shape == (5,)
    assert cams["cam_1"].size == (800, 600)
    assert cams["cam_1"].rvec[1] == pytest.approx(-0.4901)


def test_write_pose_h5_mirrors_the_source_contract(tmp_path):
    src = tmp_path / "a.h5"
    df = _make_df(np.ones((10, 2, 2), dtype=np.float32),
                  np.full((10, 2), 0.5, dtype=np.float32))
    _write_h5(src, df)

    got, meta = read_pose_h5(src)
    assert meta["key"] == "df_with_missing"
    assert meta["is_table"] is True
    assert meta["scorer"] == SCORER
    assert meta["bodyparts"] == BODYPARTS

    dst = tmp_path / "b.h5"
    write_pose_h5(got, meta, dst)
    back, meta2 = read_pose_h5(dst)
    assert meta2["key"] == meta["key"]
    assert meta2["is_table"] == meta["is_table"]
    assert list(back.columns.names) == ["scorer", "bodyparts", "coords"]
    assert set(map(str, back.dtypes)) == {"float32"}
    pd.testing.assert_frame_equal(got, back)


def test_run_reprojection_rescues_and_rejects(tmp_path):
    """Build a synthetic pair from the fixture calibration: 300 frames of a
    moving 3D point, exactly consistent in both views. Then damage the target
    view: frames 100-109 get a confident but geometrically impossible position,
    frames 200-209 keep the correct position but a low likelihood."""
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
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

    out = run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key="cam_0", tgt_cam_key="cam_1", out_dir=tmp_path,
    )

    assert out["counts"]["REJECT"] >= 10
    assert out["counts"]["RESCUE"] >= 10

    # Both cameras get an output file, named identically apart from _cam{N}_.
    ref_out = tmp_path / "s_cam0_x_reprojected.h5"
    tgt_out = tmp_path / "s_cam1_x_reprojected.h5"
    assert ref_out.is_file() and tgt_out.is_file()
    assert ref_out.name.replace("_cam0_", "_cam1_") == tgt_out.name
    assert (tmp_path / "s_cam1_x_reprojected.json").is_file()
    assert (tmp_path / "s_cam1_x_reprojected.npz").is_file()

    # The reference file is a faithful copy.
    src_ref, _ = read_pose_h5(ref_h5)
    got_ref, _ = read_pose_h5(ref_out)
    pd.testing.assert_frame_equal(src_ref, got_ref)

    # Damaged frames are gone; low-confidence-but-correct frames are lifted.
    got_tgt, _ = read_pose_h5(tgt_out)
    snout = got_tgt[SCORER]["Snout"]
    assert snout["x"].iloc[100:110].isna().all()
    assert (snout["likelihood"].iloc[100:110] == 0).all()
    assert snout["x"].iloc[200:210].notna().all()
    assert (snout["likelihood"].iloc[200:210] >= 0.9).all()

    # Untouched frames keep their exact original coordinates.
    src_tgt, _ = read_pose_h5(tgt_h5)
    assert np.allclose(src_tgt[SCORER]["Snout"]["x"].iloc[0:50],
                       snout["x"].iloc[0:50], equal_nan=True)


def test_per_bodypart_override_corrects_the_other_file(tmp_path):
    """Flipping a bodypart means the REFERENCE camera is the one judged for it,
    so the correction must land in the reference output, not the target's."""
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    ref_cam, tgt_cam = cams["cam_0"], cams["cam_1"]

    n = 300
    t = np.linspace(0.0, 1.0, n)
    xyz = np.c_[10.0 + 2.0 * t, -5.0 + 2.0 * t, 250.0 + 5.0 * t]
    ref_xy = np.stack([project_point(ref_cam, xyz)] * 2, axis=1)
    tgt_xy = np.stack([project_point(tgt_cam, xyz)] * 2, axis=1)
    ref_lik = np.full((n, 2), 0.99, dtype=np.float32)
    tgt_lik = np.full((n, 2), 0.99, dtype=np.float32)

    # Damage the REFERENCE view's Snout, and flip Snout so it gets judged.
    ref_xy[100:110, 0] += 250.0

    ref_h5 = tmp_path / "s_cam0_x.h5"
    tgt_h5 = tmp_path / "s_cam1_x.h5"
    _write_h5(ref_h5, _make_df(ref_xy, ref_lik))
    _write_h5(tgt_h5, _make_df(tgt_xy, tgt_lik))

    run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key="cam_0", tgt_cam_key="cam_1", out_dir=tmp_path,
        overrides={"Snout": "ref"},
    )

    got_ref, _ = read_pose_h5(tmp_path / "s_cam0_x_reprojected.h5")
    got_tgt, _ = read_pose_h5(tmp_path / "s_cam1_x_reprojected.h5")

    # The flipped bodypart was corrected in the reference file...
    assert got_ref[SCORER]["Snout"]["x"].iloc[100:110].isna().all()
    # ...and the target's own Snout, which was never wrong, is untouched.
    src_tgt, _ = read_pose_h5(tgt_h5)
    assert np.allclose(
        src_tgt[SCORER]["Snout"]["x"].to_numpy(),
        got_tgt[SCORER]["Snout"]["x"].to_numpy(), equal_nan=True,
    )
    # The un-flipped bodypart still leaves the reference file alone.
    src_ref, _ = read_pose_h5(ref_h5)
    assert np.allclose(
        src_ref[SCORER]["Pellet"]["x"].to_numpy(),
        got_ref[SCORER]["Pellet"]["x"].to_numpy(), equal_nan=True,
    )


def test_run_reprojection_never_writes_beside_the_source_when_out_dir_given(tmp_path):
    calib = _write_calib(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    out.mkdir()

    cams = load_calibration(calib)
    n = 60
    xyz = np.c_[np.full(n, 10.0), np.full(n, -5.0), np.linspace(250, 260, n)]
    xy0 = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    xy1 = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    lik = np.full((n, 2), 0.99, dtype=np.float32)

    _write_h5(src / "s_cam0_x.h5", _make_df(xy0, lik))
    _write_h5(src / "s_cam1_x.h5", _make_df(xy1, lik))

    run_reprojection(
        ref_h5=src / "s_cam0_x.h5", tgt_h5=src / "s_cam1_x.h5",
        calib_path=calib, ref_cam_key="cam_0", tgt_cam_key="cam_1",
        out_dir=out,
    )
    assert not list(src.glob("*_reprojected.*"))
    assert (out / "s_cam1_x_reprojected.h5").is_file()


from dlc_3d_bp.reprojection import normalize_per_cam

CAMS = ("cam_0", "cam_1")


def test_normalize_per_cam_scalar_applies_to_every_camera():
    assert normalize_per_cam(0.6, 0.9, CAMS) == {"cam_0": 0.6, "cam_1": 0.6}


def test_normalize_per_cam_none_uses_the_default():
    assert normalize_per_cam(None, 0.9, CAMS) == {"cam_0": 0.9, "cam_1": 0.9}


def test_normalize_per_cam_dict_maps_each_camera():
    got = normalize_per_cam({"cam_0": 0.45, "cam_1": 0.8}, 0.9, CAMS)
    assert got == {"cam_0": 0.45, "cam_1": 0.8}


def test_normalize_per_cam_missing_key_falls_back_to_default():
    got = normalize_per_cam({"cam_0": 0.45}, 0.9, CAMS)
    assert got == {"cam_0": 0.45, "cam_1": 0.9}


def test_normalize_per_cam_rejects_unknown_camera():
    with pytest.raises(ValueError) as e:
        normalize_per_cam({"cam_9": 0.5}, 0.9, CAMS)
    assert "cam_9" in str(e.value)


def test_normalize_per_cam_rejects_out_of_range():
    for bad in (-0.1, 1.5):
        with pytest.raises(ValueError):
            normalize_per_cam(bad, 0.9, CAMS)
        with pytest.raises(ValueError):
            normalize_per_cam({"cam_0": bad}, 0.9, CAMS)


def test_normalize_per_cam_rejects_non_numeric():
    with pytest.raises(ValueError):
        normalize_per_cam("high", 0.9, CAMS)
    with pytest.raises(ValueError):
        normalize_per_cam({"cam_0": "high"}, 0.9, CAMS)


def test_normalize_per_cam_accepts_the_range_endpoints():
    assert normalize_per_cam(0.0, 0.9, CAMS)["cam_0"] == 0.0
    assert normalize_per_cam(1.0, 0.9, CAMS)["cam_1"] == 1.0


def test_per_camera_rescue_floor_applies_to_the_judged_camera(tmp_path):
    """cam_0 is judged here, so its own rescue_floor must be written — not
    cam_1's."""
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    n = 300
    t = np.linspace(0.0, 1.0, n)
    xyz = np.c_[10.0 + 2.0 * t, -5.0 + 2.0 * t, 250.0 + 5.0 * t]
    ref_xy = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    tgt_xy = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    ref_lik = np.full((n, 2), 0.99, dtype=np.float32)
    tgt_lik = np.full((n, 2), 0.99, dtype=np.float32)
    tgt_lik[100:150, 0] = 0.10          # correct place, low confidence -> rescue

    ref_h5 = tmp_path / "s_cam1_x.h5"
    tgt_h5 = tmp_path / "s_cam0_x.h5"
    _write_h5(ref_h5, _make_df(ref_xy, ref_lik))
    _write_h5(tgt_h5, _make_df(tgt_xy, tgt_lik))

    out = run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key="cam_1", tgt_cam_key="cam_0", out_dir=tmp_path,
        rescue_floor={"cam_0": 0.77, "cam_1": 0.95},
    )
    assert out["counts"]["RESCUE"] > 0
    got, _ = read_pose_h5(out["outputs"]["tgt_h5"])
    lik = got[SCORER]["Snout"]["likelihood"].to_numpy()
    rescued = lik[100:150]
    assert np.allclose(rescued, 0.77, atol=1e-6), (
        "judged camera cam_0's floor (0.77) must be used, not cam_1's 0.95"
    )


def test_per_camera_values_are_recorded_in_the_audit(tmp_path):
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    n = 80
    xyz = np.c_[np.full(n, 10.0), np.full(n, -5.0), np.linspace(250, 260, n)]
    xy1 = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    xy0 = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    lik = np.full((n, 2), 0.99, dtype=np.float32)
    _write_h5(tmp_path / "s_cam1_x.h5", _make_df(xy1, lik))
    _write_h5(tmp_path / "s_cam0_x.h5", _make_df(xy0, lik))

    out = run_reprojection(
        ref_h5=tmp_path / "s_cam1_x.h5", tgt_h5=tmp_path / "s_cam0_x.h5",
        calib_path=calib, ref_cam_key="cam_1", tgt_cam_key="cam_0",
        out_dir=tmp_path, gate_ref={"cam_0": 0.4, "cam_1": 0.7},
    )
    assert out["config"]["gate_ref"] == {"cam_0": 0.4, "cam_1": 0.7}
    # A scalar is normalized too, so the audit always shows per-camera values.
    assert out["config"]["low_tgt"] == {"cam_0": 0.6, "cam_1": 0.6}


def test_scalar_parameters_still_work(tmp_path):
    """Back-compat: scripts/verify_reprojection.py and the existing route tests
    pass scalars."""
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    n = 80
    xyz = np.c_[np.full(n, 10.0), np.full(n, -5.0), np.linspace(250, 260, n)]
    xy1 = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    xy0 = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    lik = np.full((n, 2), 0.99, dtype=np.float32)
    _write_h5(tmp_path / "s_cam1_x.h5", _make_df(xy1, lik))
    _write_h5(tmp_path / "s_cam0_x.h5", _make_df(xy0, lik))

    out = run_reprojection(
        ref_h5=tmp_path / "s_cam1_x.h5", tgt_h5=tmp_path / "s_cam0_x.h5",
        calib_path=calib, ref_cam_key="cam_1", tgt_cam_key="cam_0",
        out_dir=tmp_path, gate_ref=0.5, low_tgt=0.5,
        high_conf=0.8, rescue_floor=0.85,
    )
    assert out["config"]["gate_ref"] == {"cam_0": 0.5, "cam_1": 0.5}
    assert out["config"]["rescue_floor"] == {"cam_0": 0.85, "cam_1": 0.85}


def test_flipped_bodypart_uses_the_flipped_judged_camera_floor(tmp_path):
    """The riskiest path: a per-bodypart override AND per-camera parameters.

    With ref_cam=cam_1, a bodypart flipped to "ref" makes cam_1 the JUDGED
    camera, so its rescues must carry cam_1's rescue_floor (0.95), not cam_0's
    (0.77). Getting role_ref/role_tgt backwards in the flipped branch would
    silently apply the wrong camera's thresholds and be near-invisible in the
    output — no other test exercises this combination.
    """
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    n = 300
    t = np.linspace(0.0, 1.0, n)
    xyz = np.c_[10.0 + 2.0 * t, -5.0 + 2.0 * t, 250.0 + 5.0 * t]
    ref_xy = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    tgt_xy = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    ref_lik = np.full((n, 2), 0.99, dtype=np.float32)
    tgt_lik = np.full((n, 2), 0.99, dtype=np.float32)
    # Snout is correctly placed in cam_1 but under-confident -> rescue candidate
    # in the file that the flip makes the judged one.
    ref_lik[100:150, 0] = 0.10

    ref_h5 = tmp_path / "s_cam1_x.h5"
    tgt_h5 = tmp_path / "s_cam0_x.h5"
    _write_h5(ref_h5, _make_df(ref_xy, ref_lik))
    _write_h5(tgt_h5, _make_df(tgt_xy, tgt_lik))

    out = run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key="cam_1", tgt_cam_key="cam_0", out_dir=tmp_path,
        overrides={"Snout": "ref"},
        rescue_floor={"cam_0": 0.77, "cam_1": 0.95},
    )
    assert out["counts"]["RESCUE"] > 0

    got_ref, _ = read_pose_h5(out["outputs"]["ref_h5"])
    rescued = got_ref[SCORER]["Snout"]["likelihood"].to_numpy()[100:150]
    assert np.allclose(rescued, 0.95, atol=1e-6), (
        "flipped bodypart must use cam_1's floor (0.95, the judged camera under "
        "the flip), not cam_0's 0.77 — role_ref/role_tgt are reversed"
    )


# ── Idempotent reprojection: no _reprojected_reprojected ────────────────────
# See docs — reprojecting an already-reprojected layer used to (a) treat a
# rescued marker's raised likelihood as fresh confident evidence, silently
# compounding corrections, and (b) chain the suffix into
# X_reprojected_reprojected.h5. _normalize_reproject_input redirects an
# already-reprojected input to its source layer so _out_path regenerates the
# SAME _reprojected name, replacing it rather than chaining.

from dlc_3d_bp.reprojection import _normalize_reproject_input, _source_layer_for


def test_source_layer_for_plain_path_is_untouched():
    assert _source_layer_for(Path("/x/s_cam0_x.h5")) is None


def test_source_layer_for_already_reprojected_strips_the_suffix():
    got = _source_layer_for(Path("/x/s_cam0_x_reprojected.h5"))
    assert got == Path("/x/s_cam0_x.h5")


def test_source_layer_for_is_pure_and_does_not_check_existence():
    """Path arithmetic only — must not touch the filesystem. Verified by
    pointing at a source that does not exist and getting the computed path
    back anyway (existence is the caller's concern)."""
    got = _source_layer_for(Path("/does/not/exist/s_cam0_x_reprojected.h5"))
    assert got == Path("/does/not/exist/s_cam0_x.h5")


def test_source_layer_for_only_strips_a_trailing_suffix():
    """A stem that merely contains "_reprojected" in the middle (not as a
    trailing suffix) must be left alone."""
    assert _source_layer_for(Path("/x/s_cam0_reprojected_extra.h5")) is None


def test_normalize_reproject_input_plain_path_passes_through(tmp_path):
    p = tmp_path / "s_cam0_x.h5"
    p.write_text("stub")
    assert _normalize_reproject_input(p) == p


def test_normalize_reproject_input_redirects_to_an_existing_source(tmp_path):
    source = tmp_path / "s_cam0_x.h5"
    source.write_text("stub")
    reprojected = tmp_path / "s_cam0_x_reprojected.h5"
    reprojected.write_text("stub-out")
    assert _normalize_reproject_input(reprojected) == source


def test_normalize_reproject_input_raises_a_clear_error_on_a_missing_source(tmp_path):
    """Must NOT fall back to chaining onto the reprojected file itself."""
    reprojected = tmp_path / "s_cam0_x_reprojected.h5"
    reprojected.write_text("stub-out")
    with pytest.raises(FileNotFoundError) as exc:
        _normalize_reproject_input(reprojected)
    msg = str(exc.value)
    assert str(reprojected) in msg, "error must name the reprojected path that was selected"
    assert str(tmp_path / "s_cam0_x.h5") in msg, "error must name the missing source path"


def test_reprojecting_an_already_reprojected_layer_yields_exactly_one_output(tmp_path):
    """Feeding *_reprojected.h5 back in must NOT produce
    *_reprojected_reprojected.h5 — it must re-read the source and replace the
    existing _reprojected output, so there is exactly one output file for
    each camera afterward."""
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    n = 120
    xyz = np.c_[np.full(n, 10.0), np.full(n, -5.0), np.linspace(250, 260, n)]
    xy0 = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    xy1 = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    lik = np.full((n, 2), 0.99, dtype=np.float32)
    lik[10:20, 0] = 0.10  # a rescue candidate, so the first pass actually raises a likelihood

    ref_h5 = tmp_path / "s_cam0_x.h5"
    tgt_h5 = tmp_path / "s_cam1_x.h5"
    _write_h5(ref_h5, _make_df(xy0, lik))
    _write_h5(tgt_h5, _make_df(xy1, lik))

    first = run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key="cam_0", tgt_cam_key="cam_1", out_dir=tmp_path,
        rescue_floor=0.9,
    )
    ref_out = Path(first["outputs"]["ref_h5"])
    tgt_out = Path(first["outputs"]["tgt_h5"])
    assert ref_out.name == "s_cam0_x_reprojected.h5"
    assert tgt_out.name == "s_cam1_x_reprojected.h5"
    first_tgt, _ = read_pose_h5(tgt_out)
    first_rescued_lik = first_tgt[SCORER]["Pellet"]["likelihood"].to_numpy()[10:20].copy()

    # Re-run FEEDING THE REPROJECTED OUTPUT BACK IN, exactly what the card
    # does when the displayed kinematic layer is already a reprojection.
    second = run_reprojection(
        ref_h5=ref_out, tgt_h5=tgt_out, calib_path=calib,
        ref_cam_key="cam_0", tgt_cam_key="cam_1", out_dir=tmp_path,
        rescue_floor=0.9,
    )

    # Exactly one output file per camera — no _reprojected_reprojected chain.
    outs = sorted(p.name for p in tmp_path.glob("*_reprojected*.h5"))
    assert outs == ["s_cam0_x_reprojected.h5", "s_cam1_x_reprojected.h5"], (
        f"expected exactly one output per camera, got {outs}"
    )
    assert not list(tmp_path.glob("*_reprojected_reprojected*"))

    # The second pass re-read the SOURCE (pre-reprojection) file, not the
    # reprojected one it was handed — recorded explicitly in the audit.
    assert second["config"]["ref_h5"] == str(ref_h5)
    assert second["config"]["tgt_h5"] == str(tgt_h5)
    assert second["config"]["ref_h5_requested"] == str(ref_out)
    assert second["config"]["tgt_h5_requested"] == str(tgt_out)

    # Compounding check: the already-rescued likelihood (raised to 0.9 by the
    # first pass) must NOT be treated as fresh confident evidence and pushed
    # again — the second pass's rescued values must match the first pass's,
    # not some further-altered value.
    second_tgt, _ = read_pose_h5(Path(second["outputs"]["tgt_h5"]))
    second_rescued_lik = second_tgt[SCORER]["Pellet"]["likelihood"].to_numpy()[10:20]
    assert np.allclose(second_rescued_lik, first_rescued_lik, atol=1e-6), (
        "re-reprojecting must re-derive from the untouched source, not compound "
        "corrections already baked into the previous _reprojected output"
    )


def test_reprojecting_an_already_reprojected_layer_with_missing_source_raises(tmp_path):
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    n = 40
    xyz = np.c_[np.full(n, 10.0), np.full(n, -5.0), np.linspace(250, 260, n)]
    xy0 = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    xy1 = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    lik = np.full((n, 2), 0.99, dtype=np.float32)

    ref_h5 = tmp_path / "s_cam0_x.h5"
    tgt_h5 = tmp_path / "s_cam1_x.h5"
    _write_h5(ref_h5, _make_df(xy0, lik))
    _write_h5(tgt_h5, _make_df(xy1, lik))

    out = run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key="cam_0", tgt_cam_key="cam_1", out_dir=tmp_path,
    )
    ref_out = Path(out["outputs"]["ref_h5"])
    ref_h5.unlink()  # the source is gone; only the reprojected output remains

    with pytest.raises(FileNotFoundError):
        run_reprojection(
            ref_h5=ref_out, tgt_h5=Path(out["outputs"]["tgt_h5"]), calib_path=calib,
            ref_cam_key="cam_0", tgt_cam_key="cam_1", out_dir=tmp_path,
        )

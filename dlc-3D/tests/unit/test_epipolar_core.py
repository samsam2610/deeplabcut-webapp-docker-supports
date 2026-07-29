import numpy as np
import pytest

from dlc_3d_bp.epipolar_core import (
    Cam,
    epipolar_distance,
    extrinsics,
    fundamental_matrix,
    project_point,
    undistort_to_normalized,
    undistort_to_pixels,
)


def make_cam(name="0", f=1000.0, cx=400.0, cy=300.0, rvec=(0, 0, 0),
             tvec=(0, 0, 0), dist=(0, 0, 0, 0, 0)):
    """Synthetic pinhole camera. Defaults: at the world origin, no distortion."""
    K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], dtype=float)
    return Cam(
        name=name, K=K, dist=np.asarray(dist, dtype=float),
        rvec=np.asarray(rvec, dtype=float), tvec=np.asarray(tvec, dtype=float),
        size=(800, 600),
    )


def test_extrinsics_identity_for_zero_rvec():
    R, t = extrinsics(make_cam(rvec=(0, 0, 0), tvec=(1, 2, 3)))
    assert np.allclose(R, np.eye(3))
    assert np.allclose(t, [1, 2, 3])


def test_fundamental_matrix_is_rank_two():
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    F = fundamental_matrix(ref, tgt)
    assert F.shape == (3, 3)
    sv = np.linalg.svd(F, compute_uv=False)
    # A valid fundamental matrix has exactly rank 2: its smallest
    # singular value must be negligible next to the largest.
    assert sv[2] / sv[0] < 1e-10


def test_fundamental_matrix_is_zero_for_identical_cameras():
    ref = make_cam("0")
    F = fundamental_matrix(ref, make_cam("1"))
    assert np.allclose(F, 0.0)


def test_undistort_is_identity_without_distortion():
    cam = make_cam(dist=(0, 0, 0, 0, 0))
    pts = np.array([[400.0, 300.0], [123.4, 567.8]])
    assert np.allclose(undistort_to_pixels(cam, pts), pts, atol=1e-6)


def test_undistort_to_pixels_differs_from_normalized():
    """Regression guard: cv2.undistortPoints without P=K returns normalized
    coordinates. Mixing those with a pixel-space F yields a near-constant
    residual that looks like real data. These two must not be confused."""
    cam = make_cam(dist=(-0.15, 0, 0, 0, 0))
    pts = np.array([[600.0, 500.0]])
    pix = undistort_to_pixels(cam, pts)
    nrm = undistort_to_normalized(cam, pts)
    assert np.linalg.norm(pix - nrm) > 100.0
    # Converting normalized back through K must reproduce the pixel form.
    h = np.array([nrm[0, 0], nrm[0, 1], 1.0])
    assert np.allclose((cam.K @ h)[:2], pix[0], atol=1e-6)


def test_triangulated_correspondence_has_zero_epipolar_distance():
    """A projected 3D point is an exact correspondence, so its residual is 0."""
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    xyz = np.array([[10.0, -5.0, 500.0], [0.0, 0.0, 800.0]])
    p_ref = project_point(ref, xyz)
    p_tgt = project_point(tgt, xyz)
    d = epipolar_distance(fundamental_matrix(ref, tgt), p_ref, p_tgt)
    assert np.allclose(d, 0.0, atol=1e-6)


def test_perpendicular_displacement_gives_that_distance():
    """Displacing the target point by delta perpendicular to its epipolar line
    must produce a residual of exactly delta."""
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    xyz = np.array([[10.0, -5.0, 500.0]])
    p_ref = project_point(ref, xyz)
    p_tgt = project_point(tgt, xyz)
    F = fundamental_matrix(ref, tgt)
    line = F @ np.array([p_ref[0, 0], p_ref[0, 1], 1.0])
    normal = line[:2] / np.linalg.norm(line[:2])
    for delta in (0.5, 7.0, 42.0):
        moved = p_tgt + delta * normal
        d = epipolar_distance(F, p_ref, moved)
        assert np.allclose(d, delta, atol=1e-6)


def test_epipolar_distance_propagates_nan():
    ref, tgt = make_cam("0"), make_cam("1", tvec=(100, 0, 0))
    F = fundamental_matrix(ref, tgt)
    d = epipolar_distance(F, np.array([[np.nan, np.nan]]), np.array([[1.0, 2.0]]))
    assert np.isnan(d[0])


def test_epiline_endpoints_lie_on_the_line_and_inside_the_image():
    from dlc_3d_bp.epipolar_core import epiline_endpoints
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    F = fundamental_matrix(ref, tgt)
    xyz = np.array([[10.0, -5.0, 500.0]])
    p_ref = project_point(ref, xyz)
    w, h = tgt.size
    seg = epiline_endpoints(F, p_ref[0], w, h)
    assert seg is not None
    line = F @ np.array([p_ref[0, 0], p_ref[0, 1], 1.0])
    nrm = np.hypot(line[0], line[1])
    assert nrm > 0
    for (x, y) in seg:
        assert -1e-6 <= x <= w + 1e-6
        assert -1e-6 <= y <= h + 1e-6
        # Normalised point-line distance: the endpoint must lie ON the line.
        assert abs(line[0] * x + line[1] * y + line[2]) / nrm < 1e-6


def test_epiline_endpoints_passes_through_the_true_correspondence():
    from dlc_3d_bp.epipolar_core import epiline_endpoints
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    F = fundamental_matrix(ref, tgt)
    xyz = np.array([[10.0, -5.0, 500.0]])
    p_ref = project_point(ref, xyz)
    p_tgt = project_point(tgt, xyz)[0]
    (x1, y1), (x2, y2) = epiline_endpoints(F, p_ref[0], *tgt.size)
    # Distance from the true target point to the segment's infinite line is 0.
    dx, dy = x2 - x1, y2 - y1
    norm = np.hypot(dx, dy)
    cross = abs(dx * (y1 - p_tgt[1]) - dy * (x1 - p_tgt[0])) / norm
    assert cross < 1e-3


def test_epiline_endpoints_returns_none_for_nan_input():
    from dlc_3d_bp.epipolar_core import epiline_endpoints
    ref, tgt = make_cam("0"), make_cam("1", tvec=(100, 0, 0))
    F = fundamental_matrix(ref, tgt)
    assert epiline_endpoints(F, np.array([np.nan, np.nan]), 800, 600) is None


def test_triangulate_recovers_known_3d_points():
    from dlc_3d_bp.epipolar_core import triangulate_dlt
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    xyz = np.array([[10.0, -5.0, 500.0], [0.0, 0.0, 800.0], [-30.0, 20.0, 650.0]])
    got = triangulate_dlt(ref, tgt, project_point(ref, xyz), project_point(tgt, xyz))
    assert got.shape == (3, 3)
    assert np.allclose(got, xyz, atol=1e-4)


def test_triangulate_recovers_points_with_distortion():
    from dlc_3d_bp.epipolar_core import triangulate_dlt
    ref = make_cam("0", dist=(-0.035, 0, 0, 0, 0))
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0), dist=(-0.15, 0, 0, 0, 0))
    xyz = np.array([[10.0, -5.0, 500.0], [-30.0, 20.0, 650.0]])
    got = triangulate_dlt(ref, tgt, project_point(ref, xyz), project_point(tgt, xyz))
    assert np.allclose(got, xyz, atol=1e-3)


def test_triangulate_returns_nan_rows_for_nan_input():
    from dlc_3d_bp.epipolar_core import triangulate_dlt
    ref = make_cam("0")
    tgt = make_cam("1", tvec=(100, 0, 0))
    a = np.array([[400.0, 300.0], [np.nan, np.nan]])
    b = np.array([[410.0, 300.0], [410.0, 300.0]])
    got = triangulate_dlt(ref, tgt, a, b)
    assert np.isfinite(got[0]).all()
    assert np.isnan(got[1]).all()


def test_triangulate_handles_large_batches():
    from dlc_3d_bp.epipolar_core import triangulate_dlt
    ref = make_cam("0")
    tgt = make_cam("1", rvec=(0, 0.3, 0), tvec=(100, 0, 0))
    rng = np.random.default_rng(0)
    xyz = np.c_[
        rng.uniform(-50, 50, 50_000),
        rng.uniform(-50, 50, 50_000),
        rng.uniform(400, 900, 50_000),
    ]
    got = triangulate_dlt(ref, tgt, project_point(ref, xyz), project_point(tgt, xyz))
    assert np.nanmax(np.abs(got - xyz)) < 1e-3


from dlc_3d_bp.epipolar_core import DEFAULT_T_BAD, DEFAULT_T_OK, auto_threshold


def _highconf(n, d_values):
    """n high-confidence pairs carrying the given residuals."""
    return np.asarray(d_values), np.ones(n), np.ones(n)


def test_auto_threshold_recovers_injected_median_and_mad():
    rng = np.random.default_rng(1)
    d = np.abs(rng.normal(0.0, 2.0, 5000)) + 3.0
    stats = auto_threshold(*_highconf(5000, d), k1=3.0, k2=8.0)
    assert stats["threshold_source"] == "self"
    assert abs(stats["med"] - np.median(d)) < 1e-9
    expected_mad = 1.4826 * np.median(np.abs(d - np.median(d)))
    assert abs(stats["mad"] - expected_mad) < 1e-9
    assert abs(stats["t_ok"] - (stats["med"] + 3.0 * stats["mad"])) < 1e-9
    assert abs(stats["t_bad"] - (stats["med"] + 8.0 * stats["mad"])) < 1e-9


def test_auto_threshold_uses_only_high_confidence_pairs():
    """Low-confidence junk must not move the estimate."""
    d = np.concatenate([np.full(1000, 1.0), np.full(1000, 900.0)])
    lik_ref = np.concatenate([np.ones(1000), np.ones(1000)])
    lik_tgt = np.concatenate([np.ones(1000), np.zeros(1000)])
    stats = auto_threshold(d, lik_ref, lik_tgt, high_conf=0.9)
    assert stats["n_highconf"] == 1000
    assert abs(stats["med"] - 1.0) < 1e-9


def test_auto_threshold_falls_back_to_pooled_when_too_few_samples():
    d, lr, lt = _highconf(50, np.full(50, 4.0))
    pooled = {"med": 2.0, "mad": 0.5}
    stats = auto_threshold(d, lr, lt, min_n=200, k1=3.0, k2=8.0, pooled=pooled)
    assert stats["threshold_source"] == "pooled"
    assert abs(stats["t_ok"] - (2.0 + 3.0 * 0.5)) < 1e-9


def test_auto_threshold_falls_back_to_defaults_without_pooled():
    d, lr, lt = _highconf(5, np.full(5, 4.0))
    stats = auto_threshold(d, lr, lt, min_n=200, pooled=None)
    assert stats["threshold_source"] == "default"
    assert stats["t_ok"] == DEFAULT_T_OK
    assert stats["t_bad"] == DEFAULT_T_BAD


def test_auto_threshold_ignores_nan_residuals():
    d = np.array([1.0, np.nan, 1.0, 1.0])
    stats = auto_threshold(d, np.ones(4), np.ones(4), min_n=1)
    assert stats["n_highconf"] == 3


def test_auto_threshold_survives_zero_mad():
    """Identical residuals give mad == 0; thresholds must stay finite and
    ordered so classification cannot degenerate."""
    d, lr, lt = _highconf(500, np.full(500, 2.0))
    stats = auto_threshold(d, lr, lt)
    assert np.isfinite(stats["t_ok"]) and np.isfinite(stats["t_bad"])
    assert stats["t_ok"] <= stats["t_bad"]

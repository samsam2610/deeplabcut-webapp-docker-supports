import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from src import stereo

CAL = """
[cam_0]
name = "0"
size = [ 800, 600,]
matrix = [ [ 2589.6, 0.0, 399.5,], [ 0.0, 2589.6, 299.5,], [ 0.0, 0.0, 1.0,],]
distortions = [ -0.465, 0.0, 0.0, 0.0, 0.0,]
rotation = [ 0.0024, 0.0005, -0.0129,]
translation = [ -0.153, 0.882, -13.902,]

[cam_1]
name = "1"
size = [ 800, 600,]
matrix = [ [ 2505.2, 0.0, 399.5,], [ 0.0, 2505.2, 299.5,], [ 0.0, 0.0, 1.0,],]
distortions = [ -0.483, 0.0, 0.0, 0.0, 0.0,]
rotation = [ 0.0476, -0.6199, 0.0102,]
translation = [ 200.9, 26.7, 143.1,]
"""


@pytest.fixture
def cal(tmp_path):
    p = tmp_path / "calibration.toml"
    p.write_text(CAL)
    return stereo.load(p)


def test_loads_both_cameras(cal):
    assert cal.cam0.K.shape == (3, 3) and cal.cam1.K.shape == (3, 3)
    assert cal.cam0.R.shape == (3, 3) and cal.cam0.t.shape == (3, 1)


def test_projection_matrix_shape(cal):
    assert cal.cam0.P.shape == (3, 4)


def test_triangulation_round_trips_a_known_point(cal):
    # Project a 3D point into both views, triangulate it back, expect the same
    # point. Guards the undistort/projection conventions, which are easy to get
    # subtly wrong and would bias every 3D gate.
    X = np.array([[1.6, 10.0, 261.7]])
    p0, _ = cv2.projectPoints(X, cv2.Rodrigues(cal.cam0.R)[0], cal.cam0.t,
                              cal.cam0.K, cal.cam0.dist)
    p1, _ = cv2.projectPoints(X, cv2.Rodrigues(cal.cam1.R)[0], cal.cam1.t,
                              cal.cam1.K, cal.cam1.dist)
    back = cal.triangulate(p0.reshape(-1, 2), p1.reshape(-1, 2))
    assert np.allclose(back, X, atol=1e-2)


def test_distance_to_reference():
    d = stereo.distance_to([[0, 0, 0], [3, 4, 0]], [0, 0, 0])
    assert np.allclose(d, [0.0, 5.0])


def test_epiline_has_three_coefficients(cal):
    lines = cal.epiline_in_cam1([[400.0, 380.0]])
    assert lines.shape == (1, 3)


def test_epiline_passes_through_the_true_correspondence(cal):
    # The whole point of the epipolar constraint: the partner view's true match
    # must lie on the line, so a candidate far off it can be rejected.
    X = np.array([[1.6, 10.0, 261.7]])
    p0, _ = cv2.projectPoints(X, cv2.Rodrigues(cal.cam0.R)[0], cal.cam0.t,
                              cal.cam0.K, cal.cam0.dist)
    p1, _ = cv2.projectPoints(X, cv2.Rodrigues(cal.cam1.R)[0], cal.cam1.t,
                              cal.cam1.K, cal.cam1.dist)
    a, b, c = cal.epiline_in_cam1(p0.reshape(-1, 2))[0]
    x, y = cv2.undistortPoints(p1, cal.cam1.K, cal.cam1.dist,
                               P=cal.cam1.K).reshape(2)
    assert abs(a * x + b * y + c) < 1.0        # pixels from the line


def test_missing_sections_are_rejected(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("[cam_0]\nname='0'\n")
    with pytest.raises(ValueError):
        stereo.load(p)


def test_find_for_project_returns_none_when_absent(tmp_path):
    assert stereo.find_for_project(tmp_path) is None


def test_find_for_project_locates_a_calibration(tmp_path):
    d = tmp_path / "labeled-data" / "sess"
    d.mkdir(parents=True)
    (d / "calibration.toml").write_text(CAL)
    assert stereo.find_for_project(tmp_path).name == "calibration.toml"


# ── epipolar residual, the paw gate's measurement ───────────────────────────
#
# Measured on 15770 labelled cam0/cam1 pairs to set epi_px = 15. See the
# 2026-08-12 spec: the proxy has to be a centroid of REAL joints. Left-Paw is a
# decoy placed randomly to stop DLC labelling that paw, so calibrating on it
# measured random placement and gave a threshold 5 px too loose.

def _cal():
    from pathlib import Path
    from src import stereo as st
    p = st.find_for_project(
        "/home/sam/data-disk/Parra-Data/DLC-Projects/DREADD-Ali-2026-01-07")
    return st.load(p) if p and Path(p).is_file() else None


def test_a_true_correspondence_has_a_small_residual():
    """Round-trip: project a 3D point into both views, then measure. Anything
    but ~0 means the residual and the triangulation disagree about the geometry."""
    import numpy as np
    cal = _cal()
    if cal is None:
        import pytest
        pytest.skip("no calibration in this environment")
    X = np.array([[1.68, 11.09, 278.81]])
    p0 = stereo.project(cal.cam0, X)
    p1 = stereo.project(cal.cam1, X)
    assert stereo.epipolar_residual(cal, p0, p1)[0] < 1.0


def test_a_mismatched_pair_has_a_large_residual():
    import numpy as np
    cal = _cal()
    if cal is None:
        import pytest
        pytest.skip("no calibration in this environment")
    X = np.array([[1.68, 11.09, 278.81]])
    p0 = stereo.project(cal.cam0, X)
    p1 = stereo.project(cal.cam1, X) + np.array([[0.0, 120.0]])
    assert stereo.epipolar_residual(cal, p0, p1)[0] > 15.0


def test_depth_along_the_ray_is_not_penalised():
    """Displacement ALONG the epipolar line is depth, which triangulation is
    for; only the perpendicular component means "different thing".

    The points must walk cam0's actual back-projected RAY. Varying Z with X and
    Y fixed does not: it moves off the ray, so cam0's pixel changes too and the
    residual is measured against the wrong line. That mistake made this look
    like a 2 px bug in `fundamental()`, which is exact over 400 random points.
    """
    import numpy as np
    cal = _cal()
    if cal is None:
        import pytest
        pytest.skip("no calibration in this environment")
    X = np.array([1.68, 11.09, 278.81])
    centre = -cal.cam0.R.T @ cal.cam0.t.reshape(3)      # cam0's centre in world
    p0 = stereo.project(cal.cam0, X.reshape(1, 3))
    for s in (0.9, 1.0, 1.1):
        on_ray = centre + s * (X - centre)
        q = stereo.project(cal.cam1, on_ray.reshape(1, 3))
        assert stereo.epipolar_residual(cal, p0, q)[0] < 0.5, f"scale {s}"


def test_residual_handles_many_points_at_once():
    import numpy as np
    cal = _cal()
    if cal is None:
        import pytest
        pytest.skip("no calibration in this environment")
    X = np.repeat(np.array([[1.68, 11.09, 278.81]]), 5, axis=0)
    out = stereo.epipolar_residual(cal, stereo.project(cal.cam0, X),
                                   stereo.project(cal.cam1, X))
    assert out.shape == (5,)

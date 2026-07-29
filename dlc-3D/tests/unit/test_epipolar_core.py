import numpy as np
import pytest

from dlc_3d_bp.epipolar_core import Cam, extrinsics, fundamental_matrix


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

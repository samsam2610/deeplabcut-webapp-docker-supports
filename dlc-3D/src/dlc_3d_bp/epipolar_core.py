"""Pure epipolar geometry for two-camera 2D marker verification.

No file or network I/O. Imports only numpy and cv2 so this module is
importable under the host's Python 3.9 test environment. In particular it must
NOT import anipose_src, whose cameras module requires numba, which is absent
from the dlc-3d container.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Verdict codes, written to the audit npz as uint8.
UNJUDGED = 0
REJECT = 1
RESCUE = 2
RESCUE_REJECTED = 3
CONFIRM = 4
AMBIGUOUS = 5

VERDICT_NAMES = {
    UNJUDGED: "UNJUDGED",
    REJECT: "REJECT",
    RESCUE: "RESCUE",
    RESCUE_REJECTED: "RESCUE_REJECTED",
    CONFIRM: "CONFIRM",
    AMBIGUOUS: "AMBIGUOUS",
}


@dataclass
class Cam:
    """One camera's intrinsics, distortion and world->camera pose."""

    name: str
    K: np.ndarray       # (3, 3) intrinsic matrix
    dist: np.ndarray    # (5,) cv2-order distortion: k1, k2, p1, p2, k3
    rvec: np.ndarray    # (3,) Rodrigues rotation, world -> camera
    tvec: np.ndarray    # (3,) translation, world -> camera
    size: tuple         # (width, height) in pixels


def extrinsics(cam: "Cam") -> "tuple[np.ndarray, np.ndarray]":
    """Return (R, t) mapping world coordinates into this camera's frame."""
    R, _ = cv2.Rodrigues(np.asarray(cam.rvec, dtype=float).reshape(3, 1))
    return R, np.asarray(cam.tvec, dtype=float).reshape(3)


def _skew(v: np.ndarray) -> np.ndarray:
    return np.array([
        [0.0, -v[2], v[1]],
        [v[2], 0.0, -v[0]],
        [-v[1], v[0], 0.0],
    ])


def fundamental_matrix(ref: "Cam", tgt: "Cam") -> np.ndarray:
    """Fundamental matrix mapping a point in `ref` to its epipolar line in `tgt`.

    Acts on UNDISTORTED pixel coordinates. Derived from calibration rather than
    from point correspondences, so it is exact up to calibration error.
    """
    R_ref, t_ref = extrinsics(ref)
    R_tgt, t_tgt = extrinsics(tgt)
    R = R_tgt @ R_ref.T
    t = t_tgt - R @ t_ref
    E = _skew(t) @ R
    return np.linalg.inv(tgt.K).T @ E @ np.linalg.inv(ref.K)

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


def _as_points(pts: np.ndarray) -> np.ndarray:
    return np.asarray(pts, dtype=np.float64).reshape(-1, 2)


def undistort_to_pixels(cam: "Cam", pts: np.ndarray) -> np.ndarray:
    """Undistort (N, 2) pixel coordinates, returning ideal-pinhole PIXELS.

    P=cam.K is essential: without it cv2 returns normalized coordinates.
    """
    p = _as_points(pts)
    out = np.full_like(p, np.nan)
    ok = np.isfinite(p).all(axis=1)
    if ok.any():
        u = cv2.undistortPoints(
            p[ok].reshape(-1, 1, 2), cam.K, np.asarray(cam.dist, dtype=float),
            P=cam.K,
        )
        out[ok] = u.reshape(-1, 2)
    return out


def undistort_to_normalized(cam: "Cam", pts: np.ndarray) -> np.ndarray:
    """Undistort (N, 2) pixel coordinates to NORMALIZED image coordinates."""
    p = _as_points(pts)
    out = np.full_like(p, np.nan)
    ok = np.isfinite(p).all(axis=1)
    if ok.any():
        u = cv2.undistortPoints(
            p[ok].reshape(-1, 1, 2), cam.K, np.asarray(cam.dist, dtype=float),
        )
        out[ok] = u.reshape(-1, 2)
    return out


def project_point(cam: "Cam", xyz: np.ndarray) -> np.ndarray:
    """Project (N, 3) world points to (N, 2) distorted pixels."""
    p = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    proj, _ = cv2.projectPoints(
        p, np.asarray(cam.rvec, dtype=float).reshape(3, 1),
        np.asarray(cam.tvec, dtype=float).reshape(3, 1),
        cam.K, np.asarray(cam.dist, dtype=float),
    )
    return proj.reshape(-1, 2)


def epipolar_distance(
    F: np.ndarray, ref_pix: np.ndarray, tgt_pix: np.ndarray
) -> np.ndarray:
    """Perpendicular distance from each target point to its epipolar line.

    Both inputs must already be UNDISTORTED pixels. Result is in target-view
    pixels. NaN in either input yields NaN.
    """
    a = _as_points(ref_pix)
    b = _as_points(tgt_pix)
    lines = np.c_[a, np.ones(len(a))] @ F.T
    num = np.abs(np.sum(lines * np.c_[b, np.ones(len(b))], axis=1))
    den = np.sqrt(lines[:, 0] ** 2 + lines[:, 1] ** 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        return num / np.where(den > 1e-12, den, np.nan)


def epiline_endpoints(
    F: np.ndarray, ref_pix_point: np.ndarray, width: int, height: int
) -> "tuple | None":
    """Clip the epipolar line of one undistorted reference point to the target
    image rectangle.

    Returns ((x1, y1), (x2, y2)) or None when the input is not finite, the line
    is degenerate, or the line misses the image.
    """
    p = np.asarray(ref_pix_point, dtype=np.float64).reshape(2)
    if not np.isfinite(p).all():
        return None
    a, b, c = F @ np.array([p[0], p[1], 1.0])
    if not np.isfinite([a, b, c]).all() or (abs(a) < 1e-12 and abs(b) < 1e-12):
        return None

    hits = []
    if abs(b) > 1e-12:                      # intersect left and right edges
        for x in (0.0, float(width)):
            y = -(a * x + c) / b
            if -1e-9 <= y <= height + 1e-9:
                hits.append((x, y))
    if abs(a) > 1e-12:                      # intersect top and bottom edges
        for y in (0.0, float(height)):
            x = -(b * y + c) / a
            if -1e-9 <= x <= width + 1e-9:
                hits.append((x, y))
    if len(hits) < 2:
        return None

    # Keep the two most distant hits; corner cases produce duplicates.
    best, far = None, -1.0
    for i in range(len(hits)):
        for j in range(i + 1, len(hits)):
            d = np.hypot(hits[i][0] - hits[j][0], hits[i][1] - hits[j][1])
            if d > far:
                far, best = d, (hits[i], hits[j])
    if far <= 1e-9:
        return None
    return best


def triangulate_dlt(
    ref: "Cam", tgt: "Cam", ref_pix: np.ndarray, tgt_pix: np.ndarray
) -> np.ndarray:
    """Triangulate correspondences into world coordinates by batched DLT.

    Inputs are (N, 2) DISTORTED pixels; undistortion to normalized coordinates
    happens here. Rows with NaN in either view come back as NaN.
    """
    a = undistort_to_normalized(ref, ref_pix)
    b = undistort_to_normalized(tgt, tgt_pix)
    n = len(a)
    out = np.full((n, 3), np.nan)
    ok = np.isfinite(a).all(axis=1) & np.isfinite(b).all(axis=1)
    if not ok.any():
        return out

    R_ref, t_ref = extrinsics(ref)
    R_tgt, t_tgt = extrinsics(tgt)
    P_ref = np.hstack([R_ref, t_ref.reshape(3, 1)])
    P_tgt = np.hstack([R_tgt, t_tgt.reshape(3, 1)])

    ua, ub = a[ok], b[ok]
    m = len(ua)
    A = np.empty((m, 4, 4))
    A[:, 0] = ua[:, 0:1] * P_ref[2] - P_ref[0]
    A[:, 1] = ua[:, 1:2] * P_ref[2] - P_ref[1]
    A[:, 2] = ub[:, 0:1] * P_tgt[2] - P_tgt[0]
    A[:, 3] = ub[:, 1:2] * P_tgt[2] - P_tgt[1]

    # Smallest right singular vector per point is the homogeneous solution.
    _, _, vt = np.linalg.svd(A)
    h = vt[:, 3, :]
    with np.errstate(invalid="ignore", divide="ignore"):
        xyz = h[:, :3] / h[:, 3:4]
    xyz[~np.isfinite(xyz).all(axis=1)] = np.nan
    out[ok] = xyz
    return out

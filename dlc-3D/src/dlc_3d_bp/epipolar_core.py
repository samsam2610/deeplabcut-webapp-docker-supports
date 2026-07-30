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


DEFAULT_T_OK = 10.0
DEFAULT_T_BAD = 25.0

# Floor on mad so a degenerate (all-identical) residual distribution cannot
# collapse t_ok and t_bad onto the median and reject everything.
_MAD_FLOOR = 1e-3


def auto_threshold(
    d: np.ndarray,
    lik_ref: np.ndarray,
    lik_tgt: np.ndarray,
    high_conf: float = 0.9,
    high_conf_ref: "float | None" = None,
    high_conf_tgt: "float | None" = None,
    k1: float = 3.0,
    k2: float = 8.0,
    min_n: int = 200,
    pooled: "dict | None" = None,
) -> dict:
    """Estimate (t_ok, t_bad) for one bodypart from high-confidence agreement.

    Frames where BOTH views exceed their respective confidence bars are presumed
    correct correspondences, so their residual spread measures this session's real
    geometric noise for this bodypart. Per-side thresholds can override the shared
    `high_conf` value to calibrate each camera independently.
    """
    d = np.asarray(d, dtype=float)
    # Each camera clears its OWN bar. high_conf remains the shared default so
    # existing single-value callers behave identically.
    hr = high_conf if high_conf_ref is None else high_conf_ref
    ht = high_conf if high_conf_tgt is None else high_conf_tgt
    hi = (
        np.isfinite(d)
        & (np.asarray(lik_ref, dtype=float) > hr)
        & (np.asarray(lik_tgt, dtype=float) > ht)
    )
    n = int(hi.sum())

    if n >= min_n:
        sample = d[hi]
        med = float(np.median(sample))
        mad = float(1.4826 * np.median(np.abs(sample - med)))
        source = "self"
    elif pooled is not None:
        med, mad, source = float(pooled["med"]), float(pooled["mad"]), "pooled"
    else:
        return {
            "med": float("nan"), "mad": float("nan"),
            "t_ok": DEFAULT_T_OK, "t_bad": DEFAULT_T_BAD,
            "n_highconf": n, "threshold_source": "default",
        }

    mad = max(mad, _MAD_FLOOR)
    return {
        "med": med, "mad": mad,
        "t_ok": med + k1 * mad, "t_bad": med + k2 * mad,
        "n_highconf": n, "threshold_source": source,
    }


def classify(
    d: np.ndarray,
    lik_ref: np.ndarray,
    lik_tgt: np.ndarray,
    t_ok: float,
    t_bad: float,
    gate_ref: float = 0.6,
    low_tgt: float = 0.6,
) -> np.ndarray:
    """Assign a verdict code per frame for one bodypart in the TARGET view.

    REJECT is applied last so it outranks every other outcome unconditionally.
    RESCUE here means "rescue candidate"; the 3D gate confirms or demotes it
    in apply_gate().
    """
    d = np.asarray(d, dtype=float)
    lr = np.asarray(lik_ref, dtype=float)
    lt = np.asarray(lik_tgt, dtype=float)

    codes = np.full(d.shape, AMBIGUOUS, dtype=np.uint8)
    judged = np.isfinite(d) & (lr > gate_ref)
    codes[~judged] = UNJUDGED

    near = judged & (d <= t_ok)
    codes[near & (lt < low_tgt)] = RESCUE
    codes[near & (lt >= low_tgt)] = CONFIRM
    codes[judged & (d > t_bad)] = REJECT
    return codes


def plausibility_gate(
    pts3d: np.ndarray,
    codes: np.ndarray,
    max_gap: int = 10,
    expand: float = 0.2,
    speed_pct: float = 99.0,
    min_confirm: int = 20,
) -> np.ndarray:
    """Test rescue candidates for 3D plausibility.

    An epipolar line is a one-degree-of-freedom constraint, so a point can lie
    exactly on the correct line at a badly wrong depth. Two tests close that
    gap, both calibrated from this bodypart's own CONFIRM population:

    * working volume — the 1st-99th percentile box per axis, expanded by
      `expand`;
    * jump limit — distance from the most recent CONFIRM frame within `max_gap`
      must not exceed the 99th-percentile observed 3D speed times the gap.

    Returns a boolean array, True where a candidate passes. Entries that are not
    rescue candidates are True and meaningless. With fewer than `min_confirm`
    usable CONFIRM points there is nothing to calibrate against, so everything
    passes and the epipolar distance stands alone.
    """
    pts3d = np.asarray(pts3d, dtype=float)
    codes = np.asarray(codes)
    n = len(codes)
    out = np.ones(n, dtype=bool)

    finite = np.isfinite(pts3d).all(axis=1)
    conf = (codes == CONFIRM) & finite
    cand = (codes == RESCUE) & finite
    if not cand.any():
        return out
    out[(codes == RESCUE) & ~finite] = False
    if int(conf.sum()) < min_confirm:
        return out

    ref_pts = pts3d[conf]
    lo = np.percentile(ref_pts, 1.0, axis=0)
    hi = np.percentile(ref_pts, 99.0, axis=0)
    pad = (hi - lo) * expand
    lo, hi = lo - pad, hi + pad

    idx = np.flatnonzero(cand)
    inside = ((pts3d[idx] >= lo) & (pts3d[idx] <= hi)).all(axis=1)
    out[idx[~inside]] = False

    # v99 from frame-to-frame speed between consecutive CONFIRM frames.
    cframes = np.flatnonzero(conf)
    gaps = np.diff(cframes)
    step = np.linalg.norm(np.diff(ref_pts, axis=0), axis=1)
    usable = gaps > 0
    if not usable.any():
        return out
    v99 = float(np.percentile(step[usable] / gaps[usable], speed_pct))

    # Most recent CONFIRM at or before each candidate frame.
    prev_pos = np.searchsorted(cframes, idx, side="left") - 1
    for k, cand_frame in enumerate(idx):
        if not out[cand_frame]:
            continue
        p = prev_pos[k]
        if p < 0:
            continue
        gap = int(cand_frame - cframes[p])
        if gap <= 0 or gap > max_gap:
            continue                       # no recent anchor: volume test only
        limit = v99 * gap
        moved = float(np.linalg.norm(pts3d[cand_frame] - ref_pts[p]))
        if moved > limit:
            out[cand_frame] = False
    return out


def apply_gate(codes: np.ndarray, gate_pass: np.ndarray) -> np.ndarray:
    """Demote rescue candidates that failed the 3D gate."""
    out = np.asarray(codes).copy()
    out[(out == RESCUE) & ~np.asarray(gate_pass, dtype=bool)] = RESCUE_REJECTED
    return out


def apply_verdicts(
    xy: np.ndarray,
    lik: np.ndarray,
    codes: np.ndarray,
    rescue_floor: float = 0.9,
) -> "tuple[np.ndarray, np.ndarray]":
    """Produce corrected (xy, likelihood) for one bodypart. Inputs unchanged.

    REJECT clears the coordinates and zeroes the likelihood so every downstream
    filter drops the point. RESCUE keeps the coordinates and lifts the
    likelihood to the floor so a likelihood filter stops discarding it. Every
    other verdict is a pass-through.
    """
    xy_out = np.asarray(xy, dtype=float).copy()
    lik_out = np.asarray(lik, dtype=float).copy()
    codes = np.asarray(codes)

    rej = codes == REJECT
    xy_out[rej] = np.nan
    lik_out[rej] = 0.0

    res = codes == RESCUE
    lik_out[res] = np.maximum(lik_out[res], rescue_floor)
    return xy_out, lik_out

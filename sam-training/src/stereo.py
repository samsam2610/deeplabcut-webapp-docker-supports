"""Anipose stereo calibration: epipolar lines and triangulation.

The pedestal is bolted down, so an armed pellet triangulates to the SAME 3D
point every trial — measured over 138 tags: sd (0.29, 0.22, 0.31), max deviation
from the median 1.03. That makes 3D position the strongest pellet test available,
far stronger than appearance in either view alone.

Calibration lives in `labeled-data/<session>/calibration.toml` (16 of them in
DREADD-Ali, ~0.10 px reprojection error). Format is anipose's: per camera a 3x3
`matrix`, a 5-vector `distortions`, a Rodrigues `rotation` and a `translation`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


def _load_toml(path):
    try:
        import tomllib
    except ImportError:                      # py<3.11
        import tomli as tomllib
    with open(path, "rb") as fh:
        return tomllib.load(fh)


@dataclass
class Camera:
    K: np.ndarray
    dist: np.ndarray
    R: np.ndarray
    t: np.ndarray

    @property
    def P(self) -> np.ndarray:
        return self.K @ np.hstack([self.R, self.t])


@dataclass
class Calibration:
    cam0: Camera
    cam1: Camera
    source: str = ""

    def triangulate(self, p0, p1) -> np.ndarray:
        """(N,2) points in each view -> (N,3) world points.

        Undistorts first: the lenses carry a large radial term (k1 ≈ -0.47), so
        skipping it biases the result by more than the signal we are gating on.
        """
        import cv2
        a = np.asarray(p0, dtype=float).reshape(-1, 1, 2)
        b = np.asarray(p1, dtype=float).reshape(-1, 1, 2)
        ua = cv2.undistortPoints(a, self.cam0.K, self.cam0.dist, P=self.cam0.K)
        ub = cv2.undistortPoints(b, self.cam1.K, self.cam1.dist, P=self.cam1.K)
        X = cv2.triangulatePoints(self.cam0.P, self.cam1.P,
                                  ua.reshape(-1, 2).T, ub.reshape(-1, 2).T)
        return (X[:3] / X[3]).T

    def epiline_in_cam1(self, p0) -> np.ndarray:
        """Epipolar line(s) in cam1 for point(s) in cam0, as (a, b, c) with
        a*x + b*y + c = 0. Lets a candidate be checked against its partner view
        without needing a match there first."""
        import cv2
        F = fundamental(self)
        a = np.asarray(p0, dtype=float).reshape(-1, 1, 2)
        ua = cv2.undistortPoints(a, self.cam0.K, self.cam0.dist, P=self.cam0.K)
        return cv2.computeCorrespondEpilines(ua.reshape(-1, 1, 2), 1, F).reshape(-1, 3)


def fundamental(cal: Calibration) -> np.ndarray:
    """F from the two projection matrices, via the relative pose."""
    R = cal.cam1.R @ cal.cam0.R.T
    t = cal.cam1.t - R @ cal.cam0.t
    tx = np.array([[0, -t[2, 0], t[1, 0]],
                   [t[2, 0], 0, -t[0, 0]],
                   [-t[1, 0], t[0, 0], 0]], dtype=float)
    E = tx @ R
    return np.linalg.inv(cal.cam1.K).T @ E @ np.linalg.inv(cal.cam0.K)


def load(path) -> Calibration:
    import cv2
    d = _load_toml(path)
    if "cam_0" not in d or "cam_1" not in d:
        raise ValueError(f"{path}: expected cam_0 and cam_1 sections")

    def cam(section):
        R, _ = cv2.Rodrigues(np.asarray(section["rotation"], dtype=float))
        return Camera(K=np.asarray(section["matrix"], dtype=float),
                      dist=np.asarray(section["distortions"], dtype=float),
                      R=R,
                      t=np.asarray(section["translation"], dtype=float).reshape(3, 1))

    return Calibration(cam0=cam(d["cam_0"]), cam1=cam(d["cam_1"]), source=str(path))


def _session_key(name: str):
    """(animal, YYYYMMDD) from a labeled-data dir or a video stem."""
    import re
    m = re.match(r"^(.+?)_(?:cam\d+_)?(\d{8})", name)
    return (m.group(1), m.group(2)) if m else (None, None)


def find_for_video(project_path, video) -> Path | None:
    """The calibration nearest to THIS recording.

    Same session if it has one; else the same animal on the nearest date; else
    the nearest date from any animal.

    This used to be "the last path alphabetically", under a docstring claiming
    "the most recent". For banh-mi-1 Jul 7 that picked khoai-lang-2's May 12
    calibration — a different animal, two months earlier. Measured on banh-mi-1
    Jul 2's own labelled frames, the same verified-correct paw pairs score
    p50 0.78 px under that session's own calibration and p50 27.8 px under
    khoai-lang's. Every 3D gate in the pipeline was paying that.
    """
    root = Path(project_path) / "labeled-data"
    found = sorted(root.glob("*/calibration.toml"))
    if not found:
        return None
    animal, date = _session_key(Path(video).stem if video else "")
    if animal is None:
        return found[-1]

    def rank(path):
        a, d = _session_key(path.parent.name)
        if a is None or d is None:
            return (2, 10 ** 9, path.parent.name)
        gap = abs(int(d) - int(date))
        # same animal first, then nearest in time: the rig is one rig, but a
        # nudged camera between animals is exactly what a stale calibration
        # cannot see.
        return (0 if a == animal else 1, gap, path.parent.name)

    return min(found, key=rank)


def find_for_project(project_path) -> Path | None:
    """Any calibration in the project. Prefer `find_for_video` — a calibration
    from the wrong session is the single largest error in the 3D gates."""
    root = Path(project_path) / "labeled-data"
    found = sorted(root.glob("*/calibration.toml"))
    return found[-1] if found else None


def project(cam, points) -> np.ndarray:
    """(N,3) world points -> (N,2) pixels in this camera, distortion included.

    The inverse of what ``triangulate`` undoes, so a point pushed through
    ``project`` then ``epipolar_residual`` comes back at ~0. Without that
    round-trip the residual has nothing to be checked against.
    """
    import cv2
    X = np.asarray(points, dtype=float).reshape(-1, 3)
    rvec, _ = cv2.Rodrigues(cam.R)
    out, _ = cv2.projectPoints(X, rvec, cam.t, cam.K, cam.dist)
    return out.reshape(-1, 2)


def epipolar_residual(cal: "Calibration", p0, p1) -> np.ndarray:
    """Perpendicular distance, in px, from each cam1 point to the epipolar line
    of its cam0 partner.

    Both points are undistorted first — ``epiline_in_cam1`` undistorts cam0's,
    so leaving cam1's distorted would compare two different coordinate frames.

    PERPENDICULAR is the point: displacement ALONG the line is depth, which is
    exactly what triangulation is for and must not be penalised. Only the
    off-line component says "these two views are not looking at the same thing".
    """
    import cv2
    lines = cal.epiline_in_cam1(p0)
    b = np.asarray(p1, dtype=float).reshape(-1, 1, 2)
    ub = cv2.undistortPoints(b, cal.cam1.K, cal.cam1.dist, P=cal.cam1.K).reshape(-1, 2)
    num = np.abs(lines[:, 0] * ub[:, 0] + lines[:, 1] * ub[:, 1] + lines[:, 2])
    return num / np.sqrt(lines[:, 0] ** 2 + lines[:, 1] ** 2)


def distance_to(points, reference) -> np.ndarray:
    p = np.asarray(points, dtype=float).reshape(-1, 3)
    r = np.asarray(reference, dtype=float).reshape(1, 3)
    return np.linalg.norm(p - r, axis=1)

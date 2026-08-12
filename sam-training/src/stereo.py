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


def find_for_project(project_path) -> Path | None:
    """Any calibration in the project's labeled-data.

    They are per session, but the rig is one rig: the point of gating on 3D is
    that the pedestal does not move, so the most recent calibration is a fine
    default and the caller may override.
    """
    root = Path(project_path) / "labeled-data"
    found = sorted(root.glob("*/calibration.toml"))
    return found[-1] if found else None


def distance_to(points, reference) -> np.ndarray:
    p = np.asarray(points, dtype=float).reshape(-1, 3)
    r = np.asarray(reference, dtype=float).reshape(1, 3)
    return np.linalg.norm(p - r, axis=1)

"""Two-camera pellet sweep with a 3D gate.

Replaces the single-camera NCC sweep, which decided "pellet present" from the
best correlation anywhere in one band and could be fooled by a white paw
(measured: NCC 0.87 on a frame with no pellet).

A frame is armed only if all three hold:

  1. cam0 matches the pooled pellet template above threshold
  2. cam1 does too — the cameras are hardware-synced, so a paw faking the
     pellet in one view will not coincide in the other
  3. the two match positions triangulate to within ``max_3d_dist`` of the
     project's reference pellet point

(3) is what actually earns its place. On the frame that exposed the original
bug, BOTH cameras scored above threshold (0.79 and 0.74) and only the 3D
distance rejected it, at 3.85 against a measured max of 1.03 for real pellets.

Cost is two decodes per sampled frame rather than one; at stride 5 that is
~7 minutes for a 252k-frame pair on CPU.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from . import config, ncc, pellet_model as pm


@dataclass
class PairSweep:
    frames: np.ndarray              # 0-based indices actually scored
    score0: np.ndarray
    score1: np.ndarray
    dist3d: np.ndarray              # NaN where the cameras disagreed
    present: np.ndarray             # bool, the armed decision
    n_frames: int

    def __len__(self) -> int:
        return len(self.frames)


def decide(score0, score1, dist, threshold: float, max_dist: float) -> np.ndarray:
    """Vectorised form of the three-way test, kept separate so it is testable
    without touching video."""
    s0 = np.asarray(score0, dtype=float)
    s1 = np.asarray(score1, dtype=float)
    d = np.asarray(dist, dtype=float)
    agree = (s0 >= threshold) & (s1 >= threshold)
    near = np.isfinite(d) & (d <= max_dist)
    return agree & near


def sweep_pair(video0, video1, model: pm.PelletModel, calibration,
               stride: int = config.SWEEP_STRIDE, progress=None) -> PairSweep:
    """Score both cameras in lock-step.

    The two files are opened together and advanced in the same loop rather than
    swept separately: the cameras are frame-synced, so reading them apart would
    mean holding one whole trace in memory to pair up afterwards, and would risk
    silently mismatching indices if the two files differ in length.
    """
    cam0 = model.cameras.get("cam0")
    cam1 = model.cameras.get("cam1")
    if cam0 is None or cam1 is None:
        raise ValueError("model needs both cam0 and cam1")

    cap0 = cv2.VideoCapture(str(video0))
    cap1 = cv2.VideoCapture(str(video1))
    if not cap0.isOpened() or not cap1.isOpened():
        cap0.release(); cap1.release()
        raise OSError(f"cannot open pair: {video0} / {video1}")
    try:
        n0 = int(cap0.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        n1 = int(cap1.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        # Sweep only the overlap: a sibling a few frames shorter must not make
        # the tail of the longer video look like a camera disagreement.
        last = min(n0, n1) - 1
        frames, s0s, s1s, p0s, p1s = [], [], [], [], []
        idx = 0
        while idx <= last:
            if idx % stride:
                if not (cap0.grab() and cap1.grab()):
                    break
                idx += 1
                continue
            ok0, f0 = cap0.read()
            ok1, f1 = cap1.read()
            if not (ok0 and ok1):
                break
            a, pa = pm.match(ncc.to_gray(f0), cam0)
            b, pb = pm.match(ncc.to_gray(f1), cam1)
            frames.append(idx); s0s.append(a); s1s.append(b)
            p0s.append(pa); p1s.append(pb)
            if progress is not None and len(frames) % 2000 == 0:
                progress(idx, last)
            idx += 1
    finally:
        cap0.release(); cap1.release()

    frames = np.asarray(frames, dtype=np.int64)
    s0 = np.asarray(s0s, dtype=np.float32)
    s1 = np.asarray(s1s, dtype=np.float32)
    dist = np.full(len(frames), np.nan, dtype=np.float32)

    # Triangulate only where both cameras cleared the bar: the rest cannot be
    # armed regardless, and triangulating a paw is wasted work.
    if len(frames) and calibration is not None and model.ref_3d is not None:
        cand = np.flatnonzero((s0 >= model.threshold) & (s1 >= model.threshold))
        if len(cand):
            X = calibration.triangulate([p0s[i] for i in cand],
                                        [p1s[i] for i in cand])
            ref = np.asarray(model.ref_3d, dtype=float).reshape(1, 3)
            dist[cand] = np.linalg.norm(X - ref, axis=1).astype(np.float32)

    present = decide(s0, s1, dist, model.threshold, model.max_3d_dist)
    return PairSweep(frames=frames, score0=s0, score1=s1, dist3d=dist,
                     present=present, n_frames=min(n0, n1))

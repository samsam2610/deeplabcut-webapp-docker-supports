"""Normalised cross-correlation against the pellet-on-pedestal template.

Why NCC and not a brightness threshold: the white reload vane sweeps across the
frame between trials and swings the frame mean from ~40 to ~142. Every
absolute-intensity test tried against that failed. ``TM_CCOEFF_NORMED`` is
invariant to it.

This module deliberately knows nothing about trials or notes — it turns a video
into a score per sampled frame, and ``intervals.py`` turns that into structure.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import config


def crop(gray, box):
    y0, y1, x0, x1 = box
    return gray[y0:y1, x0:x1]


def match(gray, template, box) -> tuple[float, tuple[int, int]]:
    """Best NCC score for ``template`` inside ``box``, and where it landed.

    The returned position is in FULL-FRAME coordinates (the box offset is added
    back), so callers never have to remember whether a coordinate is relative.
    """
    region = crop(gray, box)
    if region.size == 0 or template.size == 0:
        return -1.0, (0, 0)
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return -1.0, (0, 0)
    result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, best, _, loc = cv2.minMaxLoc(result)
    y0, _, x0, _ = box
    return float(best), (int(loc[0]) + x0, int(loc[1]) + y0)


def to_gray(frame):
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


@dataclass
class Sweep:
    """Result of a strided pass over a video."""
    frames: np.ndarray              # 0-based frame indices actually scored
    scores: np.ndarray              # NCC at each
    n_frames: int                   # total frames the video reports

    def __len__(self) -> int:
        return len(self.frames)


def sweep_video(video_path, template, box=None, stride: int = config.SWEEP_STRIDE,
                start: int = 0, end: int | None = None,
                progress=None) -> Sweep:
    """Score every ``stride``-th frame of the video against ``template``.

    Reads sequentially and uses ``grab()`` to skip — decoding only the frames
    actually scored is what makes this ~5x faster than a dense pass rather than
    just 5x fewer matchTemplate calls.
    """
    box = box or config.PELLET_SEARCH_BOX
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise OSError(f"cannot open video: {video_path}")
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        last = total - 1 if end is None else min(end, total - 1)
        if start:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        frames: list[int] = []
        scores: list[float] = []
        idx = start
        while idx <= last:
            if (idx - start) % stride:
                if not cap.grab():
                    break
                idx += 1
                continue
            ok, frame = cap.read()
            if not ok:
                break
            score, _ = match(to_gray(frame), template, box)
            frames.append(idx)
            scores.append(score)
            if progress is not None and len(frames) % 2000 == 0:
                progress(idx, last)
            idx += 1
        return Sweep(np.asarray(frames, dtype=np.int64),
                     np.asarray(scores, dtype=np.float32), total)
    finally:
        cap.release()


def read_frames(video_path, indices) -> dict[int, np.ndarray]:
    """Grab specific 0-based frames. Seeking costs ~34ms, so this is for tens of
    frames (calibration, visualisation), not for sweeps."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise OSError(f"cannot open video: {video_path}")
    out: dict[int, np.ndarray] = {}
    try:
        for i in sorted(set(int(i) for i in indices)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, frame = cap.read()
            if ok:
                out[i] = frame
    finally:
        cap.release()
    return out


def extract_template(frame, box=None) -> np.ndarray:
    """Cut the pellet template out of a frame known to show the armed pedestal."""
    return crop(to_gray(frame), box or config.PELLET_TEMPLATE_BOX).copy()

"""Stage 0 — per-session rig calibration.

The camera has not moved across animals or months, so the defaults in
``config`` would usually work. We re-derive the PELLET TEMPLATE anyway: if the
pedestal shifts even slightly, every downstream window silently degrades rather
than failing loudly, and that is the worst kind of bug to inherit.

**The aperture box is NOT located — it is the config default, passed through.**
Nothing needs it yet: stage 1 uses only the pellet. Stage 2 will gate on the paw
clearing the aperture, and at that point this has to become a real measurement,
because a wrong aperture box would silently mis-time every crossing. Tracked as
a gap rather than papered over.

Calibration stores *where* the template came from, not the pixels. Re-extracting
from the video keeps the JSON small and human-readable, and means a stale
calibration can always be traced back to the frame it was built from.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from . import config, ncc


@dataclass
class RigCalibration:
    video: str
    template_frame: int             # 0-based frame the template was cut from
    template_box: tuple[int, int, int, int]
    search_box: tuple[int, int, int, int]
    aperture_box: tuple[int, int, int, int]
    score: float                    # self-match NCC on an independent frame
    n_sampled: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "RigCalibration":
        d = json.loads(text)
        for k in ("template_box", "search_box", "aperture_box"):
            d[k] = tuple(d[k])
        return cls(**d)


def _spread(n_frames: int, n: int) -> list[int]:
    """Frame indices spread across the video, avoiding the very ends."""
    if n_frames <= 0:
        return []
    lo, hi = int(n_frames * 0.05), int(n_frames * 0.95)
    if hi <= lo:
        lo, hi = 0, max(0, n_frames - 1)
    return [int(round(x)) for x in np.linspace(lo, hi, num=min(n, hi - lo + 1))]


def calibrate(video_path, n_sample: int = 40,
              template_box=None, search_box=None,
              aperture_box=None) -> RigCalibration:
    """Find a frame showing the armed pedestal and cut the template from it.

    Samples frames across the video, scores each against the *default* template
    geometry, and keeps the best. The pellet is present for roughly 60% of a
    session, so a few dozen samples reliably contain several armed frames.

    The reported score is measured on a DIFFERENT frame than the template came
    from — a template always matches itself at 1.0, which would tell us nothing.
    """
    template_box = tuple(template_box or config.PELLET_TEMPLATE_BOX)
    search_box = tuple(search_box or config.PELLET_SEARCH_BOX)
    aperture_box = tuple(aperture_box or config.APERTURE_BOX)

    import cv2
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise OSError(f"cannot open video: {video_path}")
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()

    indices = _spread(n_frames, n_sample)
    frames = ncc.read_frames(video_path, indices)
    if not frames:
        raise OSError(f"no readable frames in {video_path}")

    # Rank candidates by how bright and structured the template region is: an
    # armed pedestal has a white blob on black, which has far more contrast
    # than a bare post or a vane-flooded frame.
    ranked = sorted(
        frames.items(),
        key=lambda kv: float(ncc.crop(ncc.to_gray(kv[1]), template_box).std()),
        reverse=True,
    )
    best_idx, best_frame = ranked[0]
    template = ncc.extract_template(best_frame, template_box)

    # Score it against every other sampled frame; the armed ones should score
    # high. Use the 75th percentile so a majority of empty frames cannot drag
    # the number down, and a single fluke cannot inflate it.
    others = [ncc.match(ncc.to_gray(f), template, search_box)[0]
              for i, f in frames.items() if i != best_idx]
    score = float(np.percentile(others, 75)) if others else 0.0

    return RigCalibration(
        video=str(video_path), template_frame=int(best_idx),
        template_box=template_box, search_box=search_box,
        aperture_box=aperture_box, score=score, n_sampled=len(frames),
    )


def load_template(calib: RigCalibration) -> np.ndarray:
    """Re-cut the template from the frame the calibration names."""
    frames = ncc.read_frames(calib.video, [calib.template_frame])
    if calib.template_frame not in frames:
        raise OSError(f"frame {calib.template_frame} unreadable in {calib.video}")
    return ncc.extract_template(frames[calib.template_frame], calib.template_box)


def cache_path(project_path) -> Path:
    return Path(project_path) / config.CALIBRATION_FILENAME


def save(project_path, key: str, calib: RigCalibration) -> None:
    """Persist one session's calibration into the project-level cache."""
    path = cache_path(project_path)
    store = {}
    if path.is_file():
        try:
            store = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            store = {}
    store[key] = json.loads(calib.to_json())
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(store, indent=2))
    tmp.replace(path)               # atomic: never leave a half-written cache


def load(project_path, key: str) -> RigCalibration | None:
    path = cache_path(project_path)
    if not path.is_file():
        return None
    try:
        store = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    entry = store.get(key)
    return RigCalibration.from_json(json.dumps(entry)) if entry else None

"""Stage 0 — validate the canonical pellet template against this session.

The rig is fixed: the camera has not moved across animals or two months of
sessions. So stage 0 is a VALIDATION step, not a derivation step. That is a
correction of an earlier design, and it was forced by evidence.

Deriving a template per session was tried twice and failed twice, differently:

    highest patch contrast     banh-mi-1 Jul 4  separation +0.12 (lost 42% of
                               that session's onsets — every score sat on the
                               threshold)
    widest score spread        banh-mi-1 Jul 2  separation -0.01 (selected the
                               white reload vane, whose in/out cycle is the
                               strongest bimodal signal in the box and has
                               nothing to do with the pellet)
    both combined              khoai-lang May 6 separation -0.10

Each heuristic broke a different session. Meanwhile ONE template, cut from
banh-mi-1 Jul 2 frame 49296, separates pellet-present from pellet-absent by
+0.34 to +0.56 on all ten sessions. Committed as ``assets/pellet_template.png``.

Per-session search survives only as a fallback for when the canonical genuinely
stops matching — i.e. someone moved the camera — and it says so loudly rather
than silently degrading.

**The aperture box is NOT located** — it is the config default, passed through.
Nothing needs it yet; stage 2 will gate on the paw clearing the aperture, and at
that point this has to become a real measurement. Tracked as a gap.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from . import config, ncc

CANONICAL_TEMPLATE = Path(__file__).resolve().parent / "assets" / "pellet_template.png"

# Below this spread between the high and low modes of the score distribution,
# presence and absence are not cleanly distinguishable and stage 1 must not be
# trusted. The canonical scores 0.34+ on every known session; a session landing
# under this has changed in a way that needs a human to look.
MIN_SPREAD = 0.25


@dataclass
class RigCalibration:
    video: str
    source: str                     # "canonical" | "session"
    template_frame: int             # -1 for the canonical
    template_box: tuple[int, int, int, int]
    search_box: tuple[int, int, int, int]
    aperture_box: tuple[int, int, int, int]
    score: float                    # p85 - p15 of the probe score distribution
    n_sampled: int

    @property
    def trustworthy(self) -> bool:
        return self.score >= MIN_SPREAD

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


def canonical_template() -> np.ndarray:
    import cv2
    img = cv2.imread(str(CANONICAL_TEMPLATE), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise OSError(f"canonical template missing: {CANONICAL_TEMPLATE}")
    return img


def _quality(template, grays, search_box) -> float:
    """How well this template splits the probe frames into present/absent.

    The probe set is a spread of the whole session, so it naturally contains
    both — no labels needed. A template that matches everything, or nothing,
    scores near zero.
    """
    probe = [ncc.match(g, template, search_box)[0] for g in grays]
    if not probe:
        return 0.0
    return float(np.percentile(probe, 85) - np.percentile(probe, 15))


def calibrate(video_path, n_sample: int = 32,
              template_box=None, search_box=None,
              aperture_box=None) -> RigCalibration:
    """Validate the canonical template here; fall back to a session search."""
    template_box = tuple(template_box or config.PELLET_TEMPLATE_BOX)
    search_box = tuple(search_box or config.PELLET_SEARCH_BOX)
    aperture_box = tuple(aperture_box or config.APERTURE_BOX)

    import cv2
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise OSError(f"cannot open video: {video_path}")
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()

    frames = ncc.read_frames(video_path, _spread(n_frames, n_sample))
    if not frames:
        raise OSError(f"no readable frames in {video_path}")
    grays = [ncc.to_gray(f) for f in frames.values()]

    score = _quality(canonical_template(), grays, search_box)
    if score >= MIN_SPREAD:
        return RigCalibration(
            video=str(video_path), source="canonical", template_frame=-1,
            template_box=template_box, search_box=search_box,
            aperture_box=aperture_box, score=score, n_sampled=len(frames))

    # The canonical stopped matching — most likely the camera moved. Search this
    # session, but keep whichever is better and let the caller see the number.
    best_idx, best_score = -1, score
    for idx, img in ((i, ncc.to_gray(f)) for i, f in frames.items()):
        cand = ncc.crop(img, template_box)
        if cand.size == 0:
            continue
        q = _quality(cand, [g for g in grays if g is not img], search_box)
        if q > best_score:
            best_idx, best_score = idx, q

    return RigCalibration(
        video=str(video_path),
        source="canonical" if best_idx < 0 else "session",
        template_frame=int(best_idx), template_box=template_box,
        search_box=search_box, aperture_box=aperture_box,
        score=best_score, n_sampled=len(frames))


def load_template(calib: RigCalibration) -> np.ndarray:
    if calib.source == "canonical" or calib.template_frame < 0:
        return canonical_template()
    frames = ncc.read_frames(calib.video, [calib.template_frame])
    if calib.template_frame not in frames:
        raise OSError(f"frame {calib.template_frame} unreadable in {calib.video}")
    return ncc.extract_template(frames[calib.template_frame], calib.template_box)


def cache_path(project_path) -> Path:
    return Path(project_path) / config.CALIBRATION_FILENAME


def save(project_path, key: str, calib: RigCalibration) -> None:
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
    if not entry:
        return None
    try:
        return RigCalibration.from_json(json.dumps(entry))
    except (TypeError, KeyError, ValueError):
        # An entry written by an older schema is a MISS, not a crash. This file
        # outlives the code that wrote it: the schema already changed once, when
        # calibration became validate-not-derive, and a stale entry must simply
        # re-derive rather than take the panel down.
        return None

"""Stage 0 + 1 for one video: cached pair sweep -> armed mask -> trial windows.

The single path from a sweep to the windows the panel shows. Three endpoints
need it — the debug panel, `/windows`, and `/onset-csv` — and each used to carry
its own copy; the last divergence had one of them forget the cache signature, so
"Build onset CSV" reported "not swept yet" for a video that had just been swept.

The detector is the two-camera one: both cameras must match the pooled pellet
template, and the two match positions must triangulate near the project's
reference pellet point. The single-camera sweep it replaces decided presence
from the best correlation anywhere in one band, which a white paw on the
pedestal satisfies — measured 0.85 on a frame with no pellet at all.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import (config, judging, ncc, notes, onset_csv, pellet_model as pm,
               sweep_cache)


@dataclass
class Stage1:
    frames: np.ndarray
    score: np.ndarray               # min(cam0, cam1) — see `windows_for`
    score0: np.ndarray
    score1: np.ndarray
    dist3d: np.ndarray
    armed: list
    windows: list
    judge: judging.Judge
    n_frames: int


def model_for(project_path, video):
    """The project model with THIS video's placed box centres applied.

    The sidecar is the source of truth for the box, and the sweep gate refuses
    to run without one — so the sweep must look where that box is, not at the
    project default.
    """
    model = pm.load(project_path)
    if model is None:
        return None
    return pm.with_centres(model, pm.centres_from_marks(onset_csv.read_marks(video)))


def reference_from_points(points, minimum: int = 5):
    """Median of triangulated pellet detections, or None if too few.

    Median, not mean: a paw or the reload vane occasionally triangulates
    somewhere absurd, and one such point would drag the origin with it.

    None means "not enough evidence, use the click" — an imperfect origin beats
    one derived from two frames that happened to match.
    """
    pts = [p for p in (points or []) if p is not None]
    if len(pts) < int(minimum):
        return None
    a = np.asarray(pts, dtype=float).reshape(-1, 3)
    return tuple(float(v) for v in np.median(a, axis=0))


def detect_reference(video, sibling, model, calibration, samples: int = 80,
                     thr0: float = 0.75, thr1: float = 0.72):
    """Locate the pellet in 3D by matching, before the sweep needs a reference.

    The click aims the search box; it is not accurate enough to BE the origin a
    2.0 gate measures from. On eggtart-2 Jul 10 the click sat 2.83 away from
    where the pellet actually triangulates, so 0 % of confident detections fell
    inside the gate — 151 trials produced one window. Measured from the
    detections instead: 95 % inside, median 0.52.

    ~80 frames, two decodes each: about fifteen seconds against a sweep of six
    minutes.
    """
    import cv2
    cam0, cam1 = model.cameras.get("cam0"), model.cameras.get("cam1")
    if cam0 is None or cam1 is None or calibration is None:
        return None
    c0, c1 = cv2.VideoCapture(str(video)), cv2.VideoCapture(str(sibling))
    try:
        total = min(int(c0.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
                    int(c1.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
        if total <= 0:
            return None
        found = []
        for i in range(int(samples)):
            at = int(total * (i + 0.5) / samples)
            pair = []
            for cap, cam in ((c0, cam0), (c1, cam1)):
                cap.set(cv2.CAP_PROP_POS_FRAMES, at)
                ok, img = cap.read()
                if not ok:
                    break
                pair.append(pm.match(ncc.to_gray(img), cam))
            if len(pair) < 2:
                continue
            (s0, p0), (s1, p1) = pair
            if s0 >= thr0 and s1 >= thr1:
                found.append(calibration.triangulate([p0], [p1])[0])
    finally:
        c0.release(); c1.release()
    return reference_from_points(found)


def with_reference(model, calibration, marks, detected=None):
    """A copy of ``model`` whose ``ref_3d`` is THIS pair's placed pellet.

    A 3D coordinate only means something in the frame of the calibration that
    produced it. ref_3d was a project-level constant, so moving banh-mi-1 Jul 7
    onto its own calibration pushed the triangulated pellet from 0.48 to 29.30
    away from it — every pellet would have failed a 2.0 gate.

    The human already places the box on the stationary pellet in both cameras.
    Triangulating that with this video's own calibration puts the reference in
    the right frame by construction, and it cannot go stale.
    """
    from dataclasses import replace
    if model is None or calibration is None:
        return model
    if detected is not None:
        # The detector's own answer, which is better than the click by
        # construction: it is where the template actually matched.
        return replace(model, ref_3d=[float(v) for v in detected])
    centres = pm.centres_from_marks(marks)
    p0, p1 = centres.get("cam0"), centres.get("cam1")
    if p0 is None or p1 is None:
        # Sweeping is gated on a placed box, so this is belt and braces — but
        # inventing a reference from nothing is worse than keeping the old one.
        return model
    X = calibration.triangulate([p0], [p1])[0]
    return replace(model, ref_3d=[float(X[0]), float(X[1]), float(X[2])])


def pair_sweep(project_path, video, stride: int = config.SWEEP_STRIDE,
               root=None):
    """The cached two-camera sweep, or None when the pair has not been swept."""
    model = pm.load(project_path)
    return sweep_cache.load_pair(video, model, onset_csv.read_marks(video),
                                 stride=stride, root=root)


def windows_for(project_path, video, stride: int = config.SWEEP_STRIDE,
                root=None) -> Stage1 | None:
    """None means "not swept yet" — distinct from a sweep that armed nothing.

    The panel offers a sweep for the first and reports zero trials for the
    second; collapsing them would hide a detector that is rejecting everything.
    """
    cached = pair_sweep(project_path, video, stride, root)
    if cached is None:
        return None
    frames, s0, s1, dist, n_frames = cached
    # THE conversion. The sweep counts video frames from 0; the companion CSV,
    # the tags, the onset sidecar and motion3d all count from 1. Converting once
    # here means build_windows compares armed intervals against outcome markers
    # in the SAME base — it did not, so every armed interval sat a frame adrift
    # of the trial it belonged to — and everything downstream of this line is a
    # companion-CSV frame_number. Only the cv2 seek converts back.
    frames = np.asarray(frames) + 1
    judge = judging.load(project_path)
    armed = judging.armed_pair(frames, s0, s1, dist, judge)
    trials = notes.pair_trials(notes.read_notes(video))
    return Stage1(
        frames=frames,
        # The weaker camera is what has to clear the threshold, so it is what
        # the trace should show. Plotting cam0 alone would draw a confident
        # line across frames cam1 rejected.
        score=np.minimum(s0, s1),
        score0=s0, score1=s1, dist3d=dist,
        armed=armed,
        windows=judging.build(trials, armed, judge),
        judge=judge,
        n_frames=n_frames,
    )

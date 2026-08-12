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

from . import (config, judging, notes, onset_csv, pellet_model as pm,
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

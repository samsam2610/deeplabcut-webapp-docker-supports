"""Saving and loading a sweep under the one signature everybody agrees on.

The signature used to be computed at each call site. Three call sites, two
implementations, and one — `api_onset_csv` — that passed none at all, which made
"Build onset CSV" answer "not swept yet" for a video that had just been swept.

Anything that touches the sweep cache goes through here.

Two shapes live side by side:

* ``save``/``load`` — the legacy single-camera trace (one score array)
* ``save_pair``/``load_pair`` — the two-camera sweep: both scores plus the
  triangulated distance, stored RAW so the thresholds can be retuned without
  another pass over the video

They are kept in separate keyspaces by ``KIND``. Reading one as the other must
be impossible rather than merely unlikely: a single-camera file read as a pair
would hand cam0's scores back as cam1's, which is precisely the agreement the
two-camera gate exists to prove.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import config, store

SINGLE = "s1"
# p3: the 3D reference moved from the clicked box to the detected pellet, which
# changes every stored dist3d without changing anything else in the key. A cache
# that looks fresh and holds distances measured from a different origin is the
# exact failure this project keeps hitting, so the format marker is bumped and
# the old entries simply miss.
PAIR = "p3"


def signature(model, video, marks=None, kind: str = SINGLE) -> str:
    # The calibration is part of the detector for a pair sweep: dist3d is
    # triangulated with it during the sweep, so switching calibrations must MISS
    # rather than silently reuse distances computed from the old one.
    from . import stereo
    cal = stereo.find_for_video(_project_of(video), video) if kind == PAIR else None
    tail = f"|cal={Path(cal).parent.name}" if cal else ""
    base = store.model_signature(model, Path(video).stem, marks=marks or [])
    return f"{kind}:{base}{tail}"


def _project_of(video):
    """The project a video belongs to, for calibration lookup.

    Read from the environment rather than threaded through every caller: the
    service serves one project, and the alternative is a parameter on six
    functions that would all pass the same value.
    """
    import os
    return os.environ.get(
        "SAM_TRAINING_PROJECT",
        "/user-data/Parra-Data/Disk/DLC-Projects/DREADD-Ali-2026-01-07")


# SUPERSEDED. `save`/`load` below are the single-camera cache; the pipeline uses
# save_pair/load_pair. They are kept only so an old cache can still be read by
# hand. Do not wire them back in: deciding presence from one camera's best
# correlation in one band is what scored 0.85 on a paw with no pellet.
def load(video, model, marks=None, stride: int = config.SWEEP_STRIDE,
         root=None):
    return store.load_sweep(video, stride, root=root,
                            sig=signature(model, video, marks, SINGLE))


def save(video, frames, scores, n_frames, model, marks=None,
         stride: int = config.SWEEP_STRIDE, root=None):
    return store.save_sweep(video, stride, frames, scores, n_frames, root=root,
                            sig=signature(model, video, marks, SINGLE))


# ── two-camera ──────────────────────────────────────────────────────────────


def _pair_path(video, stride, model, marks, root):
    return store.cache_file(video, stride, root,
                            sig=signature(model, video, marks, PAIR))


def save_pair(video, frames, score0, score1, dist3d, n_frames, model,
              marks=None, stride: int = config.SWEEP_STRIDE, root=None):
    """Store the raw per-camera scores and 3D distance.

    Deliberately NOT the armed decision: that is a function of the thresholds,
    and baking it in would mean retuning them costs another seven-minute sweep.
    """
    path = _pair_path(video, stride, model, marks, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, frames=np.asarray(frames),
                        score0=np.asarray(score0, dtype=np.float32),
                        score1=np.asarray(score1, dtype=np.float32),
                        # float32 keeps NaN, which means "the cameras never
                        # agreed here so this was never triangulated". An
                        # integer or 0.0 fill would read as a perfect match.
                        dist3d=np.asarray(dist3d, dtype=np.float32),
                        n_frames=int(n_frames))
    tmp.replace(path)                   # atomic: a killed sweep leaves no stub
    return path


def load_pair(video, model, marks=None, stride: int = config.SWEEP_STRIDE,
              root=None):
    path = _pair_path(video, stride, model, marks, root)
    if not path.is_file():
        return None
    try:
        d = np.load(path)
        return (d["frames"], d["score0"], d["score1"], d["dist3d"],
                int(d["n_frames"]))
    except (OSError, KeyError, ValueError):
        return None                     # a corrupt cache is a miss, not a crash

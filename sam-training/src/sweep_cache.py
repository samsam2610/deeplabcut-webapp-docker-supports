"""Saving and loading a sweep under the one signature everybody agrees on.

The signature used to be computed at each call site. Three call sites, two
implementations, and one — `api_onset_csv` — that passed none at all, which made
"Build onset CSV" answer "not swept yet" for a video that had just been swept.

Anything that touches the sweep cache goes through here.
"""
from __future__ import annotations

from . import config, store


def signature(model, video, marks=None) -> str:
    from pathlib import Path
    return store.model_signature(model, Path(video).stem, marks=marks or [])


def load(video, model, marks=None, stride: int = config.SWEEP_STRIDE,
         root=None):
    return store.load_sweep(video, stride, root=root,
                            sig=signature(model, video, marks))


def save(video, frames, scores, n_frames, model, marks=None,
         stride: int = config.SWEEP_STRIDE, root=None):
    return store.save_sweep(video, stride, frames, scores, n_frames, root=root,
                            sig=signature(model, video, marks))

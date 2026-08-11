"""Overlay geometry for the debug panel.

Geometry is sent as JSON and drawn client-side on a canvas over the frame, so
layers toggle instantly without re-fetching pixels. That matters when the point
is comparing what OpenCV, SAM and DINO each think about the SAME frame — baking
overlays into the JPEG would make that a round trip per toggle.

Every layer carries a ``kind`` the front-end knows how to draw:
    box     {x, y, w, h}          - static ROIs, template match location
    mask    {rle, w, h}           - SAM output, run-length encoded
    scalar  {value, range}        - DINO similarity, NCC score
"""
from __future__ import annotations

import numpy as np


def box_layer(name: str, box, colour: str, label: str = "") -> dict:
    """``box`` is (y0, y1, x0, x1) as used everywhere else in this module."""
    y0, y1, x0, x1 = box
    return {"name": name, "kind": "box", "colour": colour, "label": label,
            "x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0)}


def match_layer(name: str, top_left, size, colour: str, score: float) -> dict:
    x, y = top_left
    h, w = size
    return {"name": name, "kind": "box", "colour": colour,
            "label": f"NCC {score:.2f}",
            "x": int(x), "y": int(y), "w": int(w), "h": int(h)}


def encode_mask(mask) -> dict:
    """Run-length encode a boolean mask, row-major.

    Sent as alternating run lengths starting with False, which for a paw-sized
    blob in an 800x600 frame is a few hundred integers instead of 480 000.
    """
    flat = np.asarray(mask, dtype=bool).ravel()
    if flat.size == 0:
        return {"rle": [], "w": 0, "h": 0}
    changes = np.flatnonzero(np.diff(flat)) + 1
    bounds = np.concatenate(([0], changes, [flat.size]))
    runs = np.diff(bounds).tolist()
    if flat[0]:
        runs = [0] + runs           # always start the run list with False
    h, w = np.asarray(mask).shape
    return {"rle": [int(r) for r in runs], "w": int(w), "h": int(h)}


def mask_layer(name: str, mask, colour: str, label: str = "") -> dict:
    payload = encode_mask(mask)
    return {"name": name, "kind": "mask", "colour": colour, "label": label,
            **payload}


def scalar_layer(name: str, value: float, lo: float = 0.0, hi: float = 1.0,
                 label: str = "") -> dict:
    return {"name": name, "kind": "scalar", "value": float(value),
            "range": [lo, hi], "label": label}


def decode_mask(payload) -> np.ndarray:
    """Inverse of :func:`encode_mask` — used by tests to prove the round trip."""
    w, h = int(payload["w"]), int(payload["h"])
    out = np.zeros(w * h, dtype=bool)
    pos, value = 0, False
    for run in payload["rle"]:
        if value and run:
            out[pos:pos + run] = True
        pos += run
        value = not value
    return out.reshape(h, w)


def downsample_trace(frames, scores, max_points: int = 4000) -> dict:
    """Thin the NCC trace for the timeline.

    Takes the MINIMUM of each bucket rather than a stride sample: the timeline's
    job is showing where the pellet went missing, and a stride sample happily
    steps over a short dropout that a min never misses.
    """
    frames = np.asarray(frames)
    scores = np.asarray(scores)
    if frames.size <= max_points:
        return {"frames": frames.astype(int).tolist(),
                "scores": np.round(scores, 3).astype(float).tolist()}
    bucket = int(np.ceil(frames.size / max_points))
    n = (frames.size // bucket) * bucket
    f = frames[:n].reshape(-1, bucket)
    s = scores[:n].reshape(-1, bucket)
    idx = s.argmin(axis=1)
    return {"frames": f[np.arange(f.shape[0]), idx].astype(int).tolist(),
            "scores": np.round(s.min(axis=1), 3).astype(float).tolist()}

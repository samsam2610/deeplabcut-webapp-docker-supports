"""Read, write and merge the candidate-peak sidecar.

`<pose_h5_stem>_peaks.npz` holds DeepLabCut's top-K heatmap peaks for the frames
that were analysed. It is SPARSE — an explicit frame index — unlike the pose h5,
which is dense because downstream tools index it positionally. Tag runs touch a
few thousand of a video's 251k frames, so dense storage would be ~241 MB of
mostly-NaN against ~2 MB sparse.

numpy only: this must import on the host, where torch and DeepLabCut are absent.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def peaks_sidecar_path(pose_h5_path) -> Path:
    """`/d/vidDLC_x.h5` -> `/d/vidDLC_x_peaks.npz`."""
    p = Path(pose_h5_path)
    return p.with_name(p.stem + "_peaks.npz")


def write_peaks_npz(path, frames, xy, score, bodyparts, meta) -> None:
    """Write the sidecar, sorted by frame.

    Sorting here rather than at every read site means every consumer can rely on
    `frames` being ascending, which is what makes np.searchsorted lookups valid.
    """
    frames = np.asarray(frames, dtype=np.int32).reshape(-1)
    xy = np.asarray(xy, dtype=np.float32)
    score = np.asarray(score, dtype=np.float32)
    bodyparts = [str(b) for b in bodyparts]

    if xy.shape[:2] != (len(frames), len(bodyparts)) or xy.shape[-1] != 2:
        raise ValueError(
            "xy must be (N, B, K, 2) with N={} B={}, got {}".format(
                len(frames), len(bodyparts), xy.shape))
    if score.shape != xy.shape[:3]:
        raise ValueError(
            "score must be (N, B, K), got {} against xy {}".format(
                score.shape, xy.shape))
    if len(np.unique(frames)) != len(frames):
        raise ValueError("duplicate frame numbers in the sidecar index")

    order = np.argsort(frames, kind="stable")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        str(path),
        frames=frames[order],
        xy=xy[order],
        score=score[order],
        bodyparts=np.asarray(bodyparts, dtype=np.str_),
        meta=np.asarray(json.dumps(dict(meta)), dtype=np.str_),
    )


def read_peaks_npz(path) -> dict:
    """Load a sidecar into plain numpy arrays plus a decoded meta dict."""
    with np.load(str(path), allow_pickle=False) as z:
        return {
            "frames": np.asarray(z["frames"], dtype=np.int32),
            "xy": np.asarray(z["xy"], dtype=np.float32),
            "score": np.asarray(z["score"], dtype=np.float32),
            "bodyparts": [str(b) for b in z["bodyparts"]],
            "meta": json.loads(str(z["meta"])),
        }


def merge_peaks(old: dict, new: dict) -> dict:
    """Union the frame indices, preferring `new` where both carry a frame.

    A bodypart or k mismatch is an error rather than a merge: silently mixing
    two models' peaks in one file would corrupt every later lookup, and the
    failure would surface far from its cause.
    """
    if list(old["bodyparts"]) != list(new["bodyparts"]):
        raise ValueError(
            "bodypart mismatch: sidecar has {}, incoming run has {}".format(
                list(old["bodyparts"]), list(new["bodyparts"])))
    if old["xy"].shape[2] != new["xy"].shape[2]:
        raise ValueError(
            "k mismatch: sidecar has k={}, incoming run has k={}".format(
                old["xy"].shape[2], new["xy"].shape[2]))

    keep = ~np.isin(old["frames"], new["frames"])
    frames = np.concatenate([old["frames"][keep], new["frames"]])
    xy = np.concatenate([old["xy"][keep], new["xy"]])
    score = np.concatenate([old["score"][keep], new["score"]])
    order = np.argsort(frames, kind="stable")
    return {
        "frames": frames[order].astype(np.int32),
        "xy": xy[order].astype(np.float32),
        "score": score[order].astype(np.float32),
        "bodyparts": list(new["bodyparts"]),
        "meta": dict(new["meta"]),
    }

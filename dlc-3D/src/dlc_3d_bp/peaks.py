"""Candidate-peak extraction from DeepLabCut heatmaps.

Imports only numpy and scipy.ndimage so it is testable on the host, where
neither torch nor DeepLabCut is installed. The DLC-dependent work lives in
scripts/emit_peaks.py, which runs inside the worker container.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def extract_peaks(heatmap, k: int = 5, min_distance: int = 3):
    """Top-k local maxima of one bodypart's heatmap.

    Returns (xy, scores): xy is (k, 2) float32 in heatmap-cell coordinates as
    (x=column, y=row), NaN-padded; scores is (k,) float32, zero-padded. Both are
    ordered by descending score.

    Non-maximum suppression is not optional: a plain top-k returns the peak cell
    and its neighbours, so k "candidates" would be one detection counted k times.
    """
    hm = np.asarray(heatmap, dtype=np.float32)
    xy = np.full((k, 2), np.nan, dtype=np.float32)
    scores = np.zeros(k, dtype=np.float32)
    if hm.ndim != 2 or hm.size == 0:
        return xy, scores

    # A cell is a candidate when it equals the max of its neighbourhood and is
    # strictly positive, so a flat or empty heatmap yields nothing.
    size = 2 * int(min_distance) + 1
    local_max = ndimage.maximum_filter(hm, size=size, mode="nearest")
    cand = np.argwhere((hm == local_max) & (hm > 0))
    if not len(cand):
        return xy, scores

    vals = hm[cand[:, 0], cand[:, 1]]
    order = np.argsort(-vals)
    cand, vals = cand[order], vals[order]

    # Greedy suppression: keep a candidate only if it clears min_distance from
    # every candidate already kept. maximum_filter alone can still return two
    # cells of one plateau.
    kept_rc = []
    for (r, c), v in zip(cand, vals):
        if any((r - kr) ** 2 + (c - kc) ** 2 < min_distance ** 2 for kr, kc in kept_rc):
            continue
        kept_rc.append((r, c))
        idx = len(kept_rc) - 1
        xy[idx] = (float(c), float(r))   # x = column, y = row
        scores[idx] = float(v)
        if len(kept_rc) == k:
            break
    return xy, scores

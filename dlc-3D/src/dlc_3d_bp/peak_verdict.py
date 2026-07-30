"""Verdict for one bodypart, given DeepLabCut's candidate peaks and the epipolar
line induced by the trusted camera.

The change from the geometry-only rule: instead of asking whether the marker is
CONSISTENT with the line, ask whether the image contains evidence that IDENTIFIES
this part on it. Those differ exactly when several detections satisfy the line —
the adjacent-digit case — and when none do, which is occlusion.

Imports numpy only, so this is testable on the host.
"""
from __future__ import annotations

import numpy as np

# Extends the 0-5 codes in epipolar_core. Declared here rather than imported
# because epipolar_core pulls in cv2, which the pure tests avoid.
RESCUE = 2
AMBIGUOUS = 5
NO_EVIDENCE = 6
CORRECTED = 7


def peak_verdict(peak_dists, peak_scores, t_ok: float, score_floor: float):
    """Decide from the candidate peaks alone.

    peak_dists  -- (K,) distance of each peak to the epipolar line, NaN padded
    peak_scores -- (K,) heatmap score per peak, 0 padded
    Index 0 is DeepLabCut's own argmax, i.e. the marker already in the pose h5.

    Returns (verdict, chosen_index). chosen_index is None unless the verdict is
    RESCUE (index 0) or CORRECTED (the qualifying peak).
    """
    d = np.asarray(peak_dists, dtype=float)
    s = np.asarray(peak_scores, dtype=float)
    qualifies = np.isfinite(d) & (d <= float(t_ok)) & (s >= float(score_floor))
    idx = np.flatnonzero(qualifies)

    if idx.size == 0:
        # Nothing the detector found sits on the line: the image does not
        # support this part being anywhere along it.
        return NO_EVIDENCE, None
    if idx.size > 1:
        # Several detections satisfy the line, so it has identified none of
        # them. Declining is the honest answer.
        return AMBIGUOUS, None
    only = int(idx[0])
    return (RESCUE, 0) if only == 0 else (CORRECTED, only)

"""Veto-only application of candidate-peak evidence to geometry verdicts.

The geometry engine rescues a low-confidence marker that lies on the epipolar
line. That reasoning fails under occlusion: DeepLabCut had no image evidence, so
its marker is a guess, and a one-degree-of-freedom constraint endorses any guess
landing in the band. This screen asks the better question — does the image
contain evidence for this part ON the line — and refuses the rescue when it does
not.

VETO ONLY. Marker positions are never touched. `CORRECTED` is reported so the
audit can say "a different peak was the one on the line", but the applier
refuses it rather than moving anything: measured on labelled data, moving
markers improved a badly-tracked session (23.57 -> 17.27 px) and degraded two
already-accurate ones (8.42 -> 10.33 and 4.45 -> 7.38 px).

This is the vectorised twin of peak_verdict.peak_verdict, which remains the
scalar reference. tests/test_peak_screen.py asserts they agree.

numpy only, so it imports on the host.
"""
from __future__ import annotations

import numpy as np

RESCUE = 2
AMBIGUOUS = 5
NO_EVIDENCE = 6
CORRECTED = 7


def screen_rescues(codes, peak_dists, peak_scores, covered,
                   t_ok: float, score_floor: float):
    """Downgrade RESCUE verdicts unsupported by the candidate peaks.

    codes       -- (n,) geometry verdict per frame for ONE bodypart
    peak_dists  -- (n, K) each peak's distance to the epipolar line, NaN-padded
    peak_scores -- (n, K) each peak's heatmap score, 0-padded
    covered     -- (n,) bool, whether the sidecar has a row for this frame
    Peak index 0 is DeepLabCut's argmax, i.e. the marker already in the pose h5.

    Returns (new_codes, stats). Only cells that are RESCUE *and* covered can
    change; everything else is passed through, including uncovered rescues —
    absence of peaks is not absence of evidence.
    """
    out = np.array(codes, dtype=np.uint8, copy=True)
    d = np.asarray(peak_dists, dtype=float)
    s = np.asarray(peak_scores, dtype=float)
    cov = np.asarray(covered, dtype=bool)

    is_rescue = out == RESCUE
    active = is_rescue & cov
    stats = {
        "rescues": int(is_rescue.sum()),
        "covered": int(active.sum()),
        "kept": 0, "refused": 0,
        "ambiguous": 0, "no_evidence": 0, "corrected": 0,
    }
    if not active.any():
        return out, stats

    qualifies = np.isfinite(d) & (d <= float(t_ok)) & (s >= float(score_floor))
    n_qual = qualifies.sum(axis=1)
    argmax_ok = qualifies[:, 0] if qualifies.shape[1] else np.zeros(len(out), bool)

    none_on_line = active & (n_qual == 0)
    several = active & (n_qual > 1)
    only_argmax = active & (n_qual == 1) & argmax_ok
    only_other = active & (n_qual == 1) & ~argmax_ok

    out[none_on_line] = NO_EVIDENCE
    out[several] = AMBIGUOUS
    out[only_other] = CORRECTED
    # only_argmax keeps RESCUE.

    stats["no_evidence"] = int(none_on_line.sum())
    stats["ambiguous"] = int(several.sum())
    stats["corrected"] = int(only_other.sum())
    stats["kept"] = int(only_argmax.sum())
    stats["refused"] = (stats["no_evidence"] + stats["ambiguous"]
                        + stats["corrected"])
    return out, stats

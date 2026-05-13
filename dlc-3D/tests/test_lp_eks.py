"""Tests for the EKS smoothing wrappers.

The ``eks`` package is GPU-adjacent and only installed inside the
``dlc-3d-worker`` image — not on the host. We use ``importorskip`` so this
test file cleanly skips on the host and exercises real behaviour when the
worker runs it.
"""
import csv
from pathlib import Path

import pytest

eks = pytest.importorskip("eks")

from dlc_3d_bp.lp.eks_runner import smooth_single_view_csv  # noqa: E402


def _write_lp_predictions(path: Path, n_frames: int = 60) -> None:
    """Write a tiny synthetic LP-format predictions CSV (2 keypoints).

    LP/DLC three-row header: scorer / bodyparts / coords. Frame column 0
    is the image basename; the remaining triplets are (x, y, likelihood)
    per keypoint.
    """
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scorer", "lpmodel", "lpmodel", "lpmodel",
                    "lpmodel", "lpmodel", "lpmodel"])
        w.writerow(["bodyparts", "kp1", "kp1", "kp1",
                    "kp2", "kp2", "kp2"])
        w.writerow(["coords", "x", "y", "likelihood",
                    "x", "y", "likelihood"])
        for i in range(n_frames):
            w.writerow([
                f"img{i:08d}.png",
                100 + i + (i % 5), 200 + i, 0.95,
                300 - i, 150 + i, 0.90,
            ])


def test_smooth_single_view_csv(tmp_path):
    in_csv = tmp_path / "pred.csv"
    out_csv = tmp_path / "smoothed" / "pred_eks.csv"
    _write_lp_predictions(in_csv)

    result = smooth_single_view_csv(in_csv, out_csv, s=1.0)

    assert out_csv.is_file(), "EKS output CSV was not written"
    assert result["n_frames"] >= 1
    assert result["out_path"] == str(out_csv)

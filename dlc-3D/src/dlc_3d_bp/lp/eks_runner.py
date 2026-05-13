"""EKS post-hoc smoothing wrapper.

Single-view (one CSV) and multi-view (per-cam CSV set) entry points.
We import ``eks`` lazily so the Flask container — which does not have EKS
installed — can still import this module without crashing.

EKS 4.6.0 exposes its single-camera smoother under
``eks.singlecam_smoother`` and its multi-camera smoother under
``eks.multicam_smoother``. (Earlier versions referred to these as
``singleview_smoother`` / ``multiview_pca_smoother``.) The high-level
``fit_eks_*`` helpers accept a list of CSV paths (treated as an ensemble of
predictions) and write the smoothed output for us.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


def smooth_single_view_csv(in_csv: Path | str, out_csv: Path | str, s: float = 1.0) -> dict:
    """Run single-camera EKS on an LP/DLC-format predictions CSV.

    The input CSV is treated as an ensemble of size 1 (a single model's
    predictions). EKS writes the smoothed DataFrame to ``out_csv``.

    Returns ``{"n_frames": N, "out_path": str}``.
    """
    from eks.singlecam_smoother import fit_eks_singlecam

    in_csv = Path(in_csv)
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    df_smoothed, _s_finals, _input_dfs, _bp = fit_eks_singlecam(
        input_source=[str(in_csv)],
        save_file=str(out_csv),
        smooth_param=float(s),
    )
    return {"n_frames": int(len(df_smoothed)), "out_path": str(out_csv)}


def smooth_multiview_csvs(
    in_csvs: Iterable[Path | str],
    out_dir: Path | str,
    s: float = 1.0,
    camera_names: list[str] | None = None,
) -> dict:
    """Run multi-camera EKS over per-cam predictions CSVs.

    Each input CSV is expected to encode a single model's predictions for
    one camera view. EKS writes ``multicam_<camera>_results.csv`` per view
    plus an optional ``multicam_3d_results.csv`` into ``out_dir``.

    If ``camera_names`` is not provided, the camera tag is inferred from
    each CSV's stem (``<stem>``) — the filename must contain the camera
    name as a substring for EKS' file-to-camera matching to work.

    Returns ``{"out_paths": [...], "n_views": int}``.
    """
    from eks.multicam_smoother import fit_eks_multicam

    in_csvs = [Path(c) for c in in_csvs]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if camera_names is None:
        camera_names = [c.stem for c in in_csvs]

    fit_eks_multicam(
        input_source=[str(c) for c in in_csvs],
        save_dir=str(out_dir),
        camera_names=camera_names,
        smooth_param=float(s),
        save_3d_outputs=False,
    )

    out_paths = [str(out_dir / f"multicam_{cam}_results.csv") for cam in camera_names]
    return {"out_paths": out_paths, "n_views": len(in_csvs)}

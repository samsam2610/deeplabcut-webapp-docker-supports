"""Celery tasks for lightning-pose training and EKS smoothing."""
from pathlib import Path

from .celery_app import celery


@celery.task(bind=True, name="dlc_3d_lp.train")
def lp_train(self, model_dir: str, options: dict) -> dict:
    """Stub — implemented in Phase 5."""
    return {"status": "stub", "model_dir": model_dir, "options": options}


@celery.task(bind=True, name="dlc_3d_lp.eks")
def lp_eks(self, spec: dict) -> dict:
    """Run EKS smoothing per ``spec`` and return paths.

    ``spec`` keys:
      * ``mode``:     ``"single"`` | ``"multi"``
      * ``in_paths``: list[str] (one for single, N for multi)
      * ``out_csv``:  str (single mode)
      * ``out_dir``:  str (multi mode)
      * ``s``:        float, EKS smoothing parameter (default 1.0)
    """
    from .eks_runner import smooth_single_view_csv, smooth_multiview_csvs

    mode = spec.get("mode")
    s = float(spec.get("s", 1.0))
    if mode == "single":
        in_path = Path(spec["in_paths"][0])
        out_csv = Path(spec["out_csv"])
        return {"mode": "single", **smooth_single_view_csv(in_path, out_csv, s=s)}
    if mode == "multi":
        return {
            "mode": "multi",
            **smooth_multiview_csvs(spec["in_paths"], spec["out_dir"], s=s),
        }
    raise ValueError(f"unknown mode: {mode!r}")

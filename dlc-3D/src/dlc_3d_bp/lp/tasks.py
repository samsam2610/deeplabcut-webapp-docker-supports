"""Celery tasks for lightning-pose training and EKS smoothing."""
from pathlib import Path

from .celery_app import celery


@celery.task(bind=True, name="dlc_3d_lp.train")
def lp_train(self, lp_project: str, options: dict) -> dict:
    """Build the run config from `options` and run `litpose train`."""
    import os
    from .train_runner import build_train_config, make_run_dir, run_train_subprocess

    project = Path(lp_project)
    base_config = project / "config.yaml"
    if not base_config.is_file():
        raise FileNotFoundError(f"LP base config not found at {base_config}")

    run_dir = make_run_dir(project)
    run_cfg = run_dir / "config.yaml"
    build_train_config(base_config, run_cfg, options)

    log_key = f"dlc3d:lp:log:{self.request.id}"
    try:
        import redis
        rconn = redis.Redis.from_url(
            os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
            decode_responses=True,
        )
    except Exception:
        rconn = None

    def emit(line: str) -> None:
        if rconn:
            try:
                rconn.rpush(log_key, line)
                rconn.ltrim(log_key, -2000, -1)
            except Exception:
                pass
        self.update_state(state="STARTED", meta={"last_line": line, "run_dir": str(run_dir)})

    rc = run_train_subprocess(run_dir, log_callback=emit)
    if rc != 0:
        raise RuntimeError(f"litpose train exited with code {rc}")
    return {"status": "ok", "run_dir": str(run_dir)}


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


@celery.task(bind=True, name="dlc_3d_lp.predict")
def lp_predict(self, model_dir: str, videos: list, skip_viz: bool = False, overwrite: bool = False) -> dict:
    """Run `litpose predict <model_dir> <video...>`.

    Output lands under ``<model_dir>/video_preds/``. Streams stdout to a Redis
    log list and updates Celery state per line for live UI polling.
    """
    import os
    from .predict_runner import run_predict_subprocess

    if not videos:
        raise ValueError("at least one video path required")
    md = Path(model_dir)
    if not md.is_dir():
        raise FileNotFoundError(f"model_dir does not exist: {model_dir}")

    log_key = f"dlc3d:lp:log:{self.request.id}"
    try:
        import redis
        rconn = redis.Redis.from_url(
            os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
            decode_responses=True,
        )
    except Exception:
        rconn = None

    def emit(line: str) -> None:
        if rconn:
            try:
                rconn.rpush(log_key, line)
                rconn.ltrim(log_key, -2000, -1)
            except Exception:
                pass
        self.update_state(state="STARTED", meta={"last_line": line, "model_dir": str(md)})

    rc = run_predict_subprocess(md, videos, skip_viz=skip_viz, overwrite=overwrite, log_callback=emit)
    if rc != 0:
        raise RuntimeError(f"litpose predict exited with code {rc}")
    return {"status": "ok", "model_dir": str(md), "video_preds_dir": str(md / "video_preds")}

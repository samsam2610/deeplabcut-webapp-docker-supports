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
def lp_predict(self, model_dir: str, videos: list, skip_viz: bool = False, overwrite: bool = False, dest_dir: str = "") -> dict:
    """Run `litpose predict <model_dir> <video...>`, then relocate outputs.

    Before invoking litpose:
      - Reads model view_names from <model_dir>/config.yaml.
      - For multi-view models: resolves sibling _camN_ files in the same dir.
      - Transcodes any non-mp4 inputs to mp4 via ffmpeg (cached, stream-copy
        with libx264 fallback).

    Output relocation runs after predict — see relocate_predictions().
    """
    import os
    from .predict_runner import run_predict_subprocess, relocate_predictions, prepare_predict_inputs, emit_h5_sidecars

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

    # ── Resolve siblings + transcode ────────────────────────────────────
    prep = prepare_predict_inputs(md, videos)
    if not prep["mp4_paths"]:
        raise RuntimeError(
            f"no usable sessions after sibling resolution: {prep['sibling_warnings']}"
        )
    emit(f"prepared {len(prep['mp4_paths'])} mp4 input(s); "
         f"transcoded {len(prep['transcoded'])}; "
         f"warnings: {len(prep['sibling_warnings'])}")
    for w in prep["sibling_warnings"]:
        emit(f"  warning: {w}")

    # ── Run litpose predict on the resolved mp4 list ────────────────────
    rc = run_predict_subprocess(md, prep["mp4_paths"], skip_viz=skip_viz, overwrite=overwrite, log_callback=emit)
    if rc != 0:
        raise RuntimeError(f"litpose predict exited with code {rc}")

    # ── Move outputs to dest_dir (or per-video parent) ─────────────────
    relocate_info = relocate_predictions(md, prep["mp4_paths"], dest_dir=(dest_dir or None), overwrite=overwrite)
    emit(f"relocated {relocate_info['moved']} file(s); skipped {len(relocate_info['skipped'])}")

    # ── Emit H5 sidecars (main webapp's analyzed-viewer uses pd.read_hdf) ─
    h5_info = emit_h5_sidecars(relocate_info.get("dest_paths") or [])
    emit(f"emitted {len(h5_info['emitted'])} H5 sidecar(s)")

    return {
        "status": "ok",
        "model_dir": str(md),
        "dest_dir": relocate_info["dest_dir"] or "<per-video parent>",
        "moved": relocate_info["moved"],
        "skipped": relocate_info["skipped"],
        "h5_emitted": h5_info["emitted"],
        "h5_skipped": h5_info["skipped"],
        "transcoded": prep["transcoded"],
        "sibling_warnings": prep["sibling_warnings"],
        "is_multiview": prep["is_multiview"],
        "view_names": prep["view_names"],
    }

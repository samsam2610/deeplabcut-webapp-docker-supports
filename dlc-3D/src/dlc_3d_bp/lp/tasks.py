"""Celery tasks for lightning-pose training and EKS smoothing."""
from pathlib import Path

import yaml

from .celery_app import celery


def _lp_train_impl(self, lp_project: str, options: dict) -> dict:
    """Train an LP model. Single-stage MVT by default; two-stage curriculum
    (SV-pretrain → MVT with backbone transfer) when ``options.two_stage`` is True."""
    import os
    from pathlib import Path as _Path
    from . import train_runner as _tr

    build_train_config = _tr.build_train_config
    build_stage1_config = _tr.build_stage1_config
    find_best_checkpoint = _tr.find_best_checkpoint
    make_run_dir = _tr.make_run_dir

    proj = _Path(lp_project)
    if not (proj / "config.yaml").is_file():
        raise FileNotFoundError(f"LP project config not found at {proj}/config.yaml")

    log_key = f"dlc3d:lp:log:{self.request.id}"
    try:
        import redis
        rconn = redis.Redis.from_url(
            os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
            decode_responses=True,
        )
    except Exception:
        rconn = None

    # ── Redelivery guard ────────────────────────────────────────────────
    # Celery + Redis broker + acks_late=True will re-deliver any task whose
    # original execution didn't cleanly ack (worker crash, OOM, mid-flight
    # cancellation that didn't propagate, etc.). On redelivery the task ID
    # is the same, so an existing log key with real training/predict
    # progress under this ID is the signature. Bail with a clear error so
    # the second execution doesn't burn another ~3 hours of GPU on a run
    # the user never asked for, and so the broker stops endlessly retrying.
    if rconn is not None:
        try:
            prior = rconn.lrange(log_key, 0, -1)
        except Exception:
            prior = []
        _PROGRESS_MARKERS = ("Epoch ", "STAGE ", "Predicting DataLoader", "Training:")
        if prior and any(any(m in line for m in _PROGRESS_MARKERS) for line in prior):
            msg = (
                f"redelivery detected: task {self.request.id} already ran "
                f"({len(prior)} prior log lines, last: {prior[-1][:120]!r}). "
                "Refusing to re-execute; revoke this task via /lp/job/<id>/cancel "
                "if it shows up again."
            )
            try:
                rconn.rpush(log_key, msg); rconn.ltrim(log_key, -2000, -1)
            except Exception:
                pass
            raise RuntimeError(msg)

    def emit(line: str, **meta) -> None:
        if rconn:
            try:
                rconn.rpush(log_key, line); rconn.ltrim(log_key, -2000, -1)
            except Exception:
                pass
        self.update_state(state="STARTED",
                          meta={"last_line": line, "lp_project": str(proj), **meta})

    # ── Two-stage branch ────────────────────────────────────────────────
    two_stage = bool(options.get("two_stage", False))
    override_ckpt = (options.get("stage1_ckpt_override") or "").strip()

    if two_stage:
        run_root = make_run_dir(proj)  # <proj>/models/<timestamp>/
        stage1_dir = run_root / "stage1"
        stage2_dir = run_root / "stage2"

        stage1_ckpt: _Path | None = None
        if override_ckpt:
            emit(f"two-stage: using override ckpt {override_ckpt} — skipping stage 1",
                 stage="stage1_override")
            stage1_ckpt = _Path(override_ckpt)
        else:
            sv_project = proj / "sv-pretrain"
            if not (sv_project / "config.yaml").is_file():
                raise FileNotFoundError(
                    f"two-stage requested but {sv_project}/config.yaml missing; "
                    "re-run convert with a current converter to emit sv-pretrain"
                )
            stage1_dir.mkdir(parents=True, exist_ok=True)
            build_stage1_config(sv_project=sv_project, out_dir=stage1_dir, options=options)
            emit("two-stage: STAGE 1 starting (sv-pretrain)", stage="stage1_training")
            rc = _tr.run_train_subprocess(stage1_dir, log_callback=lambda l: emit(l, stage="stage1_training"))
            if rc != 0:
                raise RuntimeError(f"stage 1 litpose train exited with code {rc}")
            stage1_ckpt = find_best_checkpoint(stage1_dir)
            if stage1_ckpt is None:
                raise RuntimeError(f"stage 1 produced no checkpoint under {stage1_dir}")
            emit(f"two-stage: STAGE 1 done — ckpt {stage1_ckpt}", stage="stage1_done")

        # Stage 2 (MVT)
        stage2_dir.mkdir(parents=True, exist_ok=True)
        stage2_options = dict(options)
        # Strip stage-1 keys so build_train_config doesn't see them
        for k in ("two_stage", "stage1_max_epochs", "stage1_early_stop_patience", "stage1_ckpt_override"):
            stage2_options.pop(k, None)
        # Pass through semi-supervised + parent videos dir so build_train_config
        # can construct the filtered videos_mvt_filtered/ subdir for MVT.
        if stage2_options.get("semi_supervised_enabled"):
            stage2_options.setdefault("parent_videos_dir", str(proj / "videos"))
            stage2_options.setdefault("stage2_dir", str(stage2_dir))
        build_train_config(proj / "config.yaml", stage2_dir / "config.yaml", stage2_options)

        # Inject model.checkpoint into the just-written stage-2 config
        s2_cfg_path = stage2_dir / "config.yaml"
        s2_cfg = yaml.safe_load(s2_cfg_path.read_text())
        s2_cfg.setdefault("model", {})["checkpoint"] = str(stage1_ckpt)
        s2_cfg_path.write_text(yaml.safe_dump(s2_cfg, sort_keys=False))

        emit("two-stage: STAGE 2 starting (MVT with backbone transfer)", stage="stage2_training")
        rc = _tr.run_train_subprocess(stage2_dir, log_callback=lambda l: emit(l, stage="stage2_training"))
        if rc != 0:
            raise RuntimeError(f"stage 2 litpose train exited with code {rc}")
        emit("two-stage: STAGE 2 done", stage="stage2_done")
        return {
            "status": "ok",
            "lp_project": str(proj),
            "run_dir": str(run_root),
            "stage1_ckpt": str(stage1_ckpt),
            "stage": "stage2_done",
        }

    # ── Single-stage MVT branch (existing behaviour, unchanged contract) ─
    run_dir = make_run_dir(proj)
    build_train_config(proj / "config.yaml", run_dir / "config.yaml", options)
    rc = _tr.run_train_subprocess(run_dir, log_callback=emit)
    if rc != 0:
        raise RuntimeError(f"litpose train exited with code {rc}")
    return {"status": "ok", "lp_project": str(proj), "run_dir": str(run_dir), "stage": "done"}


lp_train = celery.task(bind=True, name="dlc_3d_lp.train")(_lp_train_impl)
# Expose the raw function via __wrapped__ so tests can invoke with their own self.
lp_train.__wrapped__ = _lp_train_impl


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

    # Redelivery guard — see lp_train for the rationale. Predict tasks on
    # 250k+ frame videos take 25+ minutes; we don't want them silently
    # restarting after a worker reset.
    if rconn is not None:
        try:
            prior = rconn.lrange(log_key, 0, -1)
        except Exception:
            prior = []
        _PROGRESS_MARKERS = ("Predicting DataLoader", "transcoding", "prepared ", "relocated ")
        if prior and any(any(m in line for m in _PROGRESS_MARKERS) for line in prior):
            msg = (
                f"redelivery detected: task {self.request.id} already ran "
                f"({len(prior)} prior log lines). Refusing to re-execute."
            )
            try:
                rconn.rpush(log_key, msg); rconn.ltrim(log_key, -2000, -1)
            except Exception:
                pass
            raise RuntimeError(msg)

    def emit(line: str) -> None:
        if rconn:
            try:
                rconn.rpush(log_key, line)
                rconn.ltrim(log_key, -2000, -1)
            except Exception:
                pass
        self.update_state(state="STARTED", meta={"last_line": line, "model_dir": str(md)})

    # ── Resolve siblings + transcode ────────────────────────────────────
    # Emit BEFORE prepare_predict_inputs so the task transitions PENDING →
    # STARTED immediately. Transcoding 10 GB AVIs can take 3+ minutes each;
    # without an early emit, the Jobs card shows PENDING-with-empty-log and
    # the run looks hung.
    emit(f"preparing inputs (transcoding {len(videos)} video(s) to mp4 if needed)…")
    prep = prepare_predict_inputs(md, videos, emit=emit)
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
    # Key off prediction_csv_paths so H5s are produced even when relocation
    # was skipped (dest existed + overwrite=False) — the fresh CSV still lives
    # at <model_dir>/video_preds/<stem>.csv and deserves a sidecar.
    h5_info = emit_h5_sidecars(relocate_info.get("prediction_csv_paths") or [])
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

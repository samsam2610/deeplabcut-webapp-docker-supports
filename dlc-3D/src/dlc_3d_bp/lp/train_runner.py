"""Lightning-pose training wrapper.

`build_train_config` is a pure config-shaping function (no GPU, no LP imports);
`run_train_subprocess` shells out to `litpose train`. The Celery task drives
both.
"""
from __future__ import annotations

import datetime
import os
import subprocess
import time
from pathlib import Path

import yaml

_DEFAULT_PATCH_MASKING = {
    "enabled": False,
    "init_epoch": 5,
    "final_epoch": 50,
    "init_ratio": 0.0,
    "final_ratio": 0.5,
}


def make_run_dir(lp_project: Path | str) -> Path:
    lp_project = Path(lp_project)
    runs = lp_project / "models"
    runs.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = runs / ts
    d.mkdir()
    return d


def build_train_config(
    base_config_path: Path | str,
    out_path: Path | str,
    options: dict,
) -> None:
    """Read the LP project's base config.yaml, apply options, write to out_path."""
    base_config_path = Path(base_config_path)
    out_path = Path(out_path)
    cfg = yaml.safe_load(base_config_path.read_text()) or {}
    cfg.setdefault("data", {})
    cfg.setdefault("model", {})
    cfg.setdefault("training", {})
    cfg.setdefault("losses", {})
    cfg.setdefault("eval", {})
    # LP 2.1.0's predict reads cfg.dali directly; bake defaults at train time so
    # predict doesn't need a runtime injection on the resulting model dir.
    cfg.setdefault("dali", {
        "general": {"seed": 123456},
        "base": {
            "train":   {"sequence_length": 32},
            "predict": {"sequence_length": 96},
        },
        "context": {
            "train":   {"batch_size": 16},
            "predict": {"sequence_length": 96},
        },
    })

    # MVT toggle. LP 2.1.0 calls the supervised multi-view model
    # ``heatmap_multiview_transformer``; older naming was ``multiview_heatmap``.
    if options.get("mvt_enabled", True):
        cfg["model"]["model_type"] = "heatmap_multiview_transformer"
    elif options.get("model_type"):
        cfg["model"]["model_type"] = options["model_type"]

    if options.get("backbone"):
        cfg["model"]["backbone"] = options["backbone"]

    # Patch masking
    if options.get("patch_masking_enabled"):
        pm = dict(_DEFAULT_PATCH_MASKING)
        pm.update({
            "enabled": True,
            "init_epoch":  options.get("patch_masking_init_epoch", pm["init_epoch"]),
            "final_epoch": options.get("patch_masking_final_epoch", pm["final_epoch"]),
            "init_ratio":  options.get("patch_masking_init_ratio", pm["init_ratio"]),
            "final_ratio": options.get("patch_masking_final_ratio", pm["final_ratio"]),
        })
        cfg["model"].setdefault("mvt", {})["patch_masking"] = pm

    # 3D reprojection loss. LP 2.1.0 anneals the unsupervised-loss weight via
    # the AnnealWeight callback, which is required to exist whenever an
    # unsupervised loss like supervised_reprojection_heatmap_mse is present.
    if options.get("reproj_loss_enabled"):
        cfg["training"]["imgaug_3d"] = True
        cfg["losses"]["supervised_reprojection_heatmap_mse"] = {
            "log_weight": options.get("reproj_loss_log_weight", 3.0),
        }
        cfg.setdefault("callbacks", {})["anneal_weight"] = {
            "attr_name": "total_unsupervised_importance",
            "init_val": 0.0,
            "increase_factor": 0.01,
            "final_val": 1.0,
            "freeze_until_epoch": 0,
        }

    # Training params
    for src, dst in (("max_epochs", "max_epochs"),
                     ("batch_size", "train_batch_size"),
                     ("batch_size", "val_batch_size"),
                     ("batch_size", "test_batch_size")):
        if src in options:
            cfg["training"][dst] = options[src]

    # Keep min_epochs <= max_epochs. LP 2.1.0 asserts both keys are present and
    # uses them as PL Trainer args; min_epochs > max_epochs would error.
    if "max_epochs" in options:
        cfg["training"]["min_epochs"] = min(
            cfg["training"].get("min_epochs", 1), int(options["max_epochs"])
        )
    # Lr scheduler milestones must be <= max_epochs or the multi-step LR is
    # a no-op for short smoke runs — that's fine, but ensure the list isn't
    # required to be filtered. (left as-is)

    # Eval flags
    if "predict_vids_after_training" in options:
        cfg["eval"]["predict_vids_after_training"] = bool(options["predict_vids_after_training"])
    if "save_vids_after_training" in options:
        cfg["eval"]["save_vids_after_training"] = bool(options["save_vids_after_training"])

    out_path.write_text(yaml.safe_dump(cfg, sort_keys=False))


def run_train_subprocess(model_dir: Path | str, log_callback=None, cwd: Path | str | None = None) -> int:
    """Spawn `litpose train`. Return process returncode.

    log_callback: optional callable(line: str) -> None invoked once per stdout line.

    The installed `litpose` 2.1.0 CLI takes the config as a positional argument
    (not `--config`), and supports `--output_dir` for the model directory.
    """
    model_dir = Path(model_dir)
    cfg = model_dir / "config.yaml"
    cmd = ["litpose", "train", str(cfg), "--output_dir", str(model_dir)]
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "0"}
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=str(cwd) if cwd else None,
        env=env,
    )
    last_emit = time.time()
    for line in proc.stdout:  # type: ignore[union-attr]
        if log_callback:
            try:
                log_callback(line.rstrip("\n"))
            except Exception:
                pass
        if time.time() - last_emit > 5:
            last_emit = time.time()
    return proc.wait()


def find_best_checkpoint(model_dir) -> Path | None:
    """Return the newest ``*-best.ckpt`` under ``<model_dir>/tb_logs/.../checkpoints/``.

    Falls back to any ``*.ckpt`` if no *-best is present. Returns None when
    no checkpoint exists at all.
    """
    model_dir = Path(model_dir)
    best = list(model_dir.glob("tb_logs/*/version_*/checkpoints/*-best.ckpt"))
    if best:
        return max(best, key=lambda p: p.stat().st_mtime)
    any_ckpt = list(model_dir.glob("tb_logs/*/version_*/checkpoints/*.ckpt"))
    if any_ckpt:
        return max(any_ckpt, key=lambda p: p.stat().st_mtime)
    return None


def build_stage1_config(
    sv_project,
    out_dir,
    options: dict,
) -> None:
    """Materialise stage-1's config.yaml at ``<out_dir>/config.yaml``.

    Starts from the SV-pretrain project's ``config.yaml`` and overlays
    short-run + early-stopping defaults so stage 1 finishes quickly once
    val loss plateaus.
    """
    sv_cfg_path = Path(sv_project) / "config.yaml"
    cfg = yaml.safe_load(sv_cfg_path.read_text()) or {}
    training = cfg.setdefault("training", {})
    max_epochs = int(options.get("stage1_max_epochs", 100))
    training["max_epochs"] = max_epochs
    training["min_epochs"] = min(training.get("min_epochs", 1) or 1, max_epochs)
    training["early_stopping"] = True
    training["early_stop_patience"] = int(options.get("stage1_early_stop_patience", 5))
    # No unsupervised losses, no patch masking, no reproj for stage 1.
    cfg.setdefault("losses", {})
    cfg.setdefault("callbacks", {})
    Path(out_dir, "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))

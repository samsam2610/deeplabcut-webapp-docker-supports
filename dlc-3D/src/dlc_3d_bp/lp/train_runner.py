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

    # 3D reprojection loss
    if options.get("reproj_loss_enabled"):
        cfg["training"]["imgaug_3d"] = True
        cfg["losses"]["supervised_reprojection_heatmap_mse"] = {
            "log_weight": options.get("reproj_loss_log_weight", 3.0),
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

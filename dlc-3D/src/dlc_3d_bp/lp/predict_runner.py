"""Lightning-pose inference wrapper.

Lists trained model run dirs in an LP project and spawns `litpose predict`
to run inference on one or more videos. Output lands under
``<model_dir>/video_preds/`` per LP's convention.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Iterable


def list_models(lp_project: Path | str) -> list[dict]:
    """Return [{run_id, path, has_checkpoint, has_predictions, status}, ...] sorted newest-first."""
    lp_project = Path(lp_project)
    models_dir = lp_project / "models"
    if not models_dir.is_dir():
        return []
    out: list[dict] = []
    for d in sorted(models_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        ckpts = list(d.glob("tb_logs/*/version_*/checkpoints/*.ckpt"))
        preds = list(d.glob("predictions_*.csv"))
        status_file = d / "train_status.json"
        status = ""
        if status_file.is_file():
            try:
                import json
                status = (json.loads(status_file.read_text()) or {}).get("status", "")
            except Exception:
                status = ""
        out.append({
            "run_id": d.name,
            "path": str(d),
            "has_checkpoint": bool(ckpts),
            "has_predictions": bool(preds),
            "status": status,
        })
    return out


def run_predict_subprocess(
    model_dir: Path | str,
    inputs: Iterable[Path | str],
    skip_viz: bool = False,
    overwrite: bool = False,
    log_callback=None,
) -> int:
    """Spawn `litpose predict <model_dir> <input...>`. Returns process returncode.

    LP writes per-video CSVs to ``<model_dir>/video_preds/`` (and labeled MP4s
    to ``<model_dir>/video_preds/labeled_videos/`` unless --skip_viz).
    """
    model_dir = Path(model_dir)
    cmd = ["litpose", "predict", str(model_dir), *[str(p) for p in inputs]]
    if skip_viz:
        cmd.append("--skip_viz")
    if overwrite:
        cmd.append("--overwrite")

    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "0"}
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=env,
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

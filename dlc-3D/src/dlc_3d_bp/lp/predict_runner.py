"""Lightning-pose inference wrapper.

Lists trained model run dirs in an LP project and spawns `litpose predict`
to run inference on one or more videos. Output lands under
``<model_dir>/video_preds/`` per LP's convention.
"""
from __future__ import annotations

import os
import shutil
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


def relocate_predictions(
    model_dir: Path | str,
    videos: Iterable[Path | str],
    dest_dir: Path | str | None = None,
    overwrite: bool = False,
) -> dict:
    """Move per-video outputs from <model_dir>/video_preds/ to their final home.

    For each input video, looks under <model_dir>/video_preds/ for:
      - <stem>.csv                            (predictions)
      - <stem>_*.csv                          (per-metric losses)
      - labeled_videos/<stem>_labeled.mp4     (only if rendered)

    If ``dest_dir`` is None (or falsy), each video's outputs land in that
    video's parent directory. Otherwise everything lands in ``dest_dir``.
    The labeled MP4 is renamed to ``<stem>_labeled.mp4`` at the destination.

    When a destination file already exists and ``overwrite`` is False, the
    move is skipped and the source path is recorded in the ``skipped`` list.

    Returns {"moved": int, "skipped": [str], "dest_dir": str | None}.
    """
    model_dir = Path(model_dir)
    vp = model_dir / "video_preds"
    labeled = vp / "labeled_videos"
    moved = 0
    skipped: list[str] = []

    explicit_dest = Path(dest_dir) if dest_dir else None

    for v in videos:
        v = Path(v)
        stem = v.stem
        target_dir = explicit_dest if explicit_dest is not None else v.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        for src in sorted(vp.glob(f"{stem}.csv")) + sorted(vp.glob(f"{stem}_*.csv")):
            dst = target_dir / src.name
            if dst.exists() and not overwrite:
                skipped.append(str(src))
                continue
            shutil.move(str(src), str(dst))
            moved += 1

        mp4 = labeled / f"{stem}_labeled.mp4"
        if mp4.is_file():
            dst = target_dir / f"{stem}_labeled.mp4"
            if dst.exists() and not overwrite:
                skipped.append(str(mp4))
            else:
                shutil.move(str(mp4), str(dst))
                moved += 1

    # Tidy: drop labeled_videos/ and video_preds/ if empty after moves
    if labeled.is_dir() and not any(labeled.iterdir()):
        labeled.rmdir()
    if vp.is_dir() and not any(vp.iterdir()):
        vp.rmdir()

    return {
        "moved": moved,
        "skipped": skipped,
        "dest_dir": str(explicit_dest) if explicit_dest is not None else None,
    }

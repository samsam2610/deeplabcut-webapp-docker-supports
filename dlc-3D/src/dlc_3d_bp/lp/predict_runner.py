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

    Destination filenames are renamed with an ``_lp`` infix so they never
    collide with same-named user files (e.g., a DLC annotation `<stem>.csv`
    sitting next to the source video):
      - ``<stem>.csv``                → ``<stem>_lp.csv``
      - ``<stem>_<metric>.csv``       → ``<stem>_lp_<metric>.csv``
      - ``<stem>_labeled.mp4``        → ``<stem>_lp_labeled.mp4``

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

    def _lp_name(src_name: str, stem: str) -> str:
        """Insert '_lp' after the video stem so we never collide with user files."""
        if src_name == f"{stem}.csv":
            return f"{stem}_lp.csv"
        if src_name.startswith(f"{stem}_") and src_name.endswith(".csv"):
            tail = src_name[len(stem) + 1:]  # e.g. "pixel_error.csv"
            return f"{stem}_lp_{tail}"
        if src_name == f"{stem}_labeled.mp4":
            return f"{stem}_lp_labeled.mp4"
        return src_name  # unknown shape — leave as-is

    for v in videos:
        v = Path(v)
        stem = v.stem
        target_dir = explicit_dest if explicit_dest is not None else v.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        for src in sorted(vp.glob(f"{stem}.csv")) + sorted(vp.glob(f"{stem}_*.csv")):
            dst = target_dir / _lp_name(src.name, stem)
            if dst.exists() and not overwrite:
                skipped.append(str(src))
                continue
            shutil.move(str(src), str(dst))
            moved += 1

        mp4 = labeled / f"{stem}_labeled.mp4"
        if mp4.is_file():
            dst = target_dir / _lp_name(mp4.name, stem)
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


# ─────────────────────────────────────────────────────────────────────────────
# Multi-view pairing + AVI transcoding helpers
# ─────────────────────────────────────────────────────────────────────────────
import yaml


def _load_view_names(model_dir: "Path | str") -> list[str]:
    """Return `data.view_names` from `<model_dir>/config.yaml`, or [] if missing.

    Returns [] for single-view models (where view_names is missing or has 0/1 entries).
    """
    cfg_path = Path(model_dir) / "config.yaml"
    if not cfg_path.is_file():
        return []
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return []
    views = (cfg.get("data") or {}).get("view_names") or []
    if not isinstance(views, list):
        return []
    return [str(v) for v in views]


import re


def _resolve_siblings(videos: "list[Path | str]", view_names: list) -> dict:
    """Group video paths into per-session pairs by _<view>_ substitution.

    Multi-view (len(view_names) > 1):
      For each input, find the first ``_<view>_`` token in the stem (any
      view from ``view_names``). Resolve sibling paths for every other view
      in the same directory. Drop sessions where any view file is missing
      and record a warning.

    Single-view (len(view_names) <= 1):
      Return each input as its own one-element "pair".

    Returns: ``{"pairs": list[list[Path]], "warnings": list[str]}``.
    """
    pairs: list = []
    warnings: list = []

    if len(view_names) <= 1:
        for v in videos:
            pairs.append([Path(v)])
        return {"pairs": pairs, "warnings": warnings}

    # Multi-view: bucket inputs by session key
    sessions: dict = {}
    for v in videos:
        v = Path(v)
        stem = v.stem
        match_view = None
        for vn in view_names:
            if re.search(rf"_{re.escape(vn)}_", stem):
                match_view = vn
                break
        if match_view is None:
            pairs.append([v])
            warnings.append(f"{v.name}: no view token from {view_names} found in stem; passing through alone")
            continue
        # Session key: directory + stem with _<view>_ removed
        session_stem = re.sub(rf"_{re.escape(match_view)}_", "_<VIEW>_", stem, count=1)
        key = (v.parent, session_stem)
        sessions.setdefault(key, {})[match_view] = v

    for (parent, session_stem), got in sessions.items():
        resolved: dict = {}
        for vn in view_names:
            if vn in got:
                resolved[vn] = got[vn]
                continue
            # Build the expected sibling path
            candidate_stem = session_stem.replace("_<VIEW>_", f"_{vn}_", 1)
            # Pick up the original suffix from any known view's file
            example = next(iter(got.values()))
            candidate = parent / f"{candidate_stem}{example.suffix}"
            if candidate.is_file():
                resolved[vn] = candidate
            else:
                warnings.append(
                    f"{session_stem.replace('_<VIEW>_', '_')}: "
                    f"missing sibling for view '{vn}' (looked for {candidate.name})"
                )

        if len(resolved) == len(view_names):
            pairs.append([resolved[vn] for vn in view_names])
        # else: session dropped (warning already recorded)

    return {"pairs": pairs, "warnings": warnings}


def _transcode_to_mp4(src: "Path | str") -> tuple:
    """Remux a non-mp4 video to mp4 next to the source.

    Returns ``(out_path, did_transcode)``.

    Behaviour:
      - If src is already ``.mp4`` → returns src unchanged.
      - If ``<stem>.mp4`` already exists next to src → returns cached path; no ffmpeg.
      - Else runs ``ffmpeg -y -i src -c copy -movflags +faststart <stem>.mp4``.
      - If the stream-copy fails, falls back to ``ffmpeg -y -i src -c:v libx264 -preset veryfast -crf 18 <stem>.mp4``.
      - Raises ``FileNotFoundError`` if ffmpeg isn't on PATH.
      - Raises ``RuntimeError`` if both stream-copy and re-encode fail.
    """
    src = Path(src)
    if src.suffix.lower() == ".mp4":
        return src, False

    out = src.with_suffix(".mp4")
    if out.is_file():
        return out, False

    copy_cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c", "copy", "-movflags", "+faststart",
        str(out),
    ]
    try:
        r = subprocess.run(copy_cmd, capture_output=True, text=True)
    except FileNotFoundError:
        # ffmpeg not on PATH → re-raise with a clear message
        raise FileNotFoundError("ffmpeg required for transcoding; not found on PATH")
    if r.returncode == 0 and out.is_file():
        return out, True

    reencode_cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        str(out),
    ]
    r2 = subprocess.run(reencode_cmd, capture_output=True, text=True)
    if r2.returncode == 0 and out.is_file():
        return out, True

    raise RuntimeError(
        f"transcode failed for {src.name}: "
        f"stream-copy stderr tail: {(r.stderr or '').splitlines()[-3:]}, "
        f"re-encode stderr tail: {(r2.stderr or '').splitlines()[-3:]}"
    )


_DALI_DEFAULTS = {
    "general": {"seed": 123456},
    "base": {
        "train":   {"sequence_length": 32},
        "predict": {"sequence_length": 96},
    },
    "context": {
        "train":   {"batch_size": 16},
        "predict": {"sequence_length": 96},
    },
}


def _ensure_dali_in_config(model_dir: "Path | str") -> bool:
    """Inject a default ``dali`` block into ``<model_dir>/config.yaml`` if absent.

    Existing trained models written before LP 2.1.0 schema awareness have no
    ``dali`` section. ``litpose predict`` reads ``cfg.dali`` directly and raises
    ``ConfigAttributeError`` when the key is missing. Appending a default block
    is purely additive (training already happened) and lets predict proceed.

    Returns True if the file was modified, False if ``dali`` was already there.
    """
    import yaml as _yaml
    cfg_path = Path(model_dir) / "config.yaml"
    if not cfg_path.is_file():
        return False
    try:
        cfg = _yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return False
    if "dali" in cfg:
        return False
    cfg["dali"] = _DALI_DEFAULTS
    cfg_path.write_text(_yaml.safe_dump(cfg, sort_keys=False))
    return True


def prepare_predict_inputs(model_dir: "Path | str", videos: "list[Path | str]") -> dict:
    """Resolve sibling views + transcode non-mp4 inputs for litpose predict.

    1. Reads ``data.view_names`` from ``<model_dir>/config.yaml``.
    2. Ensures ``dali`` is present in the model config (injects defaults if not).
    3. If multi-view: groups inputs into per-session pairs by ``_<view>_``
       substitution, dropping sessions with missing siblings (each dropped
       session adds a warning).
    4. Transcodes every non-mp4 path (via stream-copy, falling back to
       libx264 re-encode), reusing cached ``<stem>.mp4`` next to sources.

    Returns::
        {
            "mp4_paths": [Path, ...],          # what to pass to litpose
            "transcoded": [str, ...],          # source paths we transcoded this call
            "sibling_warnings": [str, ...],
            "is_multiview": bool,
            "view_names": list[str],
        }
    """
    model_dir = Path(model_dir)
    _ensure_dali_in_config(model_dir)
    view_names = _load_view_names(model_dir)
    is_multiview = len(view_names) > 1

    siblings = _resolve_siblings([Path(v) for v in videos], view_names)
    mp4_paths: list = []
    transcoded: list = []

    for group in siblings["pairs"]:
        try:
            mp4_group = []
            for v in group:
                out, did = _transcode_to_mp4(v)
                if did:
                    transcoded.append(str(v))
                mp4_group.append(out)
            mp4_paths.extend(mp4_group)
        except (FileNotFoundError, RuntimeError) as e:
            siblings["warnings"].append(f"transcode failed for {[p.name for p in group]}: {e}")

    return {
        "mp4_paths": mp4_paths,
        "transcoded": transcoded,
        "sibling_warnings": siblings["warnings"],
        "is_multiview": is_multiview,
        "view_names": view_names,
    }

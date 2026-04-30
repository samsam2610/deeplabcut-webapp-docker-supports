from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from flask import Blueprint, Response, jsonify, render_template, request

import config
import viewer

bp = Blueprint(
    "dlc_3d", __name__, url_prefix="/dlc-3d",
    template_folder="templates",
    static_folder="static", static_url_path="/static",
)

# ── Server state (single-user) ───────────────────────────────────────────────

_active_project: str | None = None
_state_lock = threading.Lock()

# ── Regex helpers ─────────────────────────────────────────────────────────────

_SESSION_RE = re.compile(r'^(.+?)_cam\d+_(\d{8})')
_CAM_RE     = re.compile(r'_cam(\d+)_')
_FRAME_RE   = re.compile(r'^img_cam(\d+)_(\d{4})_(\d+)\.png$')


def _session_key_from_stem(stem: str) -> "str | None":
    """'surv1_cam0_20260123_...' → 'surv1_20260123'. None if no match."""
    m = _SESSION_RE.match(stem)
    if not m:
        return None
    return f"{m.group(1)}_{m.group(2)}"


def _cam_index_from_stem(stem: str) -> "int | None":
    """'surv1_cam0_20260123_...' → 0. None if no match."""
    m = _CAM_RE.search(stem)
    return int(m.group(1)) if m else None


# ── Video scanning ────────────────────────────────────────────────────────────

def _scan_videos(project_path: Path) -> dict:
    """
    Crawl <project>/videos/ for *_cam<N>_*.avi files.
    Returns sessions dict keyed by '{subject}_{date}'.
    All paths are relative to project_path.
    """
    videos_dir = project_path / "videos"
    sessions: dict = {}
    if not videos_dir.is_dir():
        return sessions

    for avi in sorted(videos_dir.glob("*.avi")):
        stem = avi.stem
        session_key = _session_key_from_stem(stem)
        cam_idx = _cam_index_from_stem(stem)
        if session_key is None or cam_idx is None:
            continue

        csv_path = avi.with_suffix(".csv")
        clip_dir = videos_dir / stem
        if clip_dir.is_dir():
            clips = sorted(
                str(f.relative_to(project_path))
                for f in sorted(clip_dir.glob("*.avi"))
            )
            clip_folder = str(clip_dir.relative_to(project_path)) + "/"
        else:
            clips = None
            clip_folder = None

        cam_key = f"cam{cam_idx}"
        sessions.setdefault(session_key, {})[cam_key] = {
            "avi":         str(avi.relative_to(project_path)),
            "csv":         str(csv_path.relative_to(project_path)) if csv_path.exists() else None,
            "clip_folder": clip_folder,
            "clips":       clips,
        }

    return sessions


def _load_or_scan_videos(project_path: Path) -> dict:
    """Load videos.json if present, otherwise scan and write it."""
    vj = project_path / "videos.json"
    if vj.exists():
        with open(vj) as f:
            return json.load(f)
    return _rescan_and_save(project_path)


def _rescan_and_save(project_path: Path) -> dict:
    sessions = _scan_videos(project_path)
    data = {
        "project_path": str(project_path),
        "scanned_at":   datetime.now(timezone.utc).isoformat(),
        "sessions":     sessions,
    }
    (project_path / "videos.json").write_text(json.dumps(data, indent=2))
    return data


# ── Sibling resolution ────────────────────────────────────────────────────────

def _find_sibling_video(video_rel: str, videos_json: dict) -> "str | None":
    """
    Return the sibling camera's video path (relative) for a given video.
    Handles both raw videos and clips inside clip folders.
    """
    vp = Path(video_rel)
    parent_name = vp.parent.name  # "videos" or a clip-folder stem

    is_clip = _session_key_from_stem(parent_name) is not None
    if is_clip:
        folder_stem = parent_name           # e.g. surv1_cam0_20260123_...
        clip_name   = vp.name               # e.g. clip_001.avi
        session_key = _session_key_from_stem(folder_stem)
        cam_idx     = _cam_index_from_stem(folder_stem)
    else:
        session_key = _session_key_from_stem(vp.stem)
        cam_idx     = _cam_index_from_stem(vp.stem)
        clip_name   = None

    if session_key is None or cam_idx is None:
        return None

    session = videos_json.get("sessions", {}).get(session_key, {})
    for cam_key, cam_data in sorted(session.items()):
        if cam_key == f"cam{cam_idx}":
            continue
        if is_clip:
            for clip_path in (cam_data.get("clips") or []):
                if Path(clip_path).name == clip_name:
                    return clip_path
            return None
        else:
            return cam_data.get("avi")

    return None


# ── Frame saving ──────────────────────────────────────────────────────────────

def _save_single_frame(project_path: Path, video_rel: str, frame_number: int) -> dict:
    """
    Save one frame from video_rel at frame_number into labeled-data/{session_key}/.
    Returns {"saved": filename} or {"skipped": True, "frame_number": N}.
    Also copies calibration.toml on first save into the session folder.
    """
    stem = Path(video_rel).stem
    # If video is inside a clip folder, use the clip folder's stem for session/cam
    parent_name = Path(video_rel).parent.name
    if _session_key_from_stem(parent_name) is not None:
        stem = parent_name  # resolve session/cam from the clip-folder stem

    session_key = _session_key_from_stem(stem)
    cam_idx     = _cam_index_from_stem(stem)
    if session_key is None or cam_idx is None:
        raise ValueError(f"Cannot derive session/cam from {video_rel!r}")

    labeled_dir = project_path / "labeled-data" / session_key
    labeled_dir.mkdir(parents=True, exist_ok=True)

    # Duplicate check
    existing = sorted(labeled_dir.glob(f"img_cam{cam_idx}_*.png"))
    for f in existing:
        m = _FRAME_RE.match(f.name)
        if m and int(m.group(3)) == frame_number:
            return {"skipped": True, "frame_number": frame_number}

    # Read frame from video → PNG
    video_path = (project_path / video_rel).resolve()
    if not video_path.is_relative_to(project_path.resolve()):
        raise ValueError(f"video_rel escapes project root: {video_rel!r}")
    frame_jpeg = viewer.get_frame_jpeg(str(video_path), frame_number)
    nparr = np.frombuffer(frame_jpeg, np.uint8)
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Could not decode frame {frame_number} from {video_rel}")
    ok, png_buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encoding failed")

    order = len(existing)
    fname = f"img_cam{cam_idx}_{order:04d}_{frame_number:05d}.png"
    (labeled_dir / fname).write_bytes(png_buf.tobytes())

    # Copy calibration.toml on first save (no existing PNGs before this one)
    if order == 0:
        calib_src  = project_path / "videos" / "calibration.toml"
        calib_dest = labeled_dir / "calibration.toml"
        if calib_src.exists() and not calib_dest.exists():
            shutil.copy2(calib_src, calib_dest)

    return {"saved": fname, "order": order + 1}

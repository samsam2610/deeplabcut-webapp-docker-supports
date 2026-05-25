from __future__ import annotations

import csv
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
    template_folder="../templates",
    static_folder="../static", static_url_path="/static",
)

# ── Server state (single-user) ───────────────────────────────────────────────

_active_project: str | None = None
_state_lock = threading.Lock()

# ── Regex helpers ─────────────────────────────────────────────────────────────

_SESSION_RE = re.compile(r'^(.+?)_cam\d+_(\d{8})')
_CAM_RE     = re.compile(r'_cam(\d+)_')
_FRAME_RE   = re.compile(r'^img_cam(\d+)_(\d{4})_(\d+)\.png$')

# ── Path security ─────────────────────────────────────────────────────────────

_USER_DATA_ROOT = "/user-data"


def _resolve_video_path(video_path: str, proj: str) -> "Path | None":
    """Return resolved absolute Path for video_path, or None if disallowed.

    Absolute paths must be within /user-data/.
    Relative paths must stay within the project directory.
    """
    if video_path.startswith("/"):
        p = Path(video_path).resolve()
        if not str(p).startswith(_USER_DATA_ROOT + "/"):
            return None
        return p
    p = (Path(proj) / video_path).resolve()
    if not p.is_relative_to(Path(proj).resolve()):
        return None
    return p


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


def _find_sibling_on_filesystem(video_abs: str) -> "str | None":
    """Find sibling camera video by scanning same directory on filesystem.

    Works for any absolute path, not limited to the DLC project directory.
    """
    vp = Path(video_abs)
    if not vp.is_absolute():
        return None
    m = re.match(r'^(.+?)_cam(\d+)_(\d{8})', vp.stem)
    if not m:
        return None
    prefix, date = m.group(1), m.group(3)
    cam_idx = int(m.group(2))
    for f in vp.parent.iterdir():
        if f == vp or f.suffix.lower() not in (".avi", ".mp4"):
            continue
        m2 = re.match(r'^(.+?)_cam(\d+)_(\d{8})', f.stem)
        if m2 and m2.group(1) == prefix and m2.group(3) == date and int(m2.group(2)) != cam_idx:
            return str(f)
    return None


# ── Sibling h5 resolver (for analyzed-viewer layer pairing) ──────────────────

def _resolve_sibling_h5(primary_h5: str, target_cam: int) -> dict:
    r"""Substitute `_cam{N}_` in the basename of primary_h5 to point at target_cam.

    Returns {"path": <str>, "exists": bool} or {"path": None, "exists": False}
    when the input has no `_cam\d+_` token.
    """
    p = Path(primary_h5)
    m = _CAM_RE.search(p.name)
    if not m:
        return {"path": None, "exists": False}
    sibling_name = _CAM_RE.sub(f"_cam{int(target_cam)}_", p.name, count=1)
    sibling = p.with_name(sibling_name)
    return {"path": str(sibling), "exists": sibling.is_file()}


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
    video_path = _resolve_video_path(video_rel, str(project_path))
    if video_path is None:
        raise ValueError(f"video path not allowed: {video_rel!r}")
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

    # Copy calibration.toml if missing at destination. Source priority:
    #   1. video's own parent folder
    #   2. grandparent folder when video is inside a clip subfolder
    # Runs on every save (not just the first) so it self-heals when
    # a session folder was populated by an earlier buggy run that didn't
    # copy calibration.toml — destination check prevents redundant work.
    calib_dest = labeled_dir / "calibration.toml"
    calibration_copied = False
    if not calib_dest.exists():
        calib_candidates = [video_path.parent / "calibration.toml"]
        if _session_key_from_stem(video_path.parent.name) is not None:
            calib_candidates.append(video_path.parent.parent / "calibration.toml")
        for calib_src in calib_candidates:
            if calib_src.exists():
                shutil.copy2(calib_src, calib_dest)
                calibration_copied = True
                break

    return {"saved": fname, "order": order + 1, "calibration_copied": calibration_copied}


# ── UI ────────────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return render_template("dlc_3d.html")


# ── Filesystem browser ────────────────────────────────────────────────────────

@bp.route("/browse")
def browse():
    path_str = request.args.get("path", "").strip()
    if path_str:
        p = Path(path_str).resolve()
        if not str(p).startswith(_USER_DATA_ROOT + "/") and str(p) != _USER_DATA_ROOT:
            return jsonify({"error": "path not allowed"}), 403
    else:
        p = next((r for r in config.USER_DATA_ROOTS if r.is_dir()), Path("/"))

    if not p.is_dir():
        return jsonify({"error": "not a directory"}), 400

    entries = []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: e.name.lower()):
            if entry.name.startswith(".") or entry.name.startswith("@"):
                continue
            if entry.is_dir():
                has_config = (entry / "config.yaml").exists()
                entries.append({"name": entry.name, "type": "dir", "has_config": has_config})
            elif entry.name == "config.yaml":
                entries.append({"name": entry.name, "type": "yaml", "has_config": True})
            elif entry.is_file() and entry.suffix.lower() in (".avi", ".mp4"):
                entries.append({"name": entry.name, "type": "file"})
    except PermissionError:
        return jsonify({"error": "permission denied"}), 403

    parent = str(p.parent) if str(p.parent) != str(p) else None
    return jsonify({"path": str(p), "parent": parent, "entries": entries})


# ── Project ───────────────────────────────────────────────────────────────────

@bp.route("/project", methods=["POST"])
def set_project():
    """Set active project by config.yaml path or project directory path."""
    global _active_project
    body = request.get_json(force=True) or {}
    path_str = (body.get("path") or "").strip()
    if not path_str:
        return jsonify({"error": "path required"}), 400

    p = Path(path_str)
    if p.name == "config.yaml":
        p = p.parent
    if not (p / "config.yaml").exists():
        return jsonify({"error": "config.yaml not found at that path"}), 404

    with _state_lock:
        _active_project = str(p)

    data = _load_or_scan_videos(p)
    return jsonify({"project_path": str(p), "sessions": data.get("sessions", {})})


@bp.route("/project/rescan", methods=["POST"])
def rescan_project():
    with _state_lock:
        proj = _active_project
    if not proj:
        return jsonify({"error": "no active project"}), 400
    data = _rescan_and_save(Path(proj))
    return jsonify({"sessions": data.get("sessions", {})})


@bp.route("/project/sessions")
def get_sessions():
    with _state_lock:
        proj = _active_project
    if not proj:
        return jsonify({"sessions": {}})
    data = _load_or_scan_videos(Path(proj))
    return jsonify({"sessions": data.get("sessions", {})})


# ── Video / frame serving ─────────────────────────────────────────────────────

@bp.route("/frame")
def get_frame():
    with _state_lock:
        proj = _active_project
    video_path = request.args.get("video", "").strip()
    n_str      = request.args.get("n", "").strip()
    if not video_path or not n_str or not proj:
        return jsonify({"error": "video, n, and active project required"}), 400
    try:
        n = int(n_str)
    except ValueError:
        return jsonify({"error": "n must be an integer"}), 400

    etag = f'"dlc3d-{video_path}-{n}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304)

    full_path = _resolve_video_path(video_path, proj)
    if full_path is None:
        return jsonify({"error": "video path not allowed"}), 400
    try:
        data = viewer.get_frame_jpeg(str(full_path), n)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except (ValueError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 400

    resp = Response(data, mimetype="image/jpeg")
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@bp.route("/video-info")
def get_video_info():
    with _state_lock:
        proj = _active_project
    video_path = request.args.get("video", "").strip()
    if not video_path or not proj:
        return jsonify({"error": "video and active project required"}), 400
    full_path = _resolve_video_path(video_path, proj)
    if full_path is None:
        return jsonify({"error": "video path not allowed"}), 400
    try:
        info = viewer.get_video_info(str(full_path))
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(info)


@bp.route("/sibling-camera")
def get_sibling_camera():
    with _state_lock:
        proj = _active_project
    video_path = request.args.get("video", "").strip()
    if not video_path:
        return jsonify({"sibling_video_path": None, "calibration_exists": False})

    # ── Sibling lookup ──
    sibling = _find_sibling_on_filesystem(video_path)
    if not (sibling and str(Path(sibling).resolve()).startswith(_USER_DATA_ROOT + "/")):
        sibling = None
        if proj and not video_path.startswith("/"):
            vj_path = Path(proj) / "videos.json"
            if vj_path.exists():
                with open(vj_path) as f:
                    videos_json = json.load(f)
                sibling = _find_sibling_video(video_path, videos_json)

    # ── Calibration check (same priority as _save_single_frame) ──
    resolved = _resolve_video_path(video_path, proj or _USER_DATA_ROOT)
    calibration_exists = False
    if resolved is not None:
        candidates = [resolved.parent / "calibration.toml"]
        if _session_key_from_stem(resolved.parent.name) is not None:
            candidates.append(resolved.parent.parent / "calibration.toml")
        calibration_exists = any(p.is_file() for p in candidates)

    return jsonify({
        "sibling_video_path": sibling,
        "calibration_exists": calibration_exists,
    })


@bp.route("/analyzed/sibling-h5")
def analyzed_sibling_h5():
    primary = (request.args.get("primary_h5") or "").strip()
    cam = request.args.get("cam", type=int)
    if not primary or cam is None:
        return jsonify({"error": "primary_h5 and cam required"}), 400
    # Path security: must resolve under /user-data/
    resolved = Path(primary).resolve()
    if not str(resolved).startswith(_USER_DATA_ROOT + "/"):
        return jsonify({"error": "path outside /user-data"}), 403
    return jsonify(_resolve_sibling_h5(str(resolved), cam))


# ── Frame extraction ──────────────────────────────────────────────────────────

@bp.route("/save-frame", methods=["POST"])
def save_frame():
    with _state_lock:
        proj = _active_project
    if not proj:
        return jsonify({"error": "no active project"}), 400

    body             = request.get_json(force=True) or {}
    primary_video    = (body.get("primary_video")    or "").strip()
    primary_frame    = body.get("primary_frame_number")
    extract_sibling  = bool(body.get("extract_sibling", False))
    sibling_video    = (body.get("sibling_video")    or "").strip()
    sibling_frame    = body.get("sibling_frame_number")

    if not primary_video or primary_frame is None:
        return jsonify({"error": "primary_video and primary_frame_number required"}), 400

    project_path = Path(proj)
    saved = []
    skipped = []
    calibration_copied = False

    try:
        r = _save_single_frame(project_path, primary_video, int(primary_frame))
        if r.get("skipped"):
            skipped.append(r)
        else:
            saved.append(r["saved"])
        if r.get("calibration_copied"):
            calibration_copied = True
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return jsonify({"error": str(e)}), 400

    if extract_sibling and sibling_video and sibling_frame is not None:
        try:
            r2 = _save_single_frame(project_path, sibling_video, int(sibling_frame))
            if r2.get("skipped"):
                skipped.append(r2)
            else:
                saved.append(r2["saved"])
            if r2.get("calibration_copied"):
                calibration_copied = True
        except (ValueError, RuntimeError, FileNotFoundError) as e:
            return jsonify({"error": f"sibling save failed: {e}"}), 400

    stem = Path(primary_video).stem
    parent_name = Path(primary_video).parent.name
    if _session_key_from_stem(parent_name) is not None:
        stem = parent_name
    session_key = _session_key_from_stem(stem) or stem

    return jsonify({
        "saved":              saved,
        "skipped":            skipped,
        "calibration_copied": calibration_copied,
        "session_folder":     f"labeled-data/{session_key}",
    }), 201 if saved else 200


# ── Labeled frames ────────────────────────────────────────────────────────────

@bp.route("/labeled-frames")
def labeled_frames():
    with _state_lock:
        proj = _active_project
    session_key = request.args.get("session", "").strip()
    if not session_key or not proj:
        return jsonify({"frames": [], "count": 0, "session_folder": None})

    labeled_dir = Path(proj) / "labeled-data" / session_key
    if not labeled_dir.is_dir():
        return jsonify({"frames": [], "count": 0, "session_folder": f"labeled-data/{session_key}"})

    frames = sorted(f.name for f in labeled_dir.glob("img_cam*.png"))
    return jsonify({
        "frames":         frames,
        "count":          len(frames),
        "session_folder": f"labeled-data/{session_key}",
    })


@bp.route("/csv")
def csv_route():
    """Return CSV annotation rows for the same-stem .csv next to the given video.

    Format: {"rows": [...], "csv_path": str, "csv_exists": bool}
    Each row: {timestamp, frame_number, frame_line_status, note}.
    Skips rows where status is empty/"0" AND note is empty.
    """
    video_path = request.args.get("video", "").strip()
    if not video_path:
        return jsonify({"error": "video required"}), 400

    with _state_lock:
        proj = _active_project
    resolved = _resolve_video_path(video_path, proj or _USER_DATA_ROOT)
    if resolved is None:
        return jsonify({"error": "invalid path"}), 400

    csv_path = resolved.with_suffix(".csv")
    if not csv_path.is_file():
        return jsonify({"rows": [], "csv_path": str(csv_path), "csv_exists": False})

    rows = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, skipinitialspace=True)
            if reader.fieldnames:
                reader.fieldnames = [n.strip() for n in reader.fieldnames]
            for row in reader:
                row = {k.strip() if k else k: v for k, v in row.items()}
                status = (row.get("frame_line_status") or "").strip()
                note   = (row.get("note") or "").strip()
                if not note and (not status or status == "0"):
                    continue
                try:
                    fn = int(float(row.get("frame_number", 0)))
                except (ValueError, TypeError):
                    fn = 0
                rows.append({
                    "timestamp":         (row.get("timestamp") or "").strip(),
                    "frame_number":      fn,
                    "frame_line_status": status,
                    "note":              note,
                })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    rows.sort(key=lambda r: r["frame_number"])
    return jsonify({"rows": rows, "csv_path": str(csv_path), "csv_exists": True})


# ── Clip extraction ───────────────────────────────────────────────────────────

def _clip_output_path(video_path: Path, start_frame: int, n_frames: int, postfix: str) -> Path:
    stem = video_path.stem
    end_frame = start_frame + n_frames
    name = f"{stem}_{start_frame}_{end_frame}"
    safe = "".join(c for c in (postfix or "") if c.isalnum() or c in "-_")[:64]
    if safe:
        name += f"_{safe}"
    return video_path.parent / stem / f"{name}.avi"


def _trim_frames_cv2(src: Path, out: Path, start_frame: int, n_frames: int) -> int:
    """Frame-exact trim [start_frame, start_frame+n_frames) → out. Returns frames written."""
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise ValueError(f"cannot open {src}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    start_frame = max(0, start_frame)
    n_frames = max(0, min(n_frames, max(total - start_frame, 0)))
    out.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    written = 0
    for _ in range(n_frames):
        ok, frame = cap.read()
        if not ok:
            break
        vw.write(frame)
        written += 1
    vw.release()
    cap.release()
    return written


@bp.route("/extract-clip", methods=["POST"])
def extract_clip():
    body = request.get_json(force=True, silent=True) or {}
    proj = body.get("project") or request.args.get("project") or ""
    video_path = (body.get("video_path") or "").strip()
    start_frame = body.get("start_frame")
    n_frames = body.get("n_frames")
    if not video_path or start_frame is None or n_frames is None:
        return jsonify({"error": "video_path, start_frame, n_frames required"}), 400
    src = _resolve_video_path(video_path, proj) or Path(video_path)
    if not src.exists():
        return jsonify({"error": f"video not found: {src.name}"}), 404
    postfix = (body.get("postfix") or "").strip()
    try:
        out = _clip_output_path(src, int(start_frame), int(n_frames), postfix)
        written = _trim_frames_cv2(src, out, int(start_frame), int(n_frames))
        result = {"avi_path": str(out), "n_frames": written}
        sib = (body.get("sibling_video") or "").strip()
        if sib:
            sib_src = _resolve_video_path(sib, proj) or Path(sib)
            if sib_src.exists():
                sib_out = _clip_output_path(sib_src, int(start_frame), int(n_frames), postfix)
                _trim_frames_cv2(sib_src, sib_out, int(start_frame), int(n_frames))
                result["sibling_avi_path"] = str(sib_out)
        return jsonify(result)
    except Exception as e:  # noqa: BLE001 — surface trim failures to the UI
        return jsonify({"error": str(e)}), 500


@bp.route("/extract-clip/rename", methods=["POST"])
def extract_clip_rename():
    body = request.get_json(force=True, silent=True) or {}
    avi_path = (body.get("avi_path") or "").strip()
    postfix = (body.get("postfix") or "").strip()
    if not avi_path:
        return jsonify({"error": "avi_path required"}), 400
    p = Path(avi_path)
    if not p.exists():
        return jsonify({"error": f"file not found: {p.name}"}), 404
    video_stem = p.parent.name
    m = re.match(r"^_(\d+)_(\d+)", p.stem[len(video_stem):])
    if not m:
        return jsonify({"error": "cannot parse frame numbers from filename"}), 422
    new_stem = f"{video_stem}_{m.group(1)}_{m.group(2)}"
    safe = "".join(c for c in postfix if c.isalnum() or c in "-_")[:64]
    if safe:
        new_stem += f"_{safe}"
    new_avi = p.parent / f"{new_stem}.avi"
    if new_avi != p:
        p.rename(new_avi)
    return jsonify({"avi_path": str(new_avi)})


@bp.route("/extract-clip/delete", methods=["POST"])
def extract_clip_delete():
    body = request.get_json(force=True, silent=True) or {}
    avi_path = (body.get("avi_path") or "").strip()
    if not avi_path:
        return jsonify({"error": "avi_path required"}), 400
    p = Path(avi_path)
    if not p.exists():
        return jsonify({"error": f"file not found: {p.name}"}), 404
    p.unlink()
    return jsonify({"ok": True})

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

import pandas as pd
from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context

import config
import processor

bp = Blueprint(
    "clip_cutter", __name__, url_prefix="/clip-cutter",
    template_folder="templates",
    static_folder="static", static_url_path="/static",
)

_scan_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

_state: dict = {"frames": [], "mean_embedding": None}
_state_lock = threading.Lock()


def load_state() -> None:
    global _state
    new_state = processor.load_template_state(config.TEMPLATE_STATE_PATH)
    with _state_lock:
        _state = new_state


# ── UI ──────────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return render_template("clip_cutter.html")


# ── Template bank ─────────────────────────────────────────────────────────────

@bp.route("/template")
def get_template():
    with _state_lock:
        frames_out = [
            {"thumbnail": f["thumbnail"], "video_path": f["video_path"],
             "frame_number": f["frame_number"]}
            for f in _state["frames"]
        ]
        count = len(frames_out)
    return jsonify({"count": count, "frames": frames_out})


@bp.route("/template/add", methods=["POST"])
def add_to_template():
    global _state
    body = request.get_json(force=True)
    video_path = body.get("video_path")
    frame_number = body.get("frame_number")
    if not video_path or frame_number is None:
        return jsonify({"error": "video_path and frame_number required"}), 400
    with _state_lock:
        try:
            _state = processor.add_frame_to_template(
                _state, video_path, int(frame_number),
                config.TEMPLATE_STATE_PATH, crop=None
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 422
        count = len(_state["frames"])
    return jsonify({"count": count})


@bp.route("/template/<int:idx>", methods=["DELETE"])
def remove_from_template(idx: int):
    global _state
    with _state_lock:
        if idx >= len(_state["frames"]):
            return jsonify({"error": "index out of range"}), 404
        _state = processor.remove_frame_from_template(_state, idx, config.TEMPLATE_STATE_PATH)
        count = len(_state["frames"])
    return jsonify({"count": count})


_init_status: dict = {"running": False, "error": None}
_init_lock = threading.Lock()


def _run_init():
    global _state
    with _init_lock:
        _init_status["running"] = True
        _init_status["error"] = None
    try:
        config.TEMPLATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        new_state = processor.init_template_from_clips_dir(
            config.TRAINING_CLIPS_DIR, config.TEMPLATE_STATE_PATH, crop=config.TRAINING_CROP
        )
        with _state_lock:
            _state = new_state
    except Exception as exc:
        with _init_lock:
            _init_status["error"] = str(exc)
    finally:
        with _init_lock:
            _init_status["running"] = False


@bp.route("/template/init", methods=["POST"])
def init_template():
    with _init_lock:
        if _init_status["running"]:
            return jsonify({"status": "running"}), 202
    thread = threading.Thread(target=_run_init, daemon=True)
    thread.start()
    return jsonify({"status": "started"}), 202


@bp.route("/template/init/status")
def init_template_status():
    with _state_lock:
        count = len(_state["frames"])
    with _init_lock:
        running = _init_status["running"]
        error = _init_status["error"]
    return jsonify({"running": running, "count": count, "error": error})


# ── Video list ─────────────────────────────────────────────────────────────────

def _video_is_done(avi_path: Path) -> bool:
    test_clips_dir = avi_path.parent / (avi_path.stem + config.TEST_CLIPS_SUFFIX)
    if test_clips_dir.exists():
        return True
    csv_path = avi_path.with_suffix(".csv")
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path, usecols=["note"], on_bad_lines="skip")
            return bool(df["note"].eq("start_reaching").any())
        except Exception:
            return False
    return False


@bp.route("/videos")
def list_videos():
    videos = []
    for p in sorted(config.VIDEO_DIR.glob("*.avi")):
        videos.append({
            "name": p.name,
            "path": str(p),
            "done": _video_is_done(p),
        })
    return jsonify({"videos": videos})


# ── Scan ─────────────────────────────────────────────────────────────────────

def _run_scan(job_id: str, video_path: str, template_emb):
    def progress_cb(current, total):
        with _jobs_lock:
            _scan_jobs[job_id]["current"] = current
            _scan_jobs[job_id]["total"] = total

    def phase_cb(phase, current, total):
        with _jobs_lock:
            _scan_jobs[job_id]["phase"] = phase
            _scan_jobs[job_id]["current"] = current
            _scan_jobs[job_id]["total"] = total

    try:
        detections = processor.scan_video(
            video_path,
            template_emb,
            stride=config.SCAN_STRIDE,
            threshold=config.SIMILARITY_THRESHOLD,
            min_spacing=config.MIN_PEAK_SPACING,
            fine_window=config.FINE_SCAN_WINDOW,
            batch_size=config.SCAN_BATCH_SIZE,
            progress_cb=progress_cb,
            phase_cb=phase_cb,
        )
        known = processor.get_known_key_frames(config.TRAINING_CLIPS_DIR)
        for d in detections:
            kf = d["frame_number"]
            match = next(
                (name for kf_known, name in known.items() if abs(kf - kf_known) <= 5),
                None,
            )
            d["known_match"] = match

        with _jobs_lock:
            _scan_jobs[job_id]["status"] = "done"
            _scan_jobs[job_id]["detections"] = detections
    except Exception as exc:
        with _jobs_lock:
            _scan_jobs[job_id]["status"] = "error"
            _scan_jobs[job_id]["error"] = str(exc)


@bp.route("/scan", methods=["POST"])
def start_scan():
    body = request.get_json(force=True)
    video_path = body.get("video_path")
    if not video_path:
        return jsonify({"error": "video_path required"}), 400
    with _state_lock:
        mean_embedding = _state["mean_embedding"]
    if mean_embedding is None:
        return jsonify({"error": "template is empty — run /template/init first"}), 422

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _scan_jobs[job_id] = {
            "status": "running", "phase": "starting",
            "current": 0, "total": 1, "detections": [], "error": None,
        }

    template_emb = mean_embedding.copy()
    thread = threading.Thread(
        target=_run_scan, args=(job_id, video_path, template_emb), daemon=True
    )
    thread.start()
    return jsonify({"job_id": job_id})


@bp.route("/scan/stream")
def scan_stream():
    job_id = request.args.get("job_id")
    if not job_id or job_id not in _scan_jobs:
        return jsonify({"error": "unknown job_id"}), 404

    def generate():
        while True:
            with _jobs_lock:
                job = dict(_scan_jobs[job_id])
            yield f"data: {json.dumps(job)}\n\n"
            if job["status"] in ("done", "error"):
                break
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Extract confirmed detection ───────────────────────────────────────────────

@bp.route("/extract", methods=["POST"])
def extract():
    body = request.get_json(force=True)
    video_path = body.get("video_path")
    key_frame = body.get("key_frame")
    if not video_path or key_frame is None:
        return jsonify({"error": "video_path and key_frame required"}), 400

    video_path = Path(video_path)
    parent_csv = video_path.with_suffix(".csv")
    output_dir = video_path.parent / (video_path.stem + config.TEST_CLIPS_SUFFIX)

    if not parent_csv.exists():
        return jsonify({"error": f"parent CSV not found: {parent_csv}"}), 422

    result = processor.extract_clip(video_path, parent_csv, int(key_frame), output_dir)
    processor.update_parent_csv_note(parent_csv, int(key_frame), "start_reaching")
    return jsonify(result)

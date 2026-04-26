from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

import pandas as pd
from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context

import config
import processor
import viewer

bp = Blueprint(
    "clip_cutter", __name__, url_prefix="/clip-cutter",
    template_folder="templates",
    static_folder="static", static_url_path="/static",
)

_scan_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

_state: dict = {"frames": [], "mean_embedding": None, "dino_mean_embedding": None}
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

def _run_scan(job_id: str, video_path: str, template_emb, dino_template_emb, params: dict):
    stride        = params.get("stride", config.SCAN_STRIDE)
    threshold     = params.get("threshold", config.SIMILARITY_THRESHOLD)
    min_spacing   = params.get("min_spacing", config.MIN_PEAK_SPACING)
    fine_window   = params.get("fine_window", config.FINE_SCAN_WINDOW)
    trigger_value = params.get("trigger_value", config.SENSOR_TRIGGER_VALUE)
    sensor_margin = params.get("sensor_margin", config.SENSOR_MARGIN)

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
        csv_path = Path(video_path).with_suffix(".csv")
        if csv_path.exists():
            detections = processor.scan_video_sensor_guided(
                video_path, csv_path, template_emb,
                trigger_value=trigger_value,
                sensor_margin=sensor_margin,
                stride=stride,
                threshold=threshold,
                min_spacing=min_spacing,
                fine_window=fine_window,
                batch_size=config.SCAN_BATCH_SIZE,
                progress_cb=progress_cb,
                phase_cb=phase_cb,
                dino_template_emb=dino_template_emb,
            )
        else:
            detections = processor.scan_video(
                video_path, template_emb,
                stride=stride,
                threshold=threshold,
                min_spacing=min_spacing,
                fine_window=fine_window,
                batch_size=config.SCAN_BATCH_SIZE,
                progress_cb=progress_cb,
                phase_cb=phase_cb,
                dino_template_emb=dino_template_emb,
            )

        known = processor.get_known_key_frames(config.TRAINING_CLIPS_DIR)
        for d in detections:
            kf = d["frame_number"]
            match = next(
                (name for kf_known, name in known.items() if abs(kf - kf_known) <= 5),
                None,
            )
            d["known_match"] = match
            d["status"] = "pending"

        with _state_lock:
            template_frame_count = len(_state["frames"])
        processor.save_detections(
            video_path, detections, template_frame_count, config.DETECTIONS_DIR
        )

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
        dino_mean_embedding = _state.get("dino_mean_embedding")
    if mean_embedding is None:
        return jsonify({"error": "template is empty — run /template/init first"}), 422
    if dino_mean_embedding is None:
        logging.getLogger(__name__).warning(
            "dino_mean_embedding is None — fine scan will use CLIP fallback. "
            "Re-run /template/init to enable DINOv2 fine scan."
        )

    # Fix 1: Guard params against non-dict JSON values
    raw_params = body.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}

    # Fix 2: Validate numeric param types before spawning thread
    _int_params = ("stride", "min_spacing", "fine_window", "trigger_value", "sensor_margin")
    for key in _int_params:
        if key in params and not isinstance(params[key], int):
            return jsonify({"error": f"params.{key} must be an integer"}), 400
    if "threshold" in params and not isinstance(params["threshold"], (int, float)):
        return jsonify({"error": "params.threshold must be a number"}), 400

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _scan_jobs[job_id] = {
            "status": "running", "phase": "starting",
            "current": 0, "total": 1, "detections": [], "error": None,
        }

    template_emb = mean_embedding.copy()
    dino_emb_copy = dino_mean_embedding.copy() if dino_mean_embedding is not None else None
    thread = threading.Thread(
        target=_run_scan,
        args=(job_id, video_path, template_emb, dino_emb_copy, params),
        daemon=True,
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


# ── Detection persistence ──────────────────────────────────────────────────────

@bp.route("/detections")
def get_detections():
    video_path = request.args.get("video", "").strip()
    if not video_path:
        return jsonify({"error": "video required"}), 400
    data = processor.load_detections(video_path, config.DETECTIONS_DIR)
    if data is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)


@bp.route("/detections", methods=["PUT"])
def put_detections():
    body = request.get_json(force=True, silent=True) or {}
    video_path = body.get("video_path")
    detections = body.get("detections")
    if not video_path or detections is None:
        return jsonify({"error": "video_path and detections required"}), 400
    with _state_lock:
        template_frame_count = len(_state["frames"])
    processor.save_detections(
        video_path, detections, template_frame_count, config.DETECTIONS_DIR
    )
    return jsonify({"ok": True})


# ── Frame serving ──────────────────────────────────────────────────────────────

@bp.route("/frame")
def get_frame():
    video_path = request.args.get("video", "").strip()
    n = request.args.get("n", "").strip()
    if not video_path or not n:
        return jsonify({"error": "video and n required"}), 400
    try:
        n = int(n)
    except ValueError:
        return jsonify({"error": "n must be an integer"}), 400

    etag = f'"cc-frame-{video_path}-{n}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304)

    try:
        data = viewer.get_frame_jpeg(video_path, n)
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
    video_path = request.args.get("video", "").strip()
    if not video_path:
        return jsonify({"error": "video required"}), 400
    try:
        info = viewer.get_video_info(video_path)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(info)

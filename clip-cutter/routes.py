from __future__ import annotations

import csv
import json
import logging
import threading
import time
import uuid
from pathlib import Path

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

_state: dict = {
    "frames": [],
    "mean_embedding": None,
    "dino_mean_embedding": None,
    "video_stem": None,
    "video_parent": None,
}
_state_lock = threading.Lock()

_libraries_lock = threading.Lock()


def _load_libraries() -> dict:
    """Load libraries.json; return {} if absent or malformed."""
    p = config.LIBRARIES_PATH
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_libraries(libs: dict) -> None:
    """Persist libs to LIBRARIES_PATH. Caller must hold _libraries_lock."""
    config.LIBRARIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.LIBRARIES_PATH, "w") as f:
        json.dump(libs, f, indent=2)


def _template_path() -> "Path | None":
    with _state_lock:
        stem = _state.get("video_stem")
        parent = _state.get("video_parent")
    if not stem or not parent:
        return None
    return Path(parent) / stem / "template" / "template_state.json"


def load_state() -> None:
    pass  # template state now loaded per-video via /select-video


# ── UI ──────────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return render_template("clip_cutter.html")


# ── Template bank ─────────────────────────────────────────────────────────────

@bp.route("/template")
def get_template():
    tpath = _template_path()
    with _state_lock:
        frames_out = [
            {"thumbnail": f["thumbnail"], "video_path": f["video_path"],
             "frame_number": f["frame_number"]}
            for f in _state["frames"]
        ]
        count = len(frames_out)
    has_template = tpath is not None and tpath.exists()
    return jsonify({"count": count, "frames": frames_out, "has_template": has_template})


@bp.route("/template/add", methods=["POST"])
def add_to_template():
    global _state
    tpath = _template_path()
    if tpath is None:
        return jsonify({"error": "no video selected"}), 422
    body = request.get_json(force=True)
    video_path = body.get("video_path")
    frame_number = body.get("frame_number")
    if not video_path or frame_number is None:
        return jsonify({"error": "video_path and frame_number required"}), 400
    tpath.parent.mkdir(parents=True, exist_ok=True)
    with _state_lock:
        try:
            _state = processor.add_frame_to_template(
                _state, video_path, int(frame_number), tpath, crop=None
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 422
        count = len(_state["frames"])
    return jsonify({"count": count})


@bp.route("/template/<int:idx>", methods=["DELETE"])
def remove_from_template(idx: int):
    global _state
    tpath = _template_path()
    if tpath is None:
        return jsonify({"error": "no video selected"}), 422
    with _state_lock:
        if idx >= len(_state["frames"]):
            return jsonify({"error": "index out of range"}), 404
        _state = processor.remove_frame_from_template(_state, idx, tpath)
        count = len(_state["frames"])
    return jsonify({"count": count})


@bp.route("/template/clear", methods=["POST"])
def clear_template():
    global _state
    tpath = _template_path()
    if tpath is None:
        return jsonify({"error": "no video selected"}), 422
    template_dir = tpath.parent
    if tpath.exists():
        tpath.unlink()
    if template_dir.exists():
        for jpg in template_dir.glob("*.jpg"):
            jpg.unlink()
    with _state_lock:
        _state["frames"] = []
        _state["mean_embedding"] = None
        _state["dino_mean_embedding"] = None
    return jsonify({"ok": True})


# ── Global template library ───────────────────────────────────────────────────

@bp.route("/global-libraries", methods=["GET"])
def get_libraries():
    with _libraries_lock:
        libs = _load_libraries()
    return jsonify({"libraries": libs})


@bp.route("/global-libraries", methods=["POST"])
def create_library():
    name = (request.get_json(force=True) or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 422
    with _libraries_lock:
        libs = _load_libraries()
        if name in libs:
            return jsonify({"error": "library already exists"}), 422
        libs[name] = []
        _save_libraries(libs)
    return jsonify({"ok": True})


@bp.route("/global-libraries/<name>", methods=["DELETE"])
def delete_library(name):
    with _libraries_lock:
        libs = _load_libraries()
        if name not in libs:
            return jsonify({"error": "not found"}), 404
        del libs[name]
        _save_libraries(libs)
    return jsonify({"ok": True})


@bp.route("/global-libraries/<name>/folders", methods=["POST"])
def add_library_folder(name):
    path = (request.get_json(force=True) or {}).get("path", "").strip()
    if not path:
        return jsonify({"error": "path required"}), 422
    with _libraries_lock:
        libs = _load_libraries()
        if name not in libs:
            return jsonify({"error": "library not found"}), 404
        if path in libs[name]:
            return jsonify({"error": "path already in library"}), 422
        libs[name].append(path)
        _save_libraries(libs)
    return jsonify({"ok": True, "count": len(libs[name])})


@bp.route("/global-libraries/<name>/folders", methods=["DELETE"])
def remove_library_folder(name):
    path = (request.get_json(force=True) or {}).get("path", "").strip()
    if not path:
        return jsonify({"error": "path required"}), 422
    with _libraries_lock:
        libs = _load_libraries()
        if name not in libs:
            return jsonify({"error": "library not found"}), 404
        if path not in libs[name]:
            return jsonify({"error": "path not in library"}), 404
        libs[name].remove(path)
        _save_libraries(libs)
    return jsonify({"ok": True, "count": len(libs[name])})


_init_status: dict = {"running": False, "error": None}
_init_lock = threading.Lock()

_batch_init_jobs: dict[str, dict] = {}
_batch_init_jobs_lock = threading.Lock()

_batch_scan_jobs: dict[str, dict] = {}
_batch_scan_jobs_lock = threading.Lock()

_batch_template_scan_jobs: dict[str, dict] = {}
_batch_template_scan_jobs_lock = threading.Lock()


def _run_init(video_stem: str, video_parent: str):
    global _state
    with _init_lock:
        _init_status["running"] = True
        _init_status["error"] = None
    try:
        clips_dir = Path(video_parent) / video_stem
        template_dir = clips_dir / "template"
        template_dir.mkdir(parents=True, exist_ok=True)
        state_path = template_dir / "template_state.json"
        new_state = processor.init_template_from_clips_dir(
            clips_dir, state_path, crop=config.TRAINING_CROP
        )
        new_state["video_stem"] = video_stem
        new_state["video_parent"] = video_parent
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
    with _state_lock:
        stem = _state.get("video_stem")
        parent = _state.get("video_parent")
    if not stem or not parent:
        return jsonify({"error": "no video selected"}), 422
    with _init_lock:
        if _init_status["running"]:
            return jsonify({"status": "running"}), 202
    thread = threading.Thread(target=_run_init, args=(stem, parent), daemon=True)
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


def _run_batch_init(job_id: str, video_paths: list[str]):
    total = len(video_paths)
    failed = []
    for i, video_path in enumerate(video_paths):
        p = Path(video_path)
        clips_dir = p.parent / p.stem
        template_dir = clips_dir / "template"
        template_dir.mkdir(parents=True, exist_ok=True)
        state_path = template_dir / "template_state.json"
        with _batch_init_jobs_lock:
            _batch_init_jobs[job_id]["current"] = i + 1
            _batch_init_jobs[job_id]["video"] = p.name
        try:
            processor.init_template_from_clips_dir(clips_dir, state_path, crop=config.TRAINING_CROP)
        except Exception as exc:
            failed.append({"video": p.name, "error": str(exc)})
    with _batch_init_jobs_lock:
        _batch_init_jobs[job_id]["phase"] = "done"
        _batch_init_jobs[job_id]["initialized"] = total - len(failed)
        _batch_init_jobs[job_id]["failed"] = len(failed)
        _batch_init_jobs[job_id]["failed_videos"] = failed


@bp.route("/batch-init", methods=["POST"])
def start_batch_init():
    body = request.get_json(force=True) or {}
    videos = body.get("videos", [])
    if not videos:
        return jsonify({"error": "videos list required"}), 400
    job_id = str(uuid.uuid4())
    with _batch_init_jobs_lock:
        _batch_init_jobs[job_id] = {
            "phase": "progress", "current": 0, "total": len(videos), "video": "",
        }
    thread = threading.Thread(target=_run_batch_init, args=(job_id, videos), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id})


@bp.route("/batch-init/stream")
def batch_init_stream():
    job_id = request.args.get("job_id")
    if not job_id or job_id not in _batch_init_jobs:
        return jsonify({"error": "unknown job_id"}), 404

    def generate():
        while True:
            with _batch_init_jobs_lock:
                job = dict(_batch_init_jobs[job_id])
            yield f"data: {json.dumps(job)}\n\n"
            if job.get("phase") == "done":
                break
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _run_batch_scan(job_id: str, template_dirs: list, video_paths: list, params: dict):
    stride        = params.get("stride",        config.SCAN_STRIDE)
    threshold     = params.get("threshold",     config.SIMILARITY_THRESHOLD)
    min_spacing   = params.get("min_spacing",   config.MIN_PEAK_SPACING)
    fine_window   = params.get("fine_window",   config.FINE_SCAN_WINDOW)
    scan_mode     = params.get("scan_mode",     "clip_only")
    trigger_value = params.get("trigger_value", config.SENSOR_TRIGGER_VALUE)
    sensor_margin = params.get("sensor_margin", config.SENSOR_MARGIN)

    combined = processor.load_combined_template(template_dirs)
    if combined["clip_matrix"] is None:
        with _batch_scan_jobs_lock:
            _batch_scan_jobs[job_id]["phase"] = "error"
            _batch_scan_jobs[job_id]["error"] = "No valid templates found in selected directories"
        return

    results = []
    total_videos = len(video_paths)
    for i, video_path in enumerate(video_paths):
        def phase_cb(phase, current, total, _vpath=video_path, _i=i):
            with _batch_scan_jobs_lock:
                _batch_scan_jobs[job_id]["video"] = Path(_vpath).name
                _batch_scan_jobs[job_id]["video_index"] = _i + 1
                _batch_scan_jobs[job_id]["video_total"] = total_videos
                _batch_scan_jobs[job_id]["phase"] = phase
                _batch_scan_jobs[job_id]["current"] = current
                _batch_scan_jobs[job_id]["total"] = total

        try:
            if scan_mode == "sensor+clip":
                csv_path = Path(video_path).with_suffix(".csv")
                if not csv_path.exists():
                    raise FileNotFoundError(f"CSV not found for {video_path}")
                detections = processor.scan_video_sensor_guided_multi(
                    video_path, combined, csv_path,
                    trigger_value=trigger_value,
                    sensor_margin=sensor_margin,
                    stride=stride, threshold=threshold,
                    min_spacing=min_spacing, fine_window=fine_window,
                    batch_size=config.SCAN_BATCH_SIZE,
                    phase_cb=phase_cb,
                )
            else:
                detections = processor.scan_video_multi_template(
                    video_path, combined,
                    stride=stride, threshold=threshold,
                    min_spacing=min_spacing, fine_window=fine_window,
                    batch_size=config.SCAN_BATCH_SIZE,
                    phase_cb=phase_cb,
                )
            for d in detections:
                d["status"] = "pending"
                d["source"] = "global_library"
            results.append({"video": video_path, "detections": detections})
        except Exception as exc:
            results.append({"video": video_path, "error": str(exc), "detections": []})

    with _batch_scan_jobs_lock:
        _batch_scan_jobs[job_id]["phase"] = "done"
        _batch_scan_jobs[job_id]["results"] = results


@bp.route("/batch-scan", methods=["POST"])
def start_batch_scan():
    body = request.get_json(force=True) or {}
    template_dirs = body.get("template_dirs", [])
    video_paths = body.get("video_paths", [])
    if not template_dirs:
        return jsonify({"error": "template_dirs required"}), 400
    if not video_paths:
        return jsonify({"error": "video_paths required"}), 400
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    job_id = str(uuid.uuid4())
    with _batch_scan_jobs_lock:
        _batch_scan_jobs[job_id] = {
            "phase": "starting", "video": "", "video_index": 0, "video_total": len(video_paths),
            "current": 0, "total": 1,
        }
    thread = threading.Thread(
        target=_run_batch_scan,
        args=(job_id, template_dirs, video_paths, params),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id})


@bp.route("/batch-scan/stream")
def batch_scan_stream():
    job_id = request.args.get("job_id")
    if not job_id or job_id not in _batch_scan_jobs:
        return jsonify({"error": "unknown job_id"}), 404

    def generate():
        while True:
            with _batch_scan_jobs_lock:
                job = dict(_batch_scan_jobs[job_id])
            yield f"data: {json.dumps(job)}\n\n"
            if job.get("phase") in ("done", "error"):
                break
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _run_batch_template_scan(job_id: str, template_dirs: list, video_paths: list, params: dict):
    stride        = params.get("stride",        config.SCAN_STRIDE)
    threshold     = params.get("threshold",     config.SIMILARITY_THRESHOLD)
    n_clusters    = params.get("n_clusters",    10)
    scan_mode     = params.get("scan_mode",     "clip_only")
    trigger_value = params.get("trigger_value", 14)
    sensor_margin = params.get("sensor_margin", 25)

    combined = processor.load_combined_template(template_dirs)
    if combined["clip_matrix"] is None:
        with _batch_template_scan_jobs_lock:
            _batch_template_scan_jobs[job_id]["phase"] = "error"
            _batch_template_scan_jobs[job_id]["error"] = "No valid templates found in selected directories"
        return

    per_video = []
    total_videos = len(video_paths)
    for i, video_path in enumerate(video_paths):
        def phase_cb(phase, current, total, _vpath=video_path, _i=i):
            with _batch_template_scan_jobs_lock:
                _batch_template_scan_jobs[job_id]["video"] = Path(_vpath).name
                _batch_template_scan_jobs[job_id]["video_index"] = _i + 1
                _batch_template_scan_jobs[job_id]["video_total"] = total_videos
                _batch_template_scan_jobs[job_id]["phase"] = phase
                _batch_template_scan_jobs[job_id]["current"] = current
                _batch_template_scan_jobs[job_id]["total"] = total

        try:
            csv_path = Path(video_path).with_suffix(".csv") if scan_mode == "sensor+clip" else None
            result = processor.find_template_candidates(
                video_path, combined,
                n_clusters=n_clusters,
                threshold=threshold,
                stride=stride,
                batch_size=config.SCAN_BATCH_SIZE,
                phase_cb=phase_cb,
                csv_path=csv_path,
                trigger_value=trigger_value,
                sensor_margin=sensor_margin,
            )
            per_video.append({
                "video_path": video_path,
                "candidates": result["candidates"],
                "curve": result["curve"],
                "embeddings": result["embeddings"],  # ndarray — stays in memory
            })
        except Exception as exc:
            per_video.append({
                "video_path": video_path,
                "candidates": [],
                "curve": [],
                "embeddings": None,
                "error": str(exc),
            })

    # Build serialisable results for SSE (exclude embeddings ndarray)
    sse_results = [
        {"video_path": v["video_path"], "candidates": v["candidates"]}
        for v in per_video
    ]
    with _batch_template_scan_jobs_lock:
        _batch_template_scan_jobs[job_id]["phase"] = "done"
        _batch_template_scan_jobs[job_id]["results"] = sse_results
        _batch_template_scan_jobs[job_id]["per_video"] = per_video


@bp.route("/batch-template-scan", methods=["POST"])
def start_batch_template_scan():
    body = request.get_json(force=True) or {}
    template_dirs = body.get("template_dirs", [])
    video_paths   = body.get("video_paths",   [])
    if not template_dirs:
        return jsonify({"error": "template_dirs required"}), 400
    if not video_paths:
        return jsonify({"error": "video_paths required"}), 400
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    job_id = str(uuid.uuid4())
    with _batch_template_scan_jobs_lock:
        _batch_template_scan_jobs[job_id] = {
            "phase": "starting", "video": "", "video_index": 0,
            "video_total": len(video_paths), "current": 0, "total": 1,
        }
    threading.Thread(
        target=_run_batch_template_scan,
        args=(job_id, template_dirs, video_paths, params),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@bp.route("/batch-template-scan/stream")
def batch_template_scan_stream():
    job_id = request.args.get("job_id")
    if not job_id or job_id not in _batch_template_scan_jobs:
        return jsonify({"error": "unknown job_id"}), 404

    def generate():
        while True:
            with _batch_template_scan_jobs_lock:
                job = {k: v for k, v in _batch_template_scan_jobs[job_id].items()
                       if k not in ("per_video", "embeddings")}
            yield f"data: {json.dumps(job)}\n\n"
            if job.get("phase") in ("done", "error"):
                break
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.route("/batch-template-scan/<job_id>/recluster", methods=["POST"])
def batch_template_scan_recluster(job_id):
    import numpy as np
    from sklearn.cluster import KMeans

    body      = request.get_json(force=True) or {}
    threshold  = float(body.get("threshold",  0.70))
    n_clusters = int(body.get("n_clusters",   10))

    with _batch_template_scan_jobs_lock:
        if job_id not in _batch_template_scan_jobs:
            return jsonify({"error": "unknown job_id"}), 404
        job = _batch_template_scan_jobs[job_id]
        if job.get("phase") != "done":
            return jsonify({"error": "job not complete"}), 400
        per_video = job.get("per_video", [])

    results = []
    for vdata in per_video:
        video_path = vdata["video_path"]
        curve      = vdata.get("curve", [])
        embeddings = vdata.get("embeddings")

        if embeddings is None or len(curve) == 0:
            results.append({"video_path": video_path, "candidates": []})
            continue

        filtered_indices = [i for i, c in enumerate(curve) if c["similarity"] >= threshold]
        if not filtered_indices:
            results.append({"video_path": video_path, "candidates": []})
            continue

        filtered_pos  = np.array([curve[i]["frame_number"] for i in filtered_indices])
        filtered_embs = embeddings[filtered_indices]
        filtered_sims = np.array([curve[i]["similarity"]   for i in filtered_indices])

        if len(filtered_pos) <= n_clusters:
            candidates = [
                {"frame_number": int(filtered_pos[i]) + 1,
                 "similarity":   float(filtered_sims[i]),
                 "cluster_id":   i}
                for i in range(len(filtered_pos))
            ]
            results.append({"video_path": video_path, "candidates": candidates})
            continue

        km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
        km.fit(filtered_embs)
        candidates = []
        for cid in range(n_clusters):
            idx_in_cluster = np.where(km.labels_ == cid)[0]
            if len(idx_in_cluster) == 0:
                continue
            dists  = np.linalg.norm(filtered_embs[idx_in_cluster] - km.cluster_centers_[cid], axis=1)
            nearest = idx_in_cluster[np.argsort(dists)[:2]]
            for j in nearest:
                candidates.append({
                    "frame_number": int(filtered_pos[j]) + 1,
                    "similarity":   float(filtered_sims[j]),
                    "cluster_id":   int(cid),
                })
        candidates.sort(key=lambda c: c["frame_number"])
        results.append({"video_path": video_path, "candidates": candidates})

    return jsonify({"results": results})


@bp.route("/template-frame-add", methods=["POST"])
def template_frame_add():
    body         = request.get_json(force=True) or {}
    video_path   = body.get("video_path",   "").strip()
    frame_number = body.get("frame_number")
    if not video_path or frame_number is None:
        return jsonify({"error": "video_path and frame_number required"}), 400

    clips_dir = Path(video_path).parent / Path(video_path).stem
    state_path = None
    for candidate in [
        clips_dir / "template" / "template_state.json",
        clips_dir / "template_state.json",
    ]:
        if candidate.exists():
            state_path = candidate
            break
    if state_path is None:
        # Default: create inside clips_dir/template/
        state_path = clips_dir / "template" / "template_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)

    state = processor.load_template_state(state_path)
    state = processor.add_frame_to_template(state, video_path, int(frame_number), state_path)
    return jsonify({"count": len(state["frames"])})


# ── Filesystem browser ──────────────────────────────────────────────────────────

@bp.route("/fs/ls")
def fs_ls():
    path_str = request.args.get("path", "").strip()
    p = Path(path_str) if path_str else config._DATA_ROOT
    if not p.is_dir():
        return jsonify({"error": "not a directory"}), 400

    dirs, files = [], []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: e.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                has_avi = any(entry.glob("*.avi"))
                dirs.append({"name": entry.name, "type": "dir", "has_avi": has_avi})
            elif entry.is_file() and entry.suffix.lower() == ".avi":
                stem = entry.stem
                video_dir = p / stem
                done = video_dir.is_dir() and any(video_dir.glob("*.avi"))
                files.append({"name": entry.name, "type": "file", "done": done})
    except PermissionError:
        return jsonify({"error": "permission denied"}), 403

    parent = str(p.parent) if p.parent != p else None
    return jsonify({"path": str(p), "parent": parent, "entries": dirs + files})


@bp.route("/select-video", methods=["POST"])
def select_video():
    global _state
    body = request.get_json(force=True)
    video_path_str = (body.get("video_path") or "").strip()
    if not video_path_str:
        return jsonify({"error": "video_path required"}), 400
    p = Path(video_path_str)
    stem = p.stem
    parent = str(p.parent)
    with _state_lock:
        _state["video_stem"] = stem
        _state["video_parent"] = parent

    tpath = _template_path()
    if tpath and tpath.exists():
        new_state = processor.load_template_state(tpath)
        new_state["video_stem"] = stem
        new_state["video_parent"] = parent
        with _state_lock:
            _state.update(new_state)
        has_template = True
    else:
        with _state_lock:
            _state["frames"] = []
            _state["mean_embedding"] = None
            _state["dino_mean_embedding"] = None
        has_template = False

    with _state_lock:
        count = len(_state["frames"])
    return jsonify({"count": count, "has_template": has_template})


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

        with _state_lock:
            _stem = _state.get("video_stem")
            _parent = _state.get("video_parent")
        clips_dir = Path(_parent) / _stem if (_stem and _parent) else config.TRAINING_CLIPS_DIR
        known = processor.get_known_key_frames(clips_dir)
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


@bp.route("/check-keyframe-overlap", methods=["POST"])
def check_keyframe_overlap():
    body = request.get_json(force=True, silent=True) or {}
    video_path = (body.get("video_path") or "").strip()
    key_frame = body.get("key_frame")
    if not video_path or key_frame is None:
        return jsonify({"error": "video_path and key_frame required"}), 400

    try:
        key_frame = int(key_frame)
    except (TypeError, ValueError):
        return jsonify({"error": "key_frame must be an integer"}), 400

    video_path = Path(video_path)
    clips_dir = video_path.parent / video_path.stem

    if not clips_dir.is_dir():
        return jsonify({"overlaps": False})

    known = processor.get_known_key_frames(clips_dir)

    new_start = key_frame - 200
    new_end = key_frame + 599
    conflicts = []
    for kf, stem in known.items():
        ex_start = kf - 200
        ex_end = kf + 599
        if new_start <= ex_end and new_end >= ex_start:
            overlap = min(new_end, ex_end) - max(new_start, ex_start) + 1
            conflicts.append({"name": stem + ".avi", "overlap_frames": overlap})

    if conflicts:
        return jsonify({"overlaps": True, "conflicts": conflicts})
    return jsonify({"overlaps": False})


@bp.route("/csv")
def get_csv():
    path_str = request.args.get("path", "").strip()
    if not path_str:
        return jsonify({"error": "path required"}), 400

    try:
        csv_path = Path(path_str).resolve()
        csv_path.relative_to(config._DATA_ROOT.resolve())
    except ValueError:
        return jsonify({"error": "path outside data root"}), 403

    if not csv_path.exists():
        return jsonify({"error": "file not found"}), 404
    if not csv_path.is_file():
        return jsonify({"error": "path is not a file"}), 400

    rows = []
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "frame_number": int(row["frame_number"]),
                    "frame_line_status": str(row.get("frame_line_status", "") or ""),
                    "note": str(row.get("note", "") or ""),
                })
    except Exception as e:
        return jsonify({"error": f"CSV parse error: {e}"}), 500

    return jsonify({"rows": rows})


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

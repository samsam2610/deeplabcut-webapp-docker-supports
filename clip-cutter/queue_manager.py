from __future__ import annotations

import datetime
import json
import os
import threading
import time
import uuid
from pathlib import Path

import config

_lock = threading.Lock()
_worker_event = threading.Event()
_process_now_flag = threading.Event()
_stop_event = threading.Event()
_last_enqueue_time: float = 0.0

_queue_state: dict = {"items": []}


def _load() -> None:
    path = config.QUEUE_PATH
    if not path.exists():
        _queue_state["items"] = []
        return
    try:
        data = json.loads(path.read_text())
        items = data.get("items", [])
        for item in items:
            if item.get("status") == "processing":
                item["status"] = "pending"
        _queue_state["items"] = items
    except (json.JSONDecodeError, OSError):
        _queue_state["items"] = []


def _save() -> None:
    """Atomically persist queue. Caller must hold _lock."""
    path = config.QUEUE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"items": _queue_state["items"]}, indent=2))
    os.replace(tmp, path)


def add(
    video_path: str,
    key_frame: int,
    postfix: str = "",
    sibling_video_path: "str | None" = None,
    extract_sibling: bool = False,
) -> list[str]:
    """Add 1 or 2 queue items. Resets inactivity timer. Returns item IDs."""
    global _last_enqueue_time
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    group_id = str(uuid.uuid4())
    added_ids: list[str] = []

    primary: dict = {
        "id": str(uuid.uuid4()),
        "group_id": group_id,
        "video_path": str(video_path),
        "key_frame": int(key_frame),
        "postfix": postfix,
        "status": "pending",
        "enqueued_at": now_iso,
        "finished_at": None,
        "error": None,
        "avi_path": None,
    }

    with _lock:
        _queue_state["items"].append(primary)
        added_ids.append(primary["id"])

        if extract_sibling and sibling_video_path:
            sibling: dict = {
                "id": str(uuid.uuid4()),
                "group_id": group_id,
                "video_path": str(sibling_video_path),
                "key_frame": int(key_frame),
                "postfix": postfix,
                "status": "pending",
                "enqueued_at": now_iso,
                "finished_at": None,
                "error": None,
                "avi_path": None,
            }
            _queue_state["items"].append(sibling)
            added_ids.append(sibling["id"])

        _last_enqueue_time = time.time()
        _save()

    _worker_event.set()
    return added_ids


def remove(item_id: str) -> bool:
    """Remove a pending item by ID. Returns True if found and removed."""
    with _lock:
        for i, item in enumerate(_queue_state["items"]):
            if item["id"] == item_id and item["status"] == "pending":
                _queue_state["items"].pop(i)
                _save()
                return True
    return False


def get_status() -> dict:
    """Return a snapshot of queue state (no lock held after return)."""
    with _lock:
        items = [dict(it) for it in _queue_state["items"]]
    pending = sum(1 for it in items if it["status"] == "pending")
    processing = any(it["status"] == "processing" for it in items)
    return {"items": items, "pending_count": pending, "processing": processing}


def process_now() -> None:
    """Signal the worker to process the queue immediately."""
    _process_now_flag.set()
    _worker_event.set()


def _process_one(item: dict) -> None:
    """Extract one item. Called from worker thread without lock held."""
    import processor  # local import to allow monkeypatching in tests
    video_path = Path(item["video_path"])
    parent_csv = video_path.with_suffix(".csv")
    output_dir = video_path.parent / video_path.stem

    try:
        if not parent_csv.exists():
            raise FileNotFoundError(f"CSV not found: {parent_csv}")
        result = processor.extract_clip(
            video_path, parent_csv, item["key_frame"], output_dir,
            postfix=item["postfix"],
        )
        with _lock:
            item["status"] = "done"
            item["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            item["avi_path"] = result["avi_path"]
            _save()
        _update_detection(item["video_path"], item["key_frame"], "kept", result["avi_path"])
    except Exception as exc:
        with _lock:
            item["status"] = "error"
            item["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            item["error"] = str(exc)
            _save()


def _update_detection(video_path: str, key_frame: int, status: str,
                      avi_path: "str | None" = None) -> None:
    """Sync matching detection in per-video JSON. Best-effort — swallows errors."""
    try:
        import processor  # local import
        data = processor.load_detections(video_path, config.DETECTIONS_DIR)
        if data is None:
            return
        changed = False
        for d in data.get("detections", []):
            if d.get("video_path") == video_path and d.get("frame_number") == key_frame:
                d["status"] = status
                if avi_path is not None:
                    d["extract_avi_path"] = avi_path
                changed = True
                break
        if changed:
            processor.save_detections(
                video_path, data["detections"],
                data.get("template_frame_count", 0),
                config.DETECTIONS_DIR,
            )
    except Exception:
        pass


def _worker_loop() -> None:
    """Background thread: sequential processing + 5-min inactivity auto-trigger."""
    _load()
    while not _stop_event.is_set():
        _worker_event.wait(timeout=30)
        _worker_event.clear()
        if _stop_event.is_set():
            break

        force = _process_now_flag.is_set()
        _process_now_flag.clear()

        with _lock:
            elapsed = (time.time() - _last_enqueue_time) if _last_enqueue_time > 0 else float("inf")
            has_pending = any(it["status"] == "pending" for it in _queue_state["items"])

        if not has_pending:
            continue

        if not force and elapsed < 300:
            continue

        while not _stop_event.is_set():
            with _lock:
                item = next(
                    (it for it in _queue_state["items"] if it["status"] == "pending"), None
                )
                if item is None:
                    break
                item["status"] = "processing"
                _save()
            _process_one(item)


def start_worker() -> None:
    """Start the background worker thread once at app startup."""
    for t in threading.enumerate():
        if t.name == "queue-worker" and t.is_alive():
            return  # already running
    _load()
    _stop_event.clear()
    threading.Thread(target=_worker_loop, daemon=True, name="queue-worker").start()

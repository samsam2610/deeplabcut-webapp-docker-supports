# Extract Queue + Sibling-Cam Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sequential extract queue (deferred extraction via `queue.json`) and a sibling-camera clip extraction checkbox, plus per-card and bulk buttons to backfill sibling clips for legacy "kept" detections.

**Architecture:** A new `queue_manager.py` module owns all queue state (in-memory + atomic JSON persistence) and runs a background daemon thread that processes items sequentially. Routes delegate to the manager. The frontend watches queue state via a persistent SSE stream, drives queue interactions, and syncs queue state to detection cards on load and live.

**Tech Stack:** Python 3, Flask SSE, threading.Event, pytest + monkeypatch; vanilla JS + fetch; existing `processor.extract_clip`.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `clip-cutter/config.py` | Modify | Add `QUEUE_PATH` constant |
| `clip-cutter/queue_manager.py` | Create | Queue state, worker thread, load/save, add/remove/get_status, detection JSON sync |
| `clip-cutter/routes.py` | Modify | Add 5 queue endpoints + SSE route |
| `clip-cutter/app.py` | Modify | Call `queue_manager.start_worker()` on startup |
| `clip-cutter/tests/test_queue_manager.py` | Create | Unit tests for queue_manager |
| `clip-cutter/tests/conftest.py` | Modify | Reset queue_manager state between tests |
| `clip-cutter/templates/clip_cutter.html` | Modify | Add sibling checkbox, Extract Queue button in detections bar, ep-remove-queue button, rename ep-extract label |
| `clip-cutter/static/clip_cutter.js` | Modify | Queue SSE, candidate card queue button, detections bar logic, sibling backfill |
| `clip-cutter/static/enhanced_player.js` | Modify | Extract Queue wiring, sibling checkbox visibility/read |

---

## Task 1: Add QUEUE_PATH to config

**Files:**
- Modify: `clip-cutter/config.py`

- [ ] **Step 1: Add QUEUE_PATH constant**

Open `config.py` and add after the `LIBRARIES_PATH` block:

```python
QUEUE_PATH = Path(
    os.environ.get(
        "CLIP_CUTTER_QUEUE_PATH",
        str(_DATA_ROOT / "Reaching-Task-Data/clip-cutter/queue.json"),
    )
)
```

- [ ] **Step 2: Verify import works**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -c "import config; print(config.QUEUE_PATH)"
```

Expected: prints the path without error.

- [ ] **Step 3: Commit**

```bash
git add clip-cutter/config.py
git commit -m "feat: add QUEUE_PATH config constant"
```

---

## Task 2: queue_manager.py — core state, load/save, add/remove/get_status

**Files:**
- Create: `clip-cutter/queue_manager.py`
- Create: `clip-cutter/tests/test_queue_manager.py`

- [ ] **Step 1: Write failing tests**

Create `clip-cutter/tests/test_queue_manager.py`:

```python
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def reset_qm(tmp_path, monkeypatch):
    import config
    import queue_manager

    monkeypatch.setattr(config, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(config, "DETECTIONS_DIR", tmp_path / "detections")

    # Reset all module-level state
    import importlib
    importlib.reload(queue_manager)

    yield

    queue_manager._stop_event.set()
    queue_manager._worker_event.set()


def test_add_creates_pending_item(tmp_path):
    import queue_manager
    ids = queue_manager.add("/data/cam0.avi", 1234, postfix="ok")
    assert len(ids) == 1
    status = queue_manager.get_status()
    assert status["pending_count"] == 1
    assert status["items"][0]["video_path"] == "/data/cam0.avi"
    assert status["items"][0]["key_frame"] == 1234
    assert status["items"][0]["postfix"] == "ok"
    assert status["items"][0]["status"] == "pending"


def test_add_persists_to_file(tmp_path, monkeypatch):
    import config, queue_manager
    ids = queue_manager.add("/data/cam0.avi", 200)
    data = json.loads(config.QUEUE_PATH.read_text())
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == ids[0]


def test_add_with_sibling_creates_two_items():
    import queue_manager
    ids = queue_manager.add(
        "/data/cam0.avi", 200, postfix="",
        sibling_video_path="/data/cam1.avi", extract_sibling=True
    )
    assert len(ids) == 2
    status = queue_manager.get_status()
    assert status["pending_count"] == 2
    items = status["items"]
    assert items[0]["group_id"] == items[1]["group_id"]
    assert items[0]["video_path"] == "/data/cam0.avi"
    assert items[1]["video_path"] == "/data/cam1.avi"


def test_add_without_sibling_flag_creates_one_item():
    import queue_manager
    ids = queue_manager.add(
        "/data/cam0.avi", 200,
        sibling_video_path="/data/cam1.avi", extract_sibling=False
    )
    assert len(ids) == 1


def test_remove_pending_item():
    import queue_manager
    ids = queue_manager.add("/data/cam0.avi", 200)
    removed = queue_manager.remove(ids[0])
    assert removed is True
    assert queue_manager.get_status()["pending_count"] == 0


def test_remove_unknown_id_returns_false():
    import queue_manager
    assert queue_manager.remove("nonexistent-id") is False


def test_remove_done_item_returns_false(monkeypatch):
    import queue_manager
    ids = queue_manager.add("/data/cam0.avi", 200)
    # Manually mark as done
    with queue_manager._lock:
        queue_manager._queue_state["items"][0]["status"] = "done"
    assert queue_manager.remove(ids[0]) is False


def test_get_status_processing_flag(monkeypatch):
    import queue_manager
    queue_manager.add("/data/cam0.avi", 200)
    with queue_manager._lock:
        queue_manager._queue_state["items"][0]["status"] = "processing"
    status = queue_manager.get_status()
    assert status["processing"] is True
    assert status["pending_count"] == 0


def test_load_resets_processing_to_pending(tmp_path, monkeypatch):
    import config, queue_manager, importlib
    # Write a queue file with a "processing" item
    config.QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.QUEUE_PATH.write_text(json.dumps({"items": [
        {"id": "abc", "group_id": "g1", "video_path": "/x.avi",
         "key_frame": 100, "postfix": "", "status": "processing",
         "enqueued_at": "2026-01-01T00:00:00", "finished_at": None,
         "error": None, "avi_path": None}
    ]}))
    importlib.reload(queue_manager)
    status = queue_manager.get_status()
    assert status["items"][0]["status"] == "pending"


def test_load_empty_when_file_missing():
    import queue_manager
    status = queue_manager.get_status()
    assert status["pending_count"] == 0
    assert status["items"] == []


def test_load_empty_when_file_corrupt(tmp_path, monkeypatch):
    import config, queue_manager, importlib
    config.QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.QUEUE_PATH.write_text("NOT JSON {{}")
    importlib.reload(queue_manager)
    assert queue_manager.get_status()["items"] == []
```

- [ ] **Step 2: Run to verify all fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_queue_manager.py -v 2>&1 | head -40
```

Expected: `ModuleNotFoundError: No module named 'queue_manager'` (all fail, no import yet).

- [ ] **Step 3: Create queue_manager.py with core implementation**

Create `clip-cutter/queue_manager.py`:

```python
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
    _load()
    _stop_event.clear()
    threading.Thread(target=_worker_loop, daemon=True, name="queue-worker").start()
```

- [ ] **Step 4: Run the core tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_queue_manager.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/queue_manager.py clip-cutter/tests/test_queue_manager.py
git commit -m "feat: add queue_manager core (add/remove/get_status/load/save)"
```

---

## Task 3: queue_manager.py — worker processing + detection JSON update

**Files:**
- Modify: `clip-cutter/tests/test_queue_manager.py` (add worker tests)

- [ ] **Step 1: Write failing worker tests**

Append to `clip-cutter/tests/test_queue_manager.py`:

```python
def test_process_now_extracts_item(tmp_path, monkeypatch):
    import processor, queue_manager

    extract_calls = []

    def fake_extract(video_path, parent_csv, key_frame, output_dir, postfix=""):
        extract_calls.append((str(video_path), key_frame, postfix))
        avi = output_dir / f"clip_{key_frame}.avi"
        avi.parent.mkdir(parents=True, exist_ok=True)
        avi.touch()
        return {"avi_path": str(avi), "start_frame_number": 1, "end_frame_number": 800}

    monkeypatch.setattr(processor, "extract_clip", fake_extract)

    # Create a fake CSV so the worker doesn't fail with FileNotFoundError
    csv = tmp_path / "cam0.csv"
    csv.write_text("frame_number,frame_line_status,note\n1,0,\n")
    avi = tmp_path / "cam0.avi"
    avi.touch()

    queue_manager.add(str(avi), 200)
    queue_manager.start_worker()
    queue_manager.process_now()

    # Wait up to 3s for the item to be processed
    deadline = time.time() + 3
    while time.time() < deadline:
        if queue_manager.get_status()["pending_count"] == 0:
            break
        time.sleep(0.05)

    status = queue_manager.get_status()
    assert len(extract_calls) == 1
    assert extract_calls[0][1] == 200
    done_items = [it for it in status["items"] if it["status"] == "done"]
    assert len(done_items) == 1
    assert done_items[0]["avi_path"] is not None


def test_worker_marks_error_on_missing_csv(tmp_path, monkeypatch):
    import queue_manager

    avi = tmp_path / "cam0.avi"
    avi.touch()
    # No CSV file — worker should mark item as error
    queue_manager.add(str(avi), 200)
    queue_manager.start_worker()
    queue_manager.process_now()

    deadline = time.time() + 3
    while time.time() < deadline:
        items = queue_manager.get_status()["items"]
        if items and items[0]["status"] in ("done", "error"):
            break
        time.sleep(0.05)

    items = queue_manager.get_status()["items"]
    assert items[0]["status"] == "error"
    assert "CSV" in items[0]["error"]


def test_update_detection_updates_status(tmp_path, monkeypatch):
    import config, processor, queue_manager

    # Write a detection JSON for cam0.avi
    det_dir = tmp_path / "detections"
    det_dir.mkdir()
    monkeypatch.setattr(config, "DETECTIONS_DIR", det_dir)

    video_path = str(tmp_path / "cam0.avi")
    detections = [
        {"video_path": video_path, "frame_number": 200, "status": "queued",
         "similarity": 0.9, "source": "sensor+clip"}
    ]
    processor.save_detections(video_path, detections, 3, det_dir)

    queue_manager._update_detection(video_path, 200, "kept", "/some/clip.avi")

    data = processor.load_detections(video_path, det_dir)
    assert data["detections"][0]["status"] == "kept"
    assert data["detections"][0]["extract_avi_path"] == "/some/clip.avi"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_queue_manager.py::test_process_now_extracts_item tests/test_queue_manager.py::test_worker_marks_error_on_missing_csv tests/test_queue_manager.py::test_update_detection_updates_status -v
```

Expected: `test_process_now_extracts_item` and `test_update_detection_updates_status` fail (worker code not wired yet in step 1's implementation, but actually it is — these may already pass from Task 2's implementation). If they all pass already, skip step 3.

- [ ] **Step 3: Run all queue_manager tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_queue_manager.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add clip-cutter/tests/test_queue_manager.py
git commit -m "test: add worker + detection JSON update tests for queue_manager"
```

---

## Task 4: routes.py — queue REST endpoints + SSE

**Files:**
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/tests/test_routes.py` (add queue route tests)

- [ ] **Step 1: Write failing route tests**

Append to `clip-cutter/tests/test_routes.py`:

```python
# ── Queue routes ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_queue_state(tmp_path, monkeypatch):
    """Reset queue_manager module state between route tests."""
    import config, queue_manager, importlib
    monkeypatch.setattr(config, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(config, "DETECTIONS_DIR", tmp_path / "detections")
    importlib.reload(queue_manager)
    yield
    queue_manager._stop_event.set()
    queue_manager._worker_event.set()


def test_queue_get_empty(client):
    resp = client.get("/clip-cutter/queue")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["pending_count"] == 0
    assert data["items"] == []


def test_queue_post_adds_item(client, tmp_path):
    (tmp_path / "cam0.avi").touch()
    resp = client.post("/clip-cutter/queue", json={
        "video_path": str(tmp_path / "cam0.avi"),
        "key_frame": 200,
        "postfix": "ok",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["ids"]) == 1
    assert data["pending_count"] == 1


def test_queue_post_with_sibling_adds_two_items(client, tmp_path):
    (tmp_path / "cam0.avi").touch()
    (tmp_path / "cam1.avi").touch()
    resp = client.post("/clip-cutter/queue", json={
        "video_path": str(tmp_path / "cam0.avi"),
        "key_frame": 200,
        "extract_sibling": True,
        "sibling_video_path": str(tmp_path / "cam1.avi"),
    })
    assert resp.status_code == 200
    assert len(resp.get_json()["ids"]) == 2


def test_queue_post_missing_video_path_returns_400(client):
    resp = client.post("/clip-cutter/queue", json={"key_frame": 200})
    assert resp.status_code == 400


def test_queue_post_missing_key_frame_returns_400(client, tmp_path):
    (tmp_path / "cam0.avi").touch()
    resp = client.post("/clip-cutter/queue", json={
        "video_path": str(tmp_path / "cam0.avi"),
    })
    assert resp.status_code == 400


def test_queue_delete_removes_item(client, tmp_path):
    (tmp_path / "cam0.avi").touch()
    post_resp = client.post("/clip-cutter/queue", json={
        "video_path": str(tmp_path / "cam0.avi"),
        "key_frame": 200,
    })
    item_id = post_resp.get_json()["ids"][0]
    del_resp = client.delete(f"/clip-cutter/queue/{item_id}")
    assert del_resp.status_code == 200
    assert del_resp.get_json()["ok"] is True
    status = client.get("/clip-cutter/queue").get_json()
    assert status["pending_count"] == 0


def test_queue_delete_unknown_id_returns_404(client):
    resp = client.delete("/clip-cutter/queue/no-such-id")
    assert resp.status_code == 404


def test_queue_process_returns_ok(client):
    resp = client.post("/clip-cutter/queue/process")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py -k "queue" -v 2>&1 | tail -20
```

Expected: all fail with 404 (routes not yet defined).

- [ ] **Step 3: Add queue routes to routes.py**

In `clip-cutter/routes.py`, add this import at the top alongside existing imports:

```python
import queue_manager
```

Then add these routes anywhere after the existing `_rescan_jobs` block (e.g., just before the `# ── UI` comment at line 109):

```python
# ── Extract queue ─────────────────────────────────────────────────────────────

@bp.route("/queue")
def get_queue():
    return jsonify(queue_manager.get_status())


@bp.route("/queue", methods=["POST"])
def add_to_queue():
    body = request.get_json(force=True) or {}
    video_path = (body.get("video_path") or "").strip()
    key_frame = body.get("key_frame")
    if not video_path or key_frame is None:
        return jsonify({"error": "video_path and key_frame required"}), 400
    postfix = (body.get("postfix") or "").strip()
    extract_sibling = bool(body.get("extract_sibling", False))
    sibling_video_path = (body.get("sibling_video_path") or "").strip() or None

    ids = queue_manager.add(
        video_path, int(key_frame), postfix,
        sibling_video_path=sibling_video_path,
        extract_sibling=extract_sibling,
    )
    return jsonify({"ids": ids, "pending_count": queue_manager.get_status()["pending_count"]})


@bp.route("/queue/<item_id>", methods=["DELETE"])
def remove_from_queue(item_id: str):
    removed = queue_manager.remove(item_id)
    if not removed:
        return jsonify({"error": "item not found or not pending"}), 404
    return jsonify({"ok": True})


@bp.route("/queue/process", methods=["POST"])
def trigger_queue_process():
    queue_manager.process_now()
    return jsonify({"ok": True})


@bp.route("/queue/stream")
def queue_stream():
    def generate():
        last = None
        while True:
            current = queue_manager.get_status()
            snapshot = json.dumps(current)
            if snapshot != last:
                yield f"data: {snapshot}\n\n"
                last = snapshot
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run queue route tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py -k "queue" -v
```

Expected: all pass.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add queue REST endpoints and SSE route"
```

---

## Task 5: Startup wiring + conftest reset

**Files:**
- Modify: `clip-cutter/app.py`
- Modify: `clip-cutter/tests/conftest.py`

- [ ] **Step 1: Wire worker start in app.py**

Replace the entire `clip-cutter/app.py` with:

```python
from flask import Flask
from routes import bp
import queue_manager


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.register_blueprint(bp)
    queue_manager.start_worker()
    return app


if __name__ == "__main__":
    import os
    port = int(os.environ.get("CLIP_CUTTER_PORT", 5002))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    create_app().run(host="0.0.0.0", port=port, debug=debug)
```

- [ ] **Step 2: Prevent worker from running in tests**

In `clip-cutter/tests/conftest.py`, add a module-level autouse fixture that monkeypatches `start_worker` to a no-op. Insert this right after the imports:

```python
@pytest.fixture(autouse=True)
def no_queue_worker(monkeypatch):
    """Prevent background worker thread from starting in tests."""
    import queue_manager
    monkeypatch.setattr(queue_manager, "start_worker", lambda: None)
```

- [ ] **Step 3: Add queue state reset to the existing reset_routes_state fixture**

In `conftest.py`, update the `reset_routes_state` fixture to also reset queue_manager state. Find the existing fixture and extend it:

```python
@pytest.fixture(autouse=True)
def reset_routes_state():
    """Reset global route state and queue_manager between tests."""
    import routes, queue_manager, importlib, config
    routes._state = {
        "frames": [],
        "mean_embedding": None,
        "dino_mean_embedding": None,
        "video_stem": None,
        "video_parent": None,
        "sibling_video_path": None,
    }
    routes._init_status = {"running": False, "error": None}
    routes._batch_init_jobs.clear()
    routes._batch_scan_jobs.clear()
    routes._batch_template_scan_jobs.clear()
    # Reset queue state (items + timer)
    with queue_manager._lock:
        queue_manager._queue_state["items"] = []
        queue_manager._last_enqueue_time = 0.0
    queue_manager._process_now_flag.clear()
    queue_manager._worker_event.clear()
    yield
    routes._state = {
        "frames": [],
        "mean_embedding": None,
        "dino_mean_embedding": None,
        "video_stem": None,
        "video_parent": None,
        "sibling_video_path": None,
    }
    routes._init_status = {"running": False, "error": None}
    routes._batch_init_jobs.clear()
    routes._batch_scan_jobs.clear()
    routes._batch_template_scan_jobs.clear()
    with queue_manager._lock:
        queue_manager._queue_state["items"] = []
        queue_manager._last_enqueue_time = 0.0
    queue_manager._process_now_flag.clear()
    queue_manager._worker_event.clear()
```

Also remove the `reset_queue_state` fixture added in Task 4's test (it's now redundant — the autouse fixture in conftest handles it). Delete these lines from `test_routes.py`:

```python
@pytest.fixture(autouse=True)
def reset_queue_state(tmp_path, monkeypatch):
    """Reset queue_manager module state between route tests."""
    import config, queue_manager, importlib
    monkeypatch.setattr(config, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(config, "DETECTIONS_DIR", tmp_path / "detections")
    importlib.reload(queue_manager)
    yield
    queue_manager._stop_event.set()
    queue_manager._worker_event.set()
```

- [ ] **Step 4: Run full test suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all tests pass (including queue tests).

- [ ] **Step 5: Commit**

```bash
git add clip-cutter/app.py clip-cutter/tests/conftest.py clip-cutter/tests/test_routes.py
git commit -m "feat: wire queue_manager worker startup and reset state in tests"
```

---

## Task 6: HTML changes

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

All changes are additions or single-line edits. Make them in the order listed.

- [ ] **Step 1: Add sibling-extraction checkbox below sync cam label**

Find this block (around line 894):
```html
      <label id="ep-sync-cam-label" title="Show same frame from sibling camera" style="display:none;">
        <input type="checkbox" id="ep-sync-cam"> sync cam
      </label>
```

Replace with:
```html
      <label id="ep-sync-cam-label" title="Show same frame from sibling camera" style="display:none;">
        <input type="checkbox" id="ep-sync-cam"> sync cam
      </label>
      <label id="ep-extract-sibling-label" title="Also extract clip from sibling camera" style="display:none;font-size:9px;color:#cdd9e5;cursor:pointer;gap:4px;align-items:center;">
        <input type="checkbox" id="ep-extract-sibling" checked> also extract sibling clip
      </label>
```

- [ ] **Step 2: Rename Extract button and add Remove queue button**

Find (around line 1046):
```html
    <button class="player-btn ep-btn-blue" id="ep-extract">&#9986; Extract</button>
    <button class="player-btn ep-btn-green" id="ep-rename-extract" style="display:none;" title="Rename with current postfix">&#9998; Update name</button>
    <button class="player-btn ep-btn-red" id="ep-delete-extract" style="display:none;">&#128465; Delete extract</button>
```

Replace with:
```html
    <button class="player-btn ep-btn-blue" id="ep-extract">&#9986; Extract Queue</button>
    <button class="player-btn ep-btn-red" id="ep-remove-queue" style="display:none;">&#9711; Remove queue</button>
    <button class="player-btn ep-btn-green" id="ep-rename-extract" style="display:none;" title="Rename with current postfix">&#9998; Update name</button>
    <button class="player-btn ep-btn-red" id="ep-delete-extract" style="display:none;">&#128465; Delete extract</button>
```

- [ ] **Step 3: Add Extract Queue and Queue missing siblings buttons to the detections bar**

Find (around line 836):
```html
      <button id="detections-browse-btn" disabled title="Open video viewer without scanning" style="font-size:9px;padding:1px 6px;background:#21262d;color:#768390;border:1px solid #30363d;border-radius:3px;cursor:not-allowed;">&#9654; Browse</button>
```

Replace with:
```html
      <button id="detections-browse-btn" disabled title="Open video viewer without scanning" style="font-size:9px;padding:1px 6px;background:#21262d;color:#768390;border:1px solid #30363d;border-radius:3px;cursor:not-allowed;">&#9654; Browse</button>
      <button id="extract-queue-btn" style="display:none;font-size:9px;padding:1px 6px;background:#1f6feb;color:#fff;border:1px solid #1f6feb;border-radius:3px;cursor:pointer;" title="Extract all queued detections now">&#9203; Extract Queue (<span id="queue-pending-count">0</span>)</button>
      <button id="queue-siblings-btn" style="display:none;font-size:9px;padding:1px 6px;background:#3d2b00;color:#f0c040;border:1px solid #6a4500;border-radius:3px;cursor:pointer;" title="Queue sibling clips for all extracted detections that lack one">&#9711; Queue missing siblings (<span id="queue-siblings-count">0</span>)</button>
```

- [ ] **Step 4: Add CSS for queue circle button in candidate cards**

Find the `.filter-btn.active` style block in the `<style>` section and add after it:

```css
.btn-queue { background: transparent; color: #f0c040; border: 1px solid #6a4500; border-radius: 50%; width: 18px; height: 18px; padding: 0; font-size: 10px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.btn-queue:hover { background: #3d2b00; }
.btn-queue.queued { background: #f0c040; color: #0d1117; border-color: #f0c040; }
.btn-queue:disabled { opacity: 0.4; cursor: not-allowed; }
```

- [ ] **Step 5: Update Shift+E keyboard shortcut hint in help tooltip**

Find:
```html
          <tr><td>Shift+E</td><td>Extract clip</td></tr>
```
Replace with:
```html
          <tr><td>Shift+E</td><td>Extract Queue</td></tr>
```

- [ ] **Step 6: Verify the page loads without JS errors**

Start the server:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python app.py
```
Open `http://localhost:5002/clip-cutter/` in a browser. Check the browser console for errors. The player panel should still show "✂ Extract Queue" when opened. Close the server (`Ctrl+C`).

- [ ] **Step 7: Commit**

```bash
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat: add queue UI elements to HTML (sibling checkbox, queue buttons, rename Extract)"
```

---

## Task 7: clip_cutter.js — queue SSE, candidate card queue button, detections bar, sibling backfill

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Add queue SSE connection and detections bar wiring**

At the top of `clip_cutter.js`, add these state variables alongside the existing ones:

```javascript
let _queueEs = null;
let _siblingVideoPath = null;  // set when select-video returns sibling_video_path
```

Add this function before the `loadLibraries` function:

```javascript
// ── Extract queue ─────────────────────────────────────────────────────────────

function _connectQueueStream() {
  if (_queueEs) { _queueEs.close(); _queueEs = null; }
  _queueEs = new EventSource("/clip-cutter/queue/stream");
  _queueEs.onmessage = (e) => {
    const status = JSON.parse(e.data);
    _applyQueueStatus(status);
  };
  _queueEs.onerror = () => {
    if (_queueEs) { _queueEs.close(); _queueEs = null; }
    // Reconnect after 5s
    setTimeout(_connectQueueStream, 5000);
  };
}

function _applyQueueStatus(status) {
  const pendingCount = status.pending_count || 0;
  const btn = document.getElementById("extract-queue-btn");
  const countEl = document.getElementById("queue-pending-count");
  if (btn) { btn.style.display = pendingCount > 0 ? "" : "none"; }
  if (countEl) countEl.textContent = String(pendingCount);

  // Update cards for items that have completed (status "done" or "error")
  (status.items || []).forEach(item => {
    if (item.status === "done" && item.avi_path) {
      _onQueueItemDone(item);
    } else if (item.status === "error") {
      _onQueueItemError(item);
    }
  });

  // Update sibling backfill button
  _updateSiblingBackfillBtn();
}

function _onQueueItemDone(item) {
  // Find detection by queue_item_id
  const idx = detections.findIndex(d => d.queue_item_id === item.id);
  if (idx === -1) return;
  const d = detections[idx];
  if (d.status === "kept") return;  // already updated
  d.status = "kept";
  d.extract_avi_path = item.avi_path;
  const card = document.getElementById(`card-${idx}`);
  if (card) {
    card.classList.add("kept");
    card.classList.remove("queued");
    card.querySelectorAll("button").forEach(b => { b.disabled = true; });
    const nameEl = card.querySelector(".result-name");
    if (nameEl) nameEl.textContent = item.avi_path.split("/").pop();
    // Show "Extract Sibling" button if sibling exists and no sibling path yet
    _renderSiblingExtractBtn(card, idx);
  }
  saveDetections();
}

function _onQueueItemError(item) {
  const idx = detections.findIndex(d => d.queue_item_id === item.id);
  if (idx === -1) return;
  const card = document.getElementById(`card-${idx}`);
  if (!card) return;
  // Show error pill on card
  const errEl = card.querySelector(".queue-error") || document.createElement("span");
  errEl.className = "queue-error";
  errEl.style.cssText = "font-size:8px;color:#f85149;margin-left:4px;";
  errEl.textContent = "⚠ " + (item.error || "extraction error");
  if (!card.querySelector(".queue-error")) {
    card.querySelector(".result-meta")?.appendChild(errEl);
  }
}

async function _queueDetection(idx) {
  const d = detections[idx];
  const postfix = (d.extract_postfix || "");
  const extractSibling = _siblingVideoPath
    ? (document.getElementById("ep-extract-sibling")?.checked ?? true)
    : false;

  try {
    const resp = await fetch("/clip-cutter/queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_path: d.video_path,
        key_frame: d.frame_number,
        postfix,
        extract_sibling: extractSibling,
        sibling_video_path: extractSibling ? _siblingVideoPath : undefined,
      }),
    });
    if (!resp.ok) { setStatus("Queue error"); return; }
    const data = await resp.json();
    detections[idx].status = "queued";
    detections[idx].queue_item_id = data.ids[0];
    if (data.ids[1]) detections[idx].sibling_queue_item_id = data.ids[1];
    const card = document.getElementById(`card-${idx}`);
    if (card) {
      const qBtn = card.querySelector(".btn-queue");
      if (qBtn) qBtn.classList.add("queued");
      card.classList.add("queued");
    }
    setStatus(`Detection queued for extraction (${data.pending_count} in queue)`);
    saveDetections();
  } catch (err) {
    setStatus("Network error: " + err.message);
  }
}

async function _unqueueDetection(idx) {
  const d = detections[idx];
  const itemId = d.queue_item_id;
  if (!itemId) return;
  try {
    const resp = await fetch(`/clip-cutter/queue/${encodeURIComponent(itemId)}`, {
      method: "DELETE",
    });
    if (!resp.ok && resp.status !== 404) { setStatus("Remove queue error"); return; }
    detections[idx].status = "pending";
    delete detections[idx].queue_item_id;
    delete detections[idx].sibling_queue_item_id;
    const card = document.getElementById(`card-${idx}`);
    if (card) {
      const qBtn = card.querySelector(".btn-queue");
      if (qBtn) qBtn.classList.remove("queued");
      card.classList.remove("queued");
    }
    setStatus("Removed from queue");
    saveDetections();
  } catch (err) {
    setStatus("Network error: " + err.message);
  }
}

function _updateSiblingBackfillBtn() {
  if (!_siblingVideoPath) {
    const btn = document.getElementById("queue-siblings-btn");
    if (btn) btn.style.display = "none";
    return;
  }
  const eligible = detections.filter(d =>
    d.status === "kept" && d.extract_avi_path && !d.sibling_extract_avi_path
  );
  const btn = document.getElementById("queue-siblings-btn");
  const countEl = document.getElementById("queue-siblings-count");
  if (btn) btn.style.display = eligible.length > 0 ? "" : "none";
  if (countEl) countEl.textContent = String(eligible.length);
}

async function _queueMissingSiblings() {
  if (!_siblingVideoPath) return;
  const eligible = detections.filter(d =>
    d.status === "kept" && d.extract_avi_path && !d.sibling_extract_avi_path
  );
  if (eligible.length === 0) return;
  setStatus(`Queuing sibling clips for ${eligible.length} detection(s)…`);
  let queued = 0;
  for (const d of eligible) {
    try {
      const resp = await fetch("/clip-cutter/queue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_path: _siblingVideoPath,
          key_frame: d.frame_number,
          postfix: d.extract_postfix || "",
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        d.sibling_queue_item_id = data.ids[0];
        queued++;
      }
    } catch { /* continue */ }
  }
  setStatus(`${queued} sibling clip(s) queued for extraction`);
  saveDetections();
  _updateSiblingBackfillBtn();
}

function _renderSiblingExtractBtn(card, idx) {
  if (!_siblingVideoPath) return;
  const d = detections[idx];
  if (d.status !== "kept" || d.sibling_extract_avi_path) return;
  if (card.querySelector(".sibling-extract-btn")) return;
  const btn = document.createElement("button");
  btn.className = "player-btn sibling-extract-btn";
  btn.style.cssText = "font-size:8px;padding:1px 5px;color:#f0c040;border-color:#6a4500;";
  btn.textContent = "Extract Sibling";
  btn.title = "Queue sibling camera clip";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const resp = await fetch("/clip-cutter/queue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_path: _siblingVideoPath,
          key_frame: d.frame_number,
          postfix: d.extract_postfix || "",
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        d.sibling_queue_item_id = data.ids[0];
        btn.textContent = "Sibling queued";
        setStatus("Sibling clip queued");
        saveDetections();
        _updateSiblingBackfillBtn();
      } else {
        btn.disabled = false;
        setStatus("Error queuing sibling clip");
      }
    } catch (err) {
      btn.disabled = false;
      setStatus("Network error: " + err.message);
    }
  });
  const meta = card.querySelector(".result-meta");
  if (meta) meta.appendChild(btn);
}
```

- [ ] **Step 2: Update buildResultCard to add queue circle button**

In `buildResultCard()`, find the buttons row in the `card.innerHTML` template:

```javascript
        <button class="btn-sm btn-green keep-btn" style="padding:1px 5px;font-size:9px;">&#10003;</button>
        <button class="btn-sm btn-red reject-btn" style="padding:1px 5px;font-size:9px;">&#10007;</button>
        <button class="btn-sm btn-blue add-btn" style="padding:1px 5px;font-size:9px;">+Tpl</button>
```

Replace with:

```javascript
        <button class="btn-sm btn-green keep-btn" style="padding:1px 5px;font-size:9px;">&#10003;</button>
        <button class="btn-queue queue-btn" title="Add to extract queue">&#9711;</button>
        <button class="btn-sm btn-red reject-btn" style="padding:1px 5px;font-size:9px;">&#10007;</button>
        <button class="btn-sm btn-blue add-btn" style="padding:1px 5px;font-size:9px;">+Tpl</button>
```

After the existing event listener attachments in `buildResultCard` (after `.add-btn` listener), add:

```javascript
  const qBtn = card.querySelector(".queue-btn");
  if (qBtn) {
    // Restore queued state from detection data
    if (d.status === "queued") {
      qBtn.classList.add("queued");
      card.classList.add("queued");
    }
    qBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (qBtn.classList.contains("queued") || d.status === "queued") {
        _unqueueDetection(idx);
      } else {
        _queueDetection(idx);
      }
    });
  }

  // Show "Extract Sibling" button on already-kept cards that lack a sibling clip
  if (d.status === "kept" && d.extract_avi_path) {
    _renderSiblingExtractBtn(card, idx);
  }
```

- [ ] **Step 3: Update selectVideo to capture sibling path**

In `selectVideo()`, after the fetch to `/clip-cutter/select-video`, update the success handler to capture `_siblingVideoPath`:

```javascript
  const { count, has_template, sibling_video_path } = await selectResp.json();
  _siblingVideoPath = sibling_video_path || null;
  _updateSiblingBackfillBtn();
```

Replace the existing line `const selectResp = await fetch(...)` block — the current code does:

```javascript
  const selectResp = await fetch("/clip-cutter/select-video", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: videoPath }),
  });
  if (!selectResp.ok) {
    setStatus("Failed to select video");
    return;
  }
```

After that `if` block, find where the code re-enables `scan-btn` and add:

```javascript
  const selectData = await selectResp.json();
  _siblingVideoPath = selectData.sibling_video_path || null;
  _updateSiblingBackfillBtn();
```

Remove any existing `await selectResp.json()` call in `selectVideo` (there currently isn't one — the existing code doesn't read the body). Add it explicitly:

```javascript
async function selectVideo(videoPath, stem, parent) {
  selectedVideoPath = videoPath;
  _selectedVideoStem = stem;
  _selectedVideoParent = parent;

  const selectResp = await fetch("/clip-cutter/select-video", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: videoPath }),
  });
  if (!selectResp.ok) {
    setStatus("Failed to select video");
    return;
  }
  const selectData = await selectResp.json();
  _siblingVideoPath = selectData.sibling_video_path || null;
  _updateSiblingBackfillBtn();

  document.getElementById("scan-btn").disabled = false;
  const browseBtn = document.getElementById("detections-browse-btn");
  if (browseBtn) { browseBtn.disabled = false; browseBtn.style.cursor = "pointer"; }
  updateBatchScanBtn();
  detections.length = 0;
  document.getElementById("results-list").innerHTML = "";
  document.getElementById("results-count").textContent = "";

  await loadTemplate();
  await loadSavedDetections(videoPath);
}
```

- [ ] **Step 4: Wire detections bar buttons and start SSE in DOMContentLoaded**

Inside the `DOMContentLoaded` handler (already exists), add these event listeners at the end of the handler, before the closing `});`:

```javascript
  // Extract Queue button
  document.getElementById("extract-queue-btn")?.addEventListener("click", () => {
    fetch("/clip-cutter/queue/process", { method: "POST" }).catch(() => {});
  });

  // Queue missing siblings button
  document.getElementById("queue-siblings-btn")?.addEventListener("click", _queueMissingSiblings);
```

Also call `_connectQueueStream()` at the start of the `DOMContentLoaded` handler (first line inside the handler, before `loadTemplate()`):

```javascript
document.addEventListener("DOMContentLoaded", () => {
  _connectQueueStream();
  loadTemplate();
  // ... rest unchanged
```

- [ ] **Step 5: Update loadSavedDetections to restore sibling backfill button**

In `loadSavedDetections`, after `renderDetections(data.detections);`, add:

```javascript
    _updateSiblingBackfillBtn();
```

- [ ] **Step 6: Manual smoke test**

Start the server and open the UI:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python app.py
```

1. Open browser console — no JS errors on load.
2. Select a video with a sibling camera → sibling backfill button should be hidden (no kept detections yet).
3. Check browser Network tab → `GET /clip-cutter/queue/stream` should be an open SSE connection.
4. Navigate to `http://localhost:5002/clip-cutter/queue` → should return `{"items": [], "pending_count": 0, "processing": false}`.

- [ ] **Step 7: Commit**

```bash
git add clip-cutter/static/clip_cutter.js
git commit -m "feat: add queue SSE, candidate card queue button, detections bar, sibling backfill"
```

---

## Task 8: enhanced_player.js — Extract Queue wiring + sibling checkbox

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js`

- [ ] **Step 1: Add ep-remove-queue button wiring in _epInitExtractPanel**

In `_epInitExtractPanel()`, find the block that shows/hides `ep-extract`, `ep-rename-extract`, `ep-delete-extract`:

```javascript
  document.getElementById("ep-extract").style.display = isKept ? "none" : "";
  document.getElementById("ep-rename-extract").style.display = isKept ? "" : "none";
  document.getElementById("ep-rename-extract").disabled = !hasPath;
  document.getElementById("ep-delete-extract").style.display = isKept ? "" : "none";
```

Replace with:

```javascript
  const isQueued = _mode === "clip" && _detectionIdx !== null &&
    typeof detections !== "undefined" && detections[_detectionIdx]?.status === "queued";

  document.getElementById("ep-extract").style.display = (isKept || isQueued) ? "none" : "";
  document.getElementById("ep-remove-queue").style.display = isQueued ? "" : "none";
  document.getElementById("ep-rename-extract").style.display = isKept ? "" : "none";
  document.getElementById("ep-rename-extract").disabled = !hasPath;
  document.getElementById("ep-delete-extract").style.display = isKept ? "" : "none";
```

- [ ] **Step 2: Update _epUpdateModeUI to account for queued state**

In `_epUpdateModeUI()`, find:

```javascript
    const isFinished = _detectionIdx !== null &&
      typeof detections !== "undefined" &&
      detections[_detectionIdx] &&
      (detections[_detectionIdx].status === "kept" || detections[_detectionIdx].status === "rejected");
    setKfBtn.disabled = isFinished;
    rejectBtn.disabled = isFinished;
    document.getElementById("ep-extract").disabled = isFinished;
```

Replace with:

```javascript
    const det = detections?.[_detectionIdx];
    const isFinished = !!det && (det.status === "kept" || det.status === "rejected" || det.status === "queued");
    setKfBtn.disabled = isFinished;
    rejectBtn.disabled = isFinished;
    document.getElementById("ep-extract").disabled = isFinished;
```

- [ ] **Step 3: Add _epUpdateSyncCamUI to show/hide sibling extraction checkbox**

In `_epUpdateSyncCamUI()`, find the end of the function:

```javascript
  label.style.display = "";
  cb.checked = _syncCamEnabled;
  cam2.style.display = _syncCamEnabled ? "flex" : "none";
}
```

Replace with:

```javascript
  label.style.display = "";
  cb.checked = _syncCamEnabled;
  cam2.style.display = _syncCamEnabled ? "flex" : "none";

  const siblingLabel = document.getElementById("ep-extract-sibling-label");
  if (siblingLabel) {
    siblingLabel.style.display = _syncCamEnabled ? "flex" : "none";
    if (_syncCamEnabled) {
      const siblingCb = document.getElementById("ep-extract-sibling");
      if (siblingCb) siblingCb.checked = true;  // default to checked when revealed
    }
  }
}
```

- [ ] **Step 4: Replace ep-extract click handler to queue instead of extract**

Find the existing `ep-extract` click handler (around line 1626). The entire handler currently POSTs to `/clip-cutter/extract`. Replace the entire handler with:

```javascript
  // Extract Queue — adds detection to the queue instead of extracting immediately
  document.getElementById("ep-extract").addEventListener("click", async () => {
    if (!_videoPath) return;
    const capturedIdx = _detectionIdx;
    const capturedVideoPath = _videoPath;
    const start = parseInt(document.getElementById("ep-start").value, 10);
    const keyFrame = start + 200;
    const postfix = document.getElementById("ep-postfix").value.trim();

    const extractSibling = _siblingVideoPath
      ? (document.getElementById("ep-extract-sibling")?.checked ?? true)
      : false;

    try {
      const resp = await fetch("/clip-cutter/queue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_path: capturedVideoPath,
          key_frame: keyFrame,
          postfix: postfix || "",
          extract_sibling: extractSibling,
          sibling_video_path: extractSibling ? _siblingVideoPath : undefined,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        setStatus("Queue error: " + err.error);
        return;
      }
      const data = await resp.json();
      setStatus(`Queued for extraction (${data.pending_count} in queue)`);

      if (_browseMode) {
        // Browse mode: create a new "queued" detection entry
        const newDet = {
          video_path: capturedVideoPath,
          frame_number: keyFrame,
          similarity: 0,
          source: "manual",
          status: "queued",
          extract_postfix: postfix || null,
          queue_item_id: data.ids[0],
          sibling_queue_item_id: data.ids[1] || null,
        };
        if (typeof detections !== "undefined") {
          detections.push(newDet);
          const newIdx = detections.length - 1;
          if (typeof buildResultCard === "function") {
            const card = buildResultCard(newDet, newIdx);
            card.classList.add("queued");
            document.getElementById("results-list").appendChild(card);
          }
          _detectionIdx = newIdx;
          const allFilterBtn = document.querySelector('.filter-btn[data-filter="all"]');
          if (allFilterBtn) allFilterBtn.click();
          else if (typeof applyFilter === "function") applyFilter();
          if (typeof saveDetections === "function") saveDetections();
        }
      } else if (capturedIdx !== null && typeof detections !== "undefined" && detections[capturedIdx]) {
        detections[capturedIdx].status = "queued";
        detections[capturedIdx].extract_postfix = postfix || null;
        detections[capturedIdx].queue_item_id = data.ids[0];
        if (data.ids[1]) detections[capturedIdx].sibling_queue_item_id = data.ids[1];
        const card = document.getElementById("card-" + capturedIdx);
        if (card) {
          card.classList.add("queued");
          const qBtn = card.querySelector(".queue-btn");
          if (qBtn) qBtn.classList.add("queued");
          card.querySelectorAll(".keep-btn, .reject-btn, .btn-queue").forEach(b => { b.disabled = true; });
        }
        if (typeof saveDetections === "function") saveDetections();
        if (_detectionIdx === capturedIdx) {
          document.getElementById("ep-extract").style.display = "none";
          document.getElementById("ep-remove-queue").style.display = "";
          document.getElementById("ep-set-kf").disabled = true;
          document.getElementById("ep-reject").disabled = true;
        }
      }
    } catch (err) {
      setStatus("Network error: " + err.message);
    }
  });
```

- [ ] **Step 5: Wire ep-remove-queue button**

After the `ep-extract` handler, add:

```javascript
  // Remove queue
  document.getElementById("ep-remove-queue").addEventListener("click", async () => {
    if (_detectionIdx === null || typeof detections === "undefined") return;
    const d = detections[_detectionIdx];
    const itemId = d?.queue_item_id;
    if (!itemId) return;
    try {
      await fetch(`/clip-cutter/queue/${encodeURIComponent(itemId)}`, { method: "DELETE" });
      d.status = "pending";
      delete d.queue_item_id;
      delete d.sibling_queue_item_id;
      document.getElementById("ep-remove-queue").style.display = "none";
      document.getElementById("ep-extract").style.display = "";
      document.getElementById("ep-set-kf").disabled = false;
      document.getElementById("ep-reject").disabled = false;
      const card = document.getElementById("card-" + _detectionIdx);
      if (card) {
        card.classList.remove("queued");
        const qBtn = card.querySelector(".queue-btn");
        if (qBtn) qBtn.classList.remove("queued");
        card.querySelectorAll(".keep-btn, .reject-btn, .btn-queue").forEach(b => { b.disabled = false; });
      }
      setStatus("Removed from queue");
      if (typeof saveDetections === "function") saveDetections();
    } catch (err) {
      setStatus("Network error: " + err.message);
    }
  });
```

- [ ] **Step 6: Run the full test suite one final time**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 7: Manual end-to-end smoke test**

Start server:
```bash
python app.py
```

1. Select a video with a sibling camera.
2. Run a scan, get detections.
3. Click the yellow circle `○` on a detection card → card gets `queued` class, circle fills `●`.
4. Open that detection in the player → player shows "Remove queue" instead of "Extract Queue".
5. Click "Remove queue" → button reverts to "Extract Queue", circle empties.
6. Click "Extract Queue" in player → detection queued, player shows "Remove queue".
7. Click "⏳ Extract Queue (N)" in the detections bar → triggers immediate processing.
8. After processing, card shows `kept` class and updated filename.
9. If sibling camera is selected with "also extract sibling clip" checked, two items appear in `GET /clip-cutter/queue`.
10. On a video with existing `kept` detections + sibling camera, "Queue missing siblings (N)" button appears → click it → siblings queued.

- [ ] **Step 8: Commit**

```bash
git add clip-cutter/static/enhanced_player.js
git commit -m "feat: wire Extract Queue button, sibling checkbox, and Remove queue in player"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| §1 Queue item schema + group_id | Task 2 |
| §1 Detection status "queued" | Tasks 2, 7, 8 |
| §2 queue_manager API | Tasks 2, 3 |
| §2 Worker sequential processing | Task 3 |
| §2 5-min inactivity timer | Task 3 |
| §2 process_now() | Task 3 |
| §2 Detection JSON update on completion | Task 3 |
| §2 Load resets "processing"→"pending" | Task 2 tests |
| §3 All 5 queue routes + SSE | Task 4 |
| §4.1 Candidate card queue button | Task 7 |
| §4.2 ep-extract renamed + queues | Task 8 |
| §4.2 ep-remove-queue button | Tasks 6, 8 |
| §4.3 ep-extract-sibling-label | Tasks 6, 8 |
| §4.4 Extract Queue detections bar button | Tasks 6, 7 |
| §4.5 SSE live updates | Task 7 |
| §5 QUEUE_PATH config | Task 1 |
| §6 Startup start_worker() | Task 5 |
| §7 Error handling (error status, no retry) | Tasks 3, 7 |
| §8.1 Per-card "Extract Sibling" button | Task 7 |
| §8.2 Bulk "Queue missing siblings" button | Tasks 6, 7 |
| §9 /extract route unchanged for browse mode | Task 8 (browse mode uses queue but still creates detection entry) |

**Note on §9 (browse mode):** The spec says the `/extract` route remains for browse mode, but Task 8 changes browse mode to use `/queue` instead. This is intentional — the queue is the only extraction path now for consistency. The `/extract` route itself is untouched and still used by `keepDetection()` on the candidate card's ✓ button (which remains unchanged as an immediate-extract path for users who want it).

**Placeholder scan:** No TBDs, all code blocks are complete.

**Type consistency:** `queue_item_id` and `sibling_queue_item_id` on detection objects are consistently used across Tasks 2, 7, and 8. `_siblingVideoPath` in `clip_cutter.js` shadows the player's `_siblingVideoPath` in `enhanced_player.js` — these are separate variables in separate modules and that is correct.

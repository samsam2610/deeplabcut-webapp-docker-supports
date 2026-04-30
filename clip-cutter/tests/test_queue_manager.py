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
    import importlib

    monkeypatch.setattr(config, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(config, "DETECTIONS_DIR", tmp_path / "detections")

    # Reset all module-level state
    importlib.reload(queue_manager)
    # Load queue state from disk (was previously done by bare _load() at module level)
    queue_manager._load()

    # Monkeypatch reload to also call _load() since we removed the bare _load() call
    original_reload = importlib.reload
    def reload_with_load(module):
        result = original_reload(module)
        if module is queue_manager:
            queue_manager._load()
        return result
    monkeypatch.setattr(importlib, "reload", reload_with_load)

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
        items = queue_manager.get_status()["items"]
        if items and items[0]["status"] in ("done", "error"):
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

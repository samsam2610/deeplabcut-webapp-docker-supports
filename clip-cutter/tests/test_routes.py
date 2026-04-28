import sys
import json
import pytest
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask test client with patched paths and mocked CLIP model."""
    import config
    import processor

    monkeypatch.setattr(config, "TEMPLATE_STATE_PATH", tmp_path / "state.json")

    rng = np.random.default_rng(42)

    class FakeModel:
        def encode(self, images, convert_to_numpy=True, batch_size=64, show_progress_bar=False):
            n = len(images) if isinstance(images, list) else 1
            arr = rng.random((n, 512)).astype(np.float32)
            if n == 1:
                return arr[0]
            return arr

    monkeypatch.setattr(processor, "_model", FakeModel())

    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_routes_state():
    """Reset global route state between tests."""
    import routes
    routes._state = {
        "frames": [],
        "mean_embedding": None,
        "dino_mean_embedding": None,
        "video_stem": None,
        "video_parent": None,
    }
    routes._init_status = {"running": False, "error": None}
    routes._batch_init_jobs.clear()
    routes._batch_scan_jobs.clear()
    routes._batch_template_scan_jobs.clear()
    yield
    routes._state = {
        "frames": [],
        "mean_embedding": None,
        "dino_mean_embedding": None,
        "video_stem": None,
        "video_parent": None,
    }
    routes._init_status = {"running": False, "error": None}
    routes._batch_init_jobs.clear()
    routes._batch_scan_jobs.clear()
    routes._batch_template_scan_jobs.clear()


def test_index_returns_200(client):
    resp = client.get("/clip-cutter/")
    assert resp.status_code == 200
    assert b"Clip Cutter" in resp.data


def test_template_get_empty(client):
    resp = client.get("/clip-cutter/template")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["count"] == 0
    assert data["frames"] == []


def test_template_delete_out_of_range(client):
    resp = client.delete("/clip-cutter/template/0")
    assert resp.status_code == 422  # no video selected


def test_videos_route_removed(client):
    resp = client.get("/clip-cutter/videos")
    assert resp.status_code == 404


def test_extract_route_missing_params(client):
    resp = client.post(
        "/clip-cutter/extract",
        json={},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_extract_missing_csv_returns_422(client, tmp_path, monkeypatch):
    import config
    (tmp_path / "fake.avi").touch()  # no .csv alongside it
    monkeypatch.setattr(config, "VIDEO_DIR", tmp_path)
    resp = client.post(
        "/clip-cutter/extract",
        json={"video_path": str(tmp_path / "fake.avi"), "key_frame": 200},
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_fs_ls_lists_dirs_and_avis(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    (tmp_path / "subdir").mkdir()
    (tmp_path / "video.avi").touch()
    (tmp_path / "notes.txt").touch()  # should be excluded
    resp = client.get(f"/clip-cutter/fs/ls?path={tmp_path}")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["path"] == str(tmp_path)
    names = [e["name"] for e in data["entries"]]
    assert "subdir" in names
    assert "video.avi" in names
    assert "notes.txt" not in names


def test_fs_ls_dirs_first(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    (tmp_path / "aaa.avi").touch()
    (tmp_path / "zzz_dir").mkdir()
    resp = client.get(f"/clip-cutter/fs/ls?path={tmp_path}")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    types = [e["type"] for e in data["entries"]]
    # dir before file even though "aaa" < "zzz"
    assert types.index("dir") < types.index("file")


def test_fs_ls_done_badge_when_video_folder_has_clips(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    (tmp_path / "myvid.avi").touch()
    vid_dir = tmp_path / "myvid"
    vid_dir.mkdir()
    (vid_dir / "clip_success.avi").touch()
    resp = client.get(f"/clip-cutter/fs/ls?path={tmp_path}")
    data = json.loads(resp.data)
    entry = next(e for e in data["entries"] if e["name"] == "myvid.avi")
    assert entry["done"] is True


def test_fs_ls_ready_badge_when_no_video_folder(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    (tmp_path / "myvid.avi").touch()
    resp = client.get(f"/clip-cutter/fs/ls?path={tmp_path}")
    data = json.loads(resp.data)
    entry = next(e for e in data["entries"] if e["name"] == "myvid.avi")
    assert entry["done"] is False


def test_fs_ls_default_path_is_data_root(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    resp = client.get("/clip-cutter/fs/ls")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["path"] == str(tmp_path)


def test_fs_ls_nonexistent_path_returns_400(client):
    resp = client.get("/clip-cutter/fs/ls?path=/nonexistent/path/xyz")
    assert resp.status_code == 400


def test_select_video_sets_state(client, tmp_path):
    (tmp_path / "session.avi").touch()
    resp = client.post(
        "/clip-cutter/select-video",
        json={"video_path": str(tmp_path / "session.avi")},
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "count" in data
    assert "has_template" in data


def test_select_video_missing_path_returns_400(client):
    resp = client.post(
        "/clip-cutter/select-video",
        json={},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_select_video_loads_template_if_exists(client, tmp_path, monkeypatch):
    import processor, numpy as np
    stem = "session"
    parent = str(tmp_path)
    template_dir = tmp_path / stem / "template"
    template_dir.mkdir(parents=True)
    # Write a minimal template_state.json
    fake_emb = np.ones(512, dtype=np.float32) / (512 ** 0.5)
    state = {
        "frames": [{"video_path": "/v.avi", "frame_number": 200,
                    "embedding": fake_emb, "thumbnail": "abc"}],
        "mean_embedding": fake_emb,
        "dino_mean_embedding": None,
    }
    processor.save_template_state(state, template_dir / "template_state.json")

    resp = client.post(
        "/clip-cutter/select-video",
        json={"video_path": str(tmp_path / f"{stem}.avi")},
        content_type="application/json",
    )
    data = json.loads(resp.data)
    assert data["count"] == 1
    assert data["has_template"] is True


def _select(client, tmp_path, stem="session"):
    """Helper: select a video so template routes have a path."""
    (tmp_path / f"{stem}.avi").touch()
    client.post(
        "/clip-cutter/select-video",
        json={"video_path": str(tmp_path / f"{stem}.avi")},
        content_type="application/json",
    )


def test_template_get_has_template_false_when_no_file(client, tmp_path):
    _select(client, tmp_path)
    resp = client.get("/clip-cutter/template")
    data = json.loads(resp.data)
    assert data["has_template"] is False


def test_template_clear_deletes_state_and_jpgs(client, tmp_path, monkeypatch):
    import processor, numpy as np
    stem = "session"
    _select(client, tmp_path, stem)
    template_dir = tmp_path / stem / "template"
    template_dir.mkdir(parents=True)
    fake_emb = np.ones(512, dtype=np.float32)
    state = {"frames": [], "mean_embedding": None, "dino_mean_embedding": None}
    state_path = template_dir / "template_state.json"
    processor.save_template_state(state, state_path)
    (template_dir / "frame_0200.jpg").touch()

    resp = client.post("/clip-cutter/template/clear")
    assert resp.status_code == 200
    assert not state_path.exists()
    assert not (template_dir / "frame_0200.jpg").exists()
    assert template_dir.exists()  # folder kept


def test_template_clear_no_video_selected_returns_422(client):
    resp = client.post("/clip-cutter/template/clear")
    assert resp.status_code == 422


def test_template_clear_when_dir_never_existed(client, tmp_path):
    _select(client, tmp_path)
    # No template dir created — just select a video and clear immediately
    resp = client.post("/clip-cutter/template/clear")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["ok"] is True


def test_init_creates_template_folder_even_with_no_clips(client, tmp_path):
    stem = "session"
    _select(client, tmp_path, stem)
    # No clips in the video folder — init should still succeed
    resp = client.post("/clip-cutter/template/init")
    assert resp.status_code == 202
    # Poll until done
    import time
    for _ in range(20):
        time.sleep(0.2)
        status_resp = client.get("/clip-cutter/template/init/status")
        data = json.loads(status_resp.data)
        if not data["running"]:
            break
    assert not data["running"]
    assert data["error"] is None
    template_dir = tmp_path / stem / "template"
    assert template_dir.exists()


def test_init_no_video_selected_returns_422(client):
    resp = client.post("/clip-cutter/template/init")
    assert resp.status_code == 422


def test_init_reads_clips_from_video_folder(client, tmp_path):
    import cv2, numpy as np, time
    stem = "session"
    _select(client, tmp_path, stem)
    # Create a minimal _success AVI in the video-named folder
    vid_dir = tmp_path / stem
    vid_dir.mkdir(exist_ok=True)
    avi_path = vid_dir / "clip_success.avi"
    writer = cv2.VideoWriter(
        str(avi_path), cv2.VideoWriter_fourcc(*"XVID"), 30.0, (64, 64)
    )
    rng = np.random.default_rng(1)
    for _ in range(210):  # need at least 200 frames
        writer.write(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8))
    writer.release()

    resp = client.post("/clip-cutter/template/init")
    assert resp.status_code == 202
    for _ in range(30):
        time.sleep(0.3)
        data = json.loads(client.get("/clip-cutter/template/init/status").data)
        if not data["running"]:
            break
    assert data["count"] == 1
    assert (tmp_path / stem / "template" / "template_state.json").exists()


def test_check_keyframe_overlap_missing_video_path(client):
    resp = client.post("/clip-cutter/check-keyframe-overlap",
                       json={"key_frame": 500})
    assert resp.status_code == 400


def test_check_keyframe_overlap_no_clips_dir(client, tmp_path):
    video_path = str(tmp_path / "test_video.avi")
    resp = client.post("/clip-cutter/check-keyframe-overlap",
                       json={"video_path": video_path, "key_frame": 500})
    assert resp.status_code == 200
    assert resp.get_json()["overlaps"] is False


def test_check_keyframe_overlap_no_overlap(client, tmp_path):
    clips_dir = tmp_path / "test_video"
    clips_dir.mkdir()
    # clip: start=300 (0-based) → kf=500, range [300, 1099]
    (clips_dir / "test_video_300_899_success.avi").touch()
    video_path = str(tmp_path / "test_video.avi")
    # new KF=2000, range [1800, 2599] — no overlap
    resp = client.post("/clip-cutter/check-keyframe-overlap",
                       json={"video_path": video_path, "key_frame": 2000})
    assert resp.status_code == 200
    assert resp.get_json()["overlaps"] is False


def test_check_keyframe_overlap_with_conflict(client, tmp_path):
    clips_dir = tmp_path / "test_video"
    clips_dir.mkdir()
    # clip: start=300 (0-based) → kf=500, range [300, 1099]
    (clips_dir / "test_video_300_899_success.avi").touch()
    video_path = str(tmp_path / "test_video.avi")
    # new KF=600, range [400, 1199] — overlaps [300,1099] by min(1199,1099)-max(400,300)+1 = 700
    resp = client.post("/clip-cutter/check-keyframe-overlap",
                       json={"video_path": video_path, "key_frame": 600})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["overlaps"] is True
    assert len(data["conflicts"]) == 1
    assert data["conflicts"][0]["name"] == "test_video_300_899_success.avi"
    assert data["conflicts"][0]["overlap_frames"] == 700


def test_csv_returns_rows(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    csv_file = tmp_path / "video.csv"
    csv_file.write_text(
        "timestamp,frame_number,frame_line_status,note\n"
        "0.0,1,14,start_reaching\n"
        "0.067,2,0,\n"
    )
    resp = client.get(f"/clip-cutter/csv?path={csv_file}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["rows"]) == 2
    assert data["rows"][0] == {"frame_number": 1, "frame_line_status": "14", "note": "start_reaching"}
    assert data["rows"][1] == {"frame_number": 2, "frame_line_status": "0", "note": ""}


def test_csv_missing_file_returns_404(client, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path)
    resp = client.get(f"/clip-cutter/csv?path={tmp_path / 'nonexistent.csv'}")
    assert resp.status_code == 404


def test_csv_path_outside_data_root_returns_403(client, tmp_path, monkeypatch):
    import config
    # data root is a subdir; request is to the parent — outside root
    monkeypatch.setattr(config, "_DATA_ROOT", tmp_path / "subdir")
    resp = client.get(f"/clip-cutter/csv?path={tmp_path / 'video.csv'}")
    assert resp.status_code == 403


def test_csv_blank_path_returns_400(client):
    resp = client.get("/clip-cutter/csv")
    assert resp.status_code == 400


def test_load_libraries_returns_empty_when_missing(tmp_path, monkeypatch):
    import config
    import routes
    monkeypatch.setattr(config, "LIBRARIES_PATH", tmp_path / "libraries.json")
    assert routes._load_libraries() == {}


def test_save_and_load_libraries_roundtrip(tmp_path, monkeypatch):
    import config
    import routes
    monkeypatch.setattr(config, "LIBRARIES_PATH", tmp_path / "libraries.json")
    libs = {"TestLib": ["/user-data/session1", "/user-data/session2"]}
    routes._save_libraries(libs)
    assert routes._load_libraries() == libs


@pytest.fixture
def lib_client(tmp_path, monkeypatch):
    """Flask test client with patched LIBRARIES_PATH."""
    import config
    import processor
    monkeypatch.setattr(config, "LIBRARIES_PATH", tmp_path / "libraries.json")
    monkeypatch.setattr(config, "TEMPLATE_STATE_PATH", tmp_path / "state.json")
    rng = np.random.default_rng(42)
    class FakeModel:
        def encode(self, images, convert_to_numpy=True, batch_size=64, show_progress_bar=False):
            n = len(images) if isinstance(images, list) else 1
            arr = rng.random((n, 512)).astype(np.float32)
            return arr[0] if n == 1 else arr
    monkeypatch.setattr(processor, "_model", FakeModel())
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_global_libraries_empty_on_start(lib_client):
    resp = lib_client.get("/clip-cutter/global-libraries")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["libraries"] == {}


def test_create_library(lib_client):
    resp = lib_client.post("/clip-cutter/global-libraries", json={"name": "TestLib"})
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["ok"] is True
    resp2 = lib_client.get("/clip-cutter/global-libraries")
    assert "TestLib" in json.loads(resp2.data)["libraries"]


def test_create_library_duplicate_returns_422(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "TestLib"})
    resp = lib_client.post("/clip-cutter/global-libraries", json={"name": "TestLib"})
    assert resp.status_code == 422


def test_create_library_empty_name_returns_422(lib_client):
    resp = lib_client.post("/clip-cutter/global-libraries", json={"name": ""})
    assert resp.status_code == 422


def test_delete_library(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "ToDelete"})
    resp = lib_client.delete("/clip-cutter/global-libraries/ToDelete")
    assert resp.status_code == 200
    data = json.loads(lib_client.get("/clip-cutter/global-libraries").data)
    assert "ToDelete" not in data["libraries"]


def test_delete_missing_library_returns_404(lib_client):
    resp = lib_client.delete("/clip-cutter/global-libraries/NoSuchLib")
    assert resp.status_code == 404


def test_add_folder_to_library(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "Lib"})
    resp = lib_client.post(
        "/clip-cutter/global-libraries/Lib/folders",
        json={"path": "/user-data/session1"},
    )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["count"] == 1
    libs = json.loads(lib_client.get("/clip-cutter/global-libraries").data)["libraries"]
    assert "/user-data/session1" in libs["Lib"]


def test_add_duplicate_folder_returns_422(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "Lib"})
    lib_client.post("/clip-cutter/global-libraries/Lib/folders", json={"path": "/p"})
    resp = lib_client.post("/clip-cutter/global-libraries/Lib/folders", json={"path": "/p"})
    assert resp.status_code == 422


def test_remove_folder_from_library(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "Lib"})
    lib_client.post("/clip-cutter/global-libraries/Lib/folders", json={"path": "/p"})
    resp = lib_client.delete("/clip-cutter/global-libraries/Lib/folders", json={"path": "/p"})
    assert resp.status_code == 200
    libs = json.loads(lib_client.get("/clip-cutter/global-libraries").data)["libraries"]
    assert "/p" not in libs["Lib"]


def test_remove_missing_folder_returns_404(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "Lib"})
    resp = lib_client.delete("/clip-cutter/global-libraries/Lib/folders", json={"path": "/nope"})
    assert resp.status_code == 404


def test_remove_folder_empty_path_returns_422(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "Lib"})
    resp = lib_client.delete("/clip-cutter/global-libraries/Lib/folders", json={"path": ""})
    assert resp.status_code == 422


def test_batch_init_requires_videos(lib_client):
    resp = lib_client.post("/clip-cutter/batch-init", json={"videos": []})
    assert resp.status_code == 400


def test_batch_init_returns_job_id(lib_client, monkeypatch, tmp_path):
    import processor
    monkeypatch.setattr(
        processor, "init_template_from_clips_dir",
        lambda clips_dir, state_path, crop=None: {"frames": [], "mean_embedding": None, "dino_mean_embedding": None}
    )
    resp = lib_client.post(
        "/clip-cutter/batch-init",
        json={"videos": [str(tmp_path / "myvid.avi")]},
    )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "job_id" in data


def test_batch_scan_requires_template_dirs(lib_client):
    resp = lib_client.post(
        "/clip-cutter/batch-scan",
        json={"template_dirs": [], "video_paths": ["/user-data/v.avi"]},
    )
    assert resp.status_code == 400


def test_batch_scan_requires_video_paths(lib_client):
    resp = lib_client.post(
        "/clip-cutter/batch-scan",
        json={"template_dirs": ["/some/dir"], "video_paths": []},
    )
    assert resp.status_code == 400


def test_batch_scan_returns_job_id(lib_client, monkeypatch, tmp_path):
    import processor
    monkeypatch.setattr(
        processor, "load_combined_template",
        lambda dirs: {"clip_matrix": None, "dino_matrix": None},
    )
    monkeypatch.setattr(
        processor, "scan_video_multi_template",
        lambda *a, **kw: [],
    )
    resp = lib_client.post(
        "/clip-cutter/batch-scan",
        json={"template_dirs": ["/some/dir"], "video_paths": [str(tmp_path / "v.avi")]},
    )
    assert resp.status_code == 200
    assert "job_id" in json.loads(resp.data)


def test_batch_init_stream_returns_done(lib_client, monkeypatch, tmp_path):
    import processor
    monkeypatch.setattr(
        processor, "init_template_from_clips_dir",
        lambda clips_dir, state_path, crop=None: {"frames": [], "mean_embedding": None, "dino_mean_embedding": None}
    )
    resp = lib_client.post(
        "/clip-cutter/batch-init",
        json={"videos": [str(tmp_path / "myvid.avi")]},
    )
    job_id = json.loads(resp.data)["job_id"]
    import time
    time.sleep(0.2)
    stream_resp = lib_client.get(f"/clip-cutter/batch-init/stream?job_id={job_id}")
    # Read one SSE event
    raw = stream_resp.data.decode()
    events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data:")]
    statuses = {e.get("phase") for e in events}
    assert "done" in statuses


def test_batch_template_scan_missing_template_dirs(client):
    resp = client.post("/clip-cutter/batch-template-scan",
                       json={"video_paths": ["/x/v.avi"], "params": {}})
    assert resp.status_code == 400
    assert b"template_dirs" in resp.data


def test_batch_template_scan_starts_and_streams(client, tmp_path, monkeypatch):
    import routes, numpy as np

    # Patch find_template_candidates to return immediately
    def fake_find(video_path, combined, **kwargs):
        return {
            "candidates": [{"frame_number": 5, "similarity": 0.8, "cluster_id": 0}],
            "curve": [{"frame_number": 0, "similarity": 0.8}],
            "embeddings": np.zeros((1, 512), dtype=np.float32),
        }

    monkeypatch.setattr("processor.find_template_candidates", fake_find)

    # Create a fake template dir with template_state.json
    tdir = tmp_path / "templ"
    tdir.mkdir()
    state_path = tdir / "template_state.json"
    state_path.write_text('{"frames": [{"video_path": "x.avi", "frame_number": 1, "embedding": [], "dino_embedding": [], "thumbnail": ""}]}')

    import processor
    monkeypatch.setattr(processor, "load_combined_template", lambda dirs: {
        "clip_matrix": np.ones((1, 512), dtype=np.float32),
        "dino_matrix": None,
    })

    resp = client.post("/clip-cutter/batch-template-scan", json={
        "template_dirs": [str(tdir)],
        "video_paths": ["/x/v.avi"],
        "params": {"stride": 10, "threshold": 0.7, "n_clusters": 5},
    })
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "job_id" in data

    import time
    time.sleep(0.2)

    # Stream until done
    with client.get(f"/clip-cutter/batch-template-scan/stream?job_id={data['job_id']}",
                    buffered=True) as stream_resp:
        assert stream_resp.status_code == 200


def test_template_frame_add_creates_entry(client, tmp_path, monkeypatch):
    import cv2, json as _json, numpy as np

    # Create a tiny video at a known path inside tmp_path
    video_path = tmp_path / "rat" / "session.avi"
    video_path.parent.mkdir(parents=True)
    out = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    for _ in range(10):
        out.write(np.zeros((48, 64, 3), dtype=np.uint8))
    out.release()

    # Template dir: <video_parent>/<video_stem>/template/
    clips_dir = tmp_path / "rat" / "session"
    tdir = clips_dir / "template"
    tdir.mkdir(parents=True)

    resp = client.post("/clip-cutter/template-frame-add", json={
        "video_path": str(video_path),
        "frame_number": 1,
    })
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["count"] == 1


def test_library_folder_frames_empty(client, tmp_path):
    resp = client.get(f"/clip-cutter/library-folder-frames?path={tmp_path}")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["frames"] == []
    assert data["count"] == 0


def test_library_folder_frames_returns_frames(client, tmp_path):
    import json as _json, numpy as np

    state_path = tmp_path / "template_state.json"
    state = {
        "frames": [
            {"video_path": "/x/v.avi", "frame_number": 42,
             "embedding": np.zeros(512).tolist(),
             "dino_embedding": np.zeros(384).tolist(),
             "thumbnail": ""},
        ],
        "mean_embedding": np.zeros(512).tolist(),
        "dino_mean_embedding": None,
    }
    state_path.write_text(_json.dumps(state))

    resp = client.get(f"/clip-cutter/library-folder-frames?path={tmp_path}")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["count"] == 1
    assert data["frames"][0]["frame_number"] == 42
    assert data["frames"][0]["video_path"] == "/x/v.avi"


def test_delete_library_folder_frame(client, tmp_path):
    import json as _json, numpy as np

    state_path = tmp_path / "template_state.json"
    state = {
        "frames": [
            {"video_path": "/x/v.avi", "frame_number": 42,
             "embedding": np.zeros(512).tolist(),
             "dino_embedding": np.zeros(384).tolist(),
             "thumbnail": ""},
        ],
        "mean_embedding": np.zeros(512).tolist(),
        "dino_mean_embedding": None,
    }
    state_path.write_text(_json.dumps(state))

    resp = client.delete("/clip-cutter/library-folder-frames",
                         json={"path": str(tmp_path), "frame_number": 42})
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["count"] == 0

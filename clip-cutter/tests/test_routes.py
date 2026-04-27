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
    """Reset global _state and _init_status between tests."""
    import routes
    routes._state = {
        "frames": [],
        "mean_embedding": None,
        "dino_mean_embedding": None,
        "video_stem": None,
        "video_parent": None,
    }
    routes._init_status = {"running": False, "error": None}
    yield
    routes._state = {
        "frames": [],
        "mean_embedding": None,
        "dino_mean_embedding": None,
        "video_stem": None,
        "video_parent": None,
    }
    routes._init_status = {"running": False, "error": None}


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

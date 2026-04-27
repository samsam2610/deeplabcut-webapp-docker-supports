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
    assert resp.status_code == 404


def test_videos_returns_list(client, monkeypatch, tmp_path):
    import config
    (tmp_path / "vid1.avi").touch()
    (tmp_path / "vid2.avi").touch()
    monkeypatch.setattr(config, "VIDEO_DIR", tmp_path)
    resp = client.get("/clip-cutter/videos")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert len(data["videos"]) == 2


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

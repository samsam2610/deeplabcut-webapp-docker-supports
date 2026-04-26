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

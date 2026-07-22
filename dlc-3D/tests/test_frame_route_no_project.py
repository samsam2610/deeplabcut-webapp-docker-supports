"""Regression: GET /dlc-3d/frame must serve an ABSOLUTE /user-data path even with
NO active project.

Bug: the sibling (cam1) tile in browse-folder mode fetches frames from /dlc-3d/frame
with an absolute path, but the route required an active DLC project — so for videos
outside any project the cam1 tile stayed blank (and the 3D mini-cam1 mirrored it).
Fix: absolute /user-data paths need only the sandbox check, not a project.
"""
import pytest
from flask import Flask

from dlc_3d_bp import routes as r


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(r, "_active_project", None, raising=False)   # browse mode
    # Frame extraction is mocked — we're testing the gate, not cv2.
    monkeypatch.setattr(r.viewer, "get_frame_jpeg", lambda p, n: b"\xff\xd8jpeg")
    app = Flask(__name__)
    app.register_blueprint(r.bp)
    app.config["TESTING"] = True
    return app.test_client()


def test_absolute_path_served_without_active_project(client, tmp_path):
    vid = tmp_path / "eggtart-1_cam1_20260701_094411_10.avi"
    vid.write_bytes(b"v")
    resp = client.get("/dlc-3d/frame", query_string={"video": str(vid), "n": 50})
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"


def test_missing_n_still_rejected(client, tmp_path):
    vid = tmp_path / "eggtart-1_cam1_x.avi"
    vid.write_bytes(b"v")
    assert client.get("/dlc-3d/frame", query_string={"video": str(vid)}).status_code == 400


def test_absolute_path_outside_user_data_rejected(client):
    # Sandbox still enforced even without a project.
    resp = client.get("/dlc-3d/frame", query_string={"video": "/etc/passwd", "n": 0})
    assert resp.status_code == 400

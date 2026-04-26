import json
import pytest
from pathlib import Path
from app import create_app
import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DETECTIONS_DIR", tmp_path / "detections")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_detections_404_when_missing(client):
    resp = client.get("/clip-cutter/detections?video=/some/video.avi")
    assert resp.status_code == 404


def test_put_detections_saves_and_get_returns_it(client):
    dets = [{"cv2_pos": 100, "frame_number": 101, "similarity": 0.85,
              "known_match": None, "status": "pending"}]
    resp = client.put(
        "/clip-cutter/detections",
        json={"video_path": "/some/video.avi", "detections": dets},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    resp2 = client.get("/clip-cutter/detections?video=/some/video.avi")
    assert resp2.status_code == 200
    data = resp2.get_json()
    assert data["video_path"] == "/some/video.avi"
    assert len(data["detections"]) == 1
    assert data["detections"][0]["status"] == "pending"


def test_put_detections_overwrites_previous(client):
    dets1 = [{"cv2_pos": 100, "frame_number": 101, "similarity": 0.85,
               "known_match": None, "status": "pending"}]
    dets2 = [{"cv2_pos": 200, "frame_number": 201, "similarity": 0.90,
               "known_match": "clip_name", "status": "kept"}]
    client.put("/clip-cutter/detections",
               json={"video_path": "/v.avi", "detections": dets1})
    client.put("/clip-cutter/detections",
               json={"video_path": "/v.avi", "detections": dets2})
    resp = client.get("/clip-cutter/detections?video=/v.avi")
    data = resp.get_json()
    assert len(data["detections"]) == 1
    assert data["detections"][0]["status"] == "kept"


def test_get_detections_missing_video_param(client):
    resp = client.get("/clip-cutter/detections")
    assert resp.status_code == 400


def test_put_detections_missing_body_fields(client):
    resp = client.put("/clip-cutter/detections", json={"video_path": "/v.avi"})
    assert resp.status_code == 400

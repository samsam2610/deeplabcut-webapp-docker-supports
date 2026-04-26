import json
import pytest
import cv2
import numpy as np
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


@pytest.fixture
def synthetic_avi(tmp_path):
    """30-frame 64×64 MJPEG AVI with varying blue channel so frames differ."""
    path = tmp_path / "test.avi"
    out = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        30.0,
        (64, 64),
    )
    for i in range(30):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[:, :, 0] = i * 8
        out.write(frame)
    out.release()
    return path


def test_frame_returns_jpeg(client, synthetic_avi):
    resp = client.get(f"/clip-cutter/frame?video={synthetic_avi}&n=0")
    assert resp.status_code == 200
    assert resp.content_type == "image/jpeg"
    assert len(resp.data) > 100


def test_frame_404_for_missing_file(client):
    resp = client.get("/clip-cutter/frame?video=/nonexistent.avi&n=0")
    assert resp.status_code == 404


def test_frame_304_on_etag_match(client, synthetic_avi):
    resp1 = client.get(f"/clip-cutter/frame?video={synthetic_avi}&n=0")
    etag = resp1.headers.get("ETag")
    assert etag is not None
    resp2 = client.get(
        f"/clip-cutter/frame?video={synthetic_avi}&n=0",
        headers={"If-None-Match": etag},
    )
    assert resp2.status_code == 304


def test_frame_missing_params(client):
    assert client.get("/clip-cutter/frame?video=/v.avi").status_code == 400
    assert client.get("/clip-cutter/frame?n=0").status_code == 400


def test_video_info_returns_frame_count_and_fps(client, synthetic_avi):
    resp = client.get(f"/clip-cutter/video-info?video={synthetic_avi}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["frame_count"] == 30
    assert abs(data["fps"] - 30.0) < 1.0


def test_video_info_404_for_missing_file(client):
    resp = client.get("/clip-cutter/video-info?video=/nonexistent.avi")
    assert resp.status_code == 404


def test_video_info_missing_param(client):
    assert client.get("/clip-cutter/video-info").status_code == 400

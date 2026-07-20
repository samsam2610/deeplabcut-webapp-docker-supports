"""Route test for POST /dlc-3d/anipose/init (Phase 1 — scaffold anipose layout).

See docs/superpowers/specs/2026-07-20-inline-3d-triangulate-anipose-init-design.md.
The route copies calibration.toml + detection(s).pickle into calibration/ and each
cam's <stem>_analyzed.h5/.csv into pose-2d/, all confined to the cam0 folder.
"""
import json

import pytest
from flask import Flask

from dlc_3d_bp import routes as r


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Sandbox the /user-data guard onto our tmp dir so absolute paths validate.
    monkeypatch.setattr(r, "_USER_DATA_ROOT", str(tmp_path))
    app = Flask(__name__)
    app.register_blueprint(r.bp)
    app.config["TESTING"] = True
    return app.test_client()


def _folder(tmp_path):
    """Create a stereo recording folder with both cams + calibration inputs."""
    folder = tmp_path / "rec"
    folder.mkdir()
    cam0 = folder / "surv1_cam0_20260123_121732_0.avi"
    cam1 = folder / "surv1_cam1_20260123_121743_0.avi"
    cam0.write_bytes(b"v0")
    cam1.write_bytes(b"v1")
    (folder / "calibration.toml").write_text("[cam_0]\n")
    (folder / "detection.pickle").write_bytes(b"pickle-bytes")
    for cam in (cam0, cam1):
        cam.with_name(cam.stem + "_analyzed.h5").write_bytes(b"h5")
        cam.with_name(cam.stem + "_analyzed.csv").write_text("csv")
    return folder, cam0, cam1


def _post(client, cam0):
    return client.post(
        "/dlc-3d/anipose/init",
        data=json.dumps({"cam0_video": str(cam0)}),
        content_type="application/json",
    )


def test_happy_path_scaffolds_layout(client, tmp_path):
    folder, cam0, cam1 = _folder(tmp_path)
    resp = _post(client, cam0)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()

    calib = folder / "calibration"
    pose = folder / "pose-2d"
    assert calib.is_dir() and pose.is_dir()
    # calibration.toml copied, detection.pickle NORMALIZED to detections.pickle
    assert (calib / "calibration.toml").is_file()
    assert (calib / "detections.pickle").is_file()
    assert not (calib / "detection.pickle").exists()
    # both cams' analyzed files copied with unchanged names
    for cam in (cam0, cam1):
        assert (pose / (cam.stem + "_analyzed.h5")).is_file()
        assert (pose / (cam.stem + "_analyzed.csv")).is_file()

    assert data["warnings"] == []
    assert data["calibration"]["detections.pickle"] == "detections.pickle"
    assert set(data["pose_2d"]["cam0"]) == {
        cam0.stem + "_analyzed.h5", cam0.stem + "_analyzed.csv"}
    assert set(data["pose_2d"]["cam1"]) == {
        cam1.stem + "_analyzed.h5", cam1.stem + "_analyzed.csv"}


def test_detections_pickle_fallback_source(client, tmp_path):
    folder, cam0, cam1 = _folder(tmp_path)
    # Remove singular, provide plural name as the source instead.
    (folder / "detection.pickle").unlink()
    (folder / "detections.pickle").write_bytes(b"plural")
    resp = _post(client, cam0)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert (folder / "calibration" / "detections.pickle").is_file()


def test_overwrites_on_rerun(client, tmp_path):
    folder, cam0, cam1 = _folder(tmp_path)
    assert _post(client, cam0).status_code == 200
    # Change source, re-run, confirm refresh (overwrite) happened.
    (folder / "calibration.toml").write_text("[cam_0]\nchanged=1\n")
    assert _post(client, cam0).status_code == 200
    assert "changed" in (folder / "calibration" / "calibration.toml").read_text()


def test_missing_sibling_400(client, tmp_path):
    folder, cam0, cam1 = _folder(tmp_path)
    cam1.unlink()  # remove the paired camera video
    resp = _post(client, cam0)
    assert resp.status_code == 400
    assert "paired camera" in resp.get_json()["error"]


def test_missing_calibration_toml_400(client, tmp_path):
    folder, cam0, cam1 = _folder(tmp_path)
    (folder / "calibration.toml").unlink()
    resp = _post(client, cam0)
    assert resp.status_code == 400
    assert "calibration.toml" in resp.get_json()["error"]


def test_missing_pickle_400(client, tmp_path):
    folder, cam0, cam1 = _folder(tmp_path)
    (folder / "detection.pickle").unlink()
    resp = _post(client, cam0)
    assert resp.status_code == 400
    assert "pickle" in resp.get_json()["error"].lower()


def test_missing_analyzed_for_one_cam_warns_not_fails(client, tmp_path):
    folder, cam0, cam1 = _folder(tmp_path)
    # Drop cam1's analyzed files entirely.
    cam1.with_name(cam1.stem + "_analyzed.h5").unlink()
    cam1.with_name(cam1.stem + "_analyzed.csv").unlink()
    resp = _post(client, cam0)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    # cam0 still copied
    assert (folder / "pose-2d" / (cam0.stem + "_analyzed.h5")).is_file()
    # cam1 warned, nothing copied
    assert data["pose_2d"]["cam1"] == []
    assert any("cam1" in w for w in data["warnings"])

import json

import pytest

import dlc_3d_bp.routes as routes


@pytest.fixture()
def client():
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    app.config.update(TESTING=True)
    return app.test_client()


def test_run_rejects_paths_outside_user_data(client):
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/etc/passwd", "tgt_h5": "/etc/shadow",
        "calibration": "/etc/hosts", "ref_cam": "cam_0", "tgt_cam": "cam_1",
    })
    assert r.status_code == 403


def test_run_requires_all_arguments(client):
    r = client.post("/dlc-3d/reproject/run", json={"ref_h5": "/user-data/a.h5"})
    assert r.status_code == 400


def test_thresholds_rejects_paths_outside_user_data(client):
    r = client.post("/dlc-3d/reproject/thresholds", json={
        "ref_h5": "/etc/passwd", "tgt_h5": "/etc/shadow",
        "calibration": "/etc/hosts", "ref_cam": "cam_0", "tgt_cam": "cam_1",
    })
    assert r.status_code == 403


def test_audit_rejects_paths_outside_user_data(client):
    r = client.get("/dlc-3d/reproject/audit?tgt_h5=/etc/passwd")
    assert r.status_code == 403


def test_epiline_rejects_paths_outside_user_data(client):
    r = client.get(
        "/dlc-3d/reproject/epiline?ref_h5=/etc/passwd&calibration=/etc/hosts"
        "&ref_cam=cam_0&tgt_cam=cam_1&frame=0&bodypart=Snout"
    )
    assert r.status_code == 403


def test_run_delegates_to_the_engine(client, monkeypatch):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"counts": {"RESCUE": 7}, "outputs": {}, "bodyparts": {}}

    monkeypatch.setattr(routes, "_reproject_run_impl", fake_run)
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/s_cam0_x.h5", "tgt_h5": "/user-data/s_cam1_x.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1", "k1": 2.5,
    })
    assert r.status_code == 200
    assert r.get_json()["counts"]["RESCUE"] == 7
    assert seen["k1"] == 2.5
    assert seen["ref_cam_key"] == "cam_0"

import json
from pathlib import Path

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
    import dlc_3d_bp.reprojection as rp
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"counts": {"RESCUE": 7}, "outputs": {}, "bodyparts": {}}

    monkeypatch.setattr(routes, "_reproject_run_impl", fake_run)
    monkeypatch.setattr(rp, "load_calibration", lambda p: {"cam_0": object(),
                                                           "cam_1": object()})
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/s_cam0_x.h5", "tgt_h5": "/user-data/s_cam1_x.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1", "k1": 2.5,
    })
    assert r.status_code == 200
    assert r.get_json()["counts"]["RESCUE"] == 7
    assert seen["k1"] == 2.5
    assert seen["ref_cam_key"] == "cam_0"


def test_unknown_camera_key_is_400_not_500(client, monkeypatch, tmp_path):
    """A camera key absent from the calibration must be a clean 400, not an
    uncaught KeyError surfacing as a 500."""
    import dlc_3d_bp.reprojection as rp

    monkeypatch.setattr(routes, "_safe_user_data_path", lambda raw: tmp_path / "x")
    monkeypatch.setattr(rp, "load_calibration", lambda p: {"cam_0": object(),
                                                          "cam_1": object()})
    r = client.post("/dlc-3d/reproject/thresholds", json={
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_9", "tgt_cam": "cam_1",
    })
    assert r.status_code == 400
    assert "cam_9" in r.get_json()["error"]


def test_run_accepts_per_camera_dicts(client, monkeypatch, tmp_path):
    import dlc_3d_bp.reprojection as rp
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"counts": {}, "outputs": {}, "bodyparts": {}, "config": {}}

    monkeypatch.setattr(routes, "_reproject_run_impl", fake_run)
    monkeypatch.setattr(rp, "load_calibration", lambda p: {"cam_0": object(),
                                                           "cam_1": object()})
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/a_cam1_x.h5", "tgt_h5": "/user-data/a_cam0_x.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_1", "tgt_cam": "cam_0",
        "gate_ref": {"cam_0": 0.4, "cam_1": 0.7},
        "rescue_floor": {"cam_0": 0.77, "cam_1": 0.95},
    })
    assert r.status_code == 200
    assert seen["gate_ref"] == {"cam_0": 0.4, "cam_1": 0.7}
    assert seen["rescue_floor"] == {"cam_0": 0.77, "cam_1": 0.95}
    # Unsupplied parameters must not be coerced to something the engine can't
    # tell apart from "use the default".
    assert seen["low_tgt"] in (None, 0.6)


def test_run_maps_missing_source_layer_to_400_not_500(client, monkeypatch):
    """_normalize_reproject_input raises FileNotFoundError when a selected
    layer is a reprojection output whose un-reprojected source is gone — that
    must surface as a clean 400, not an uncaught 500."""
    import dlc_3d_bp.reprojection as rp

    def fake_run(**kwargs):
        raise FileNotFoundError(
            "/user-data/s_cam0_x_reprojected.h5 is a reprojection output; "
            "its source /user-data/s_cam0_x.h5 does not exist"
        )

    monkeypatch.setattr(routes, "_reproject_run_impl", fake_run)
    monkeypatch.setattr(rp, "load_calibration", lambda p: {"cam_0": object(),
                                                           "cam_1": object()})
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/s_cam0_x_reprojected.h5",
        "tgt_h5": "/user-data/s_cam1_x_reprojected.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1",
    })
    assert r.status_code == 400
    assert "s_cam0_x_reprojected.h5" in r.get_json()["error"]
    assert "s_cam0_x.h5" in r.get_json()["error"]


def test_run_rejects_out_of_range_value(client, monkeypatch, tmp_path):
    import dlc_3d_bp.reprojection as rp
    monkeypatch.setattr(rp, "load_calibration",
                        lambda p: {"cam_0": object(), "cam_1": object()})
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1",
        "gate_ref": {"cam_0": 1.7},
    })
    assert r.status_code == 400
    assert "gate_ref" in r.get_json()["error"]


def test_run_rejects_unknown_camera_in_a_parameter(client, monkeypatch):
    import dlc_3d_bp.reprojection as rp
    monkeypatch.setattr(rp, "load_calibration",
                        lambda p: {"cam_0": object(), "cam_1": object()})
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1",
        "high_conf": {"cam_9": 0.8},
    })
    assert r.status_code == 400
    assert "cam_9" in r.get_json()["error"]


def test_non_numeric_k1_is_400_not_500(client, monkeypatch):
    import dlc_3d_bp.reprojection as rp
    monkeypatch.setattr(rp, "load_calibration",
                        lambda p: {"cam_0": object(), "cam_1": object()})
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1",
        "k1": {"cam_0": 3.0},
    })
    assert r.status_code == 400
    assert "k1" in r.get_json()["error"]


def test_run_forwards_the_screen_parameters(client, monkeypatch):
    import dlc_3d_bp.reprojection as rp
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"counts": {}, "bodyparts": {}, "outputs": {}, "peak_screen": None}

    monkeypatch.setattr(routes, "_reproject_run_impl", fake_run)
    monkeypatch.setattr(rp, "load_calibration", lambda p: {"cam_0": object(),
                                                           "cam_1": object()})
    body = {
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1",
        "require_peaks": True, "peak_score_floor": 0.2,
    }
    resp = client.post("/dlc-3d/reproject/run", json=body)
    assert resp.status_code == 200
    assert seen["require_peaks"] is True
    assert seen["peak_score_floor"] == 0.2


def test_run_defaults_the_screen_off(client, monkeypatch):
    import dlc_3d_bp.reprojection as rp
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"counts": {}, "bodyparts": {}, "outputs": {}, "peak_screen": None}

    monkeypatch.setattr(routes, "_reproject_run_impl", fake_run)
    monkeypatch.setattr(rp, "load_calibration", lambda p: {"cam_0": object(),
                                                           "cam_1": object()})
    body = {
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1",
    }
    resp = client.post("/dlc-3d/reproject/run", json=body)
    assert resp.status_code == 200
    assert seen["require_peaks"] is False
    assert seen["peak_score_floor"] == 0.05


def test_run_rejects_an_out_of_range_score_floor(client, monkeypatch):
    import dlc_3d_bp.reprojection as rp
    monkeypatch.setattr(rp, "load_calibration", lambda p: {"cam_0": object(),
                                                           "cam_1": object()})
    resp = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1",
        "peak_score_floor": 1.5,
    })
    assert resp.status_code == 400
    assert "peak_score_floor" in resp.get_json()["error"]


def test_peaks_status_reports_absent_sidecars(client, monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "_safe_user_data_path",
                        lambda raw: tmp_path / Path(raw).name)
    resp = client.get("/dlc-3d/reproject/peaks-status", query_string={
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5"})
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["ref"]["present"] is False and d["tgt"]["present"] is False


def test_peaks_status_reports_a_present_sidecar(client, monkeypatch, tmp_path):
    import numpy as np
    from dlc_3d_bp import peaks_io as pio

    monkeypatch.setattr(routes, "_safe_user_data_path",
                        lambda raw: tmp_path / Path(raw).name)
    dst = pio.peaks_sidecar_path(tmp_path / "b.h5")
    pio.write_peaks_npz(dst, np.array([0, 1], np.int32),
                        np.zeros((2, 1, 2, 2), np.float32),
                        np.zeros((2, 1, 2), np.float32), ["nose"], {"k": 2})
    resp = client.get("/dlc-3d/reproject/peaks-status", query_string={
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5"})
    d = resp.get_json()
    assert d["tgt"]["present"] is True and d["tgt"]["frames"] == 2


def test_peaks_status_refuses_a_path_outside_the_data_root(client):
    resp = client.get("/dlc-3d/reproject/peaks-status", query_string={
        "ref_h5": "/etc/passwd", "tgt_h5": "/etc/passwd"})
    assert resp.status_code == 403

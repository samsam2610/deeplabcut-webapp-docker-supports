"""Route tests for the frame labeler's epipolar-line support.

Style follows tests/test_reproj_panel_wiring.py's sibling route tests: a
minimal Flask app registering only dlc_3d_bp.routes.bp, with the module-level
_active_project set directly. No fixtures from the LP suite are used.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dlc_3d_bp import routes as R  # noqa: E402


# Two cameras 100 mm apart looking down the same axis — enough for a real,
# non-degenerate fundamental matrix. Written as a literal so the test does not
# depend on any calibration file on disk.
CALIB_TOML = """
[cam_0]
name = "0"
size = [ 640, 480,]
matrix = [ [ 600.0, 0.0, 320.0,], [ 0.0, 600.0, 240.0,], [ 0.0, 0.0, 1.0,],]
distortions = [ 0.0, 0.0, 0.0, 0.0, 0.0,]
rotation = [ 0.0, 0.0, 0.0,]
translation = [ 0.0, 0.0, 0.0,]

[cam_1]
name = "1"
size = [ 640, 480,]
matrix = [ [ 600.0, 0.0, 320.0,], [ 0.0, 600.0, 240.0,], [ 0.0, 0.0, 1.0,],]
distortions = [ 0.0, 0.0, 0.0, 0.0, 0.0,]
rotation = [ 0.0, 0.1, 0.0,]
translation = [ -100.0, 0.0, 0.0,]

[metadata]
adjusted = false
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project root with one session folder holding a cam pair."""
    proj = tmp_path / "proj"
    session = proj / "labeled-data" / "sess1"
    session.mkdir(parents=True)
    (session / "img_cam0_0000_00010.png").write_bytes(b"")
    (session / "img_cam1_0000_00010.png").write_bytes(b"")
    monkeypatch.setattr(R, "_active_project", str(proj))
    return proj


@pytest.fixture
def calibrated(project):
    (project / "labeled-data" / "sess1" / "calibration.toml").write_text(CALIB_TOML)
    return project


@pytest.fixture
def client(project):
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(R.bp)
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


def test_labeled_frames_reports_calibration_present(client, calibrated):
    r = client.get("/dlc-3d/labeled-frames?session=sess1")
    body = r.get_json()
    assert body["calibration"]["exists"] is True
    assert body["calibration"]["cams"] == ["cam_0", "cam_1"]


def test_labeled_frames_reports_calibration_absent(client, project):
    r = client.get("/dlc-3d/labeled-frames?session=sess1")
    assert r.get_json()["calibration"] == {"exists": False, "cams": []}


def test_labeled_frames_survives_a_corrupt_calibration(client, project):
    """A broken toml must gate the feature off, not 500 the folder listing —
    the frame list is what the labeler needs to work at all."""
    (project / "labeled-data" / "sess1" / "calibration.toml").write_text("not [ toml")
    r = client.get("/dlc-3d/labeled-frames?session=sess1")
    assert r.status_code == 200
    assert r.get_json()["calibration"]["exists"] is False
    assert len(r.get_json()["frames"]) == 2


def test_labeled_frames_still_lists_frames(client, calibrated):
    """The added field must not disturb the existing contract."""
    body = client.get("/dlc-3d/labeled-frames?session=sess1").get_json()
    assert body["count"] == 2
    assert body["session_folder"] == "labeled-data/sess1"

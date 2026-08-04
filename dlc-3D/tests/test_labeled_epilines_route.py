"""Route tests for the frame labeler's epipolar-line support.

Style follows tests/test_reproj_panel_wiring.py's sibling route tests: a
minimal Flask app registering only dlc_3d_bp.routes.bp, with
_active_project_for_user patched directly. No fixtures from the LP suite are
used.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

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
    monkeypatch.setattr(R, "_active_project_for_user", lambda: str(proj))
    return proj


@pytest.fixture
def calibrated(project):
    (project / "labeled-data" / "sess1" / "calibration.toml").write_text(CALIB_TOML)
    return project


# Same rig as CALIB_TOML, except cam_0 carries a genuinely nonzero radial
# distortion coefficient. Kept as its own literal (not a mutation of
# CALIB_TOML) so Task 2's tests and the other tests in this file, which all
# depend on CALIB_TOML's zero-distortion cameras, are unaffected.
CALIB_TOML_DISTORTED = """
[cam_0]
name = "0"
size = [ 640, 480,]
matrix = [ [ 600.0, 0.0, 320.0,], [ 0.0, 600.0, 240.0,], [ 0.0, 0.0, 1.0,],]
distortions = [ -0.15, 0.0, 0.0, 0.0, 0.0,]
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
def calibrated_distorted(project):
    """A second session (sess2) using CALIB_TOML_DISTORTED.

    A separate session folder — rather than overwriting sess1's
    calibration.toml — lets this fixture be combined with `calibrated` in the
    same test without one write clobbering the other.
    """
    session = project / "labeled-data" / "sess2"
    session.mkdir(parents=True)
    (session / "img_cam0_0000_00010.png").write_bytes(b"")
    (session / "img_cam1_0000_00010.png").write_bytes(b"")
    (session / "calibration.toml").write_text(CALIB_TOML_DISTORTED)
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
    """A calibration.toml that raises inside the parser must gate the feature
    off, not 500 the folder listing — the frame list is what the labeler
    needs to work at all.

    The fixture below has a section header (so the fallback line-parser in
    reprojection._parse_toml actually enters a section) whose value is not a
    valid Python literal: `ast.literal_eval("broken")` raises ValueError.
    A plain unparseable string with no section header (e.g. "not [ toml")
    would NOT exercise this: the fallback parser silently skips lines with no
    "=" and no section, returning {} without ever raising — which is
    indistinguishable from the try/except being deleted entirely.
    """
    (project / "labeled-data" / "sess1" / "calibration.toml").write_text(
        "[cam_0]\nmatrix = broken\n"
    )
    r = client.get("/dlc-3d/labeled-frames?session=sess1")
    assert r.status_code == 200
    assert r.get_json()["calibration"]["exists"] is False
    assert len(r.get_json()["frames"]) == 2


def test_labeled_frames_still_lists_frames(client, calibrated):
    """The added field must not disturb the existing contract."""
    body = client.get("/dlc-3d/labeled-frames?session=sess1").get_json()
    assert body["count"] == 2
    assert body["session_folder"] == "labeled-data/sess1"


def test_labeled_frames_session_key_cannot_escape_the_project(client, calibrated):
    """M8: /labeled-frames lacked the path-escape guard /labeled-epilines has.
    Same guard, same 403, for symmetry between the two session-keyed routes."""
    r = client.get("/dlc-3d/labeled-frames?session=../../etc")
    assert r.status_code == 403


def test_labeled_frames_session_key_cannot_escape_via_lexical_sibling(client, project):
    """Mirrors test_session_key_cannot_escape_via_lexical_sibling for
    /labeled-epilines: str.startswith would be defeated by a lexically
    prefixed sibling directory; the guard must use Path.is_relative_to."""
    (project / "labeled-data-evil").mkdir()
    r = client.get("/dlc-3d/labeled-frames?session=../labeled-data-evil")
    assert r.status_code == 403


def _get(client, **kw):
    kw.setdefault("session", "sess1")
    kw.setdefault("ref_cam", 0)
    kw.setdefault("tgt_cam", 1)
    if isinstance(kw.get("points"), list):
        kw["points"] = json.dumps(kw["points"])
    q = urlencode(kw)
    return client.get(f"/dlc-3d/labeled-epilines?{q}")


def test_returns_one_segment_per_point(client, calibrated):
    r = _get(client, points=[{"bodypart": "wrist", "x": 320, "y": 240},
                             {"bodypart": "paw",   "x": 200, "y": 300}])
    assert r.status_code == 200
    segs = r.get_json()["segments"]
    assert set(segs) == {"wrist", "paw"}
    for seg in segs.values():
        assert seg is None or (len(seg) == 2 and len(seg[0]) == 2)


def test_a_centred_point_yields_a_real_segment(client, calibrated):
    """Not just well-formed — an actual line across the target image. A route
    that returned all-null would satisfy the shape test above."""
    seg = _get(client, points=[{"bodypart": "wrist", "x": 320, "y": 240}]
               ).get_json()["segments"]["wrist"]
    assert seg is not None, "a centred point must project to a visible line"
    (x1, y1), (x2, y2) = seg
    assert (x1 - x2) ** 2 + (y1 - y2) ** 2 > 1.0, "degenerate segment"
    for x, y in seg:
        assert -1e-6 <= x <= 640 + 1e-6
        assert -1e-6 <= y <= 480 + 1e-6


def test_direction_matters(client, calibrated):
    """0->1 and 1->0 are different geometry; a route ignoring the direction
    would return the same line for both."""
    pts = [{"bodypart": "wrist", "x": 300, "y": 200}]
    a = _get(client, ref_cam=0, tgt_cam=1, points=pts).get_json()["segments"]["wrist"]
    b = _get(client, ref_cam=1, tgt_cam=0, points=pts).get_json()["segments"]["wrist"]
    assert a != b


def test_empty_points_is_not_an_error(client, calibrated):
    r = _get(client, points=[])
    assert r.status_code == 200
    assert r.get_json()["segments"] == {}


def test_missing_calibration_is_400(client, project):
    r = _get(client, points=[{"bodypart": "wrist", "x": 1, "y": 2}])
    assert r.status_code == 400
    assert "calibration" in r.get_json()["error"].lower()


def test_unknown_camera_index_is_400(client, calibrated):
    r = _get(client, tgt_cam=7, points=[{"bodypart": "wrist", "x": 1, "y": 2}])
    assert r.status_code == 400
    assert "cam_7" in r.get_json()["error"]


def test_same_camera_for_ref_and_target_is_400(client, calibrated):
    """A point's epipolar line in its own image is undefined."""
    r = _get(client, ref_cam=0, tgt_cam=0, points=[{"bodypart": "w", "x": 1, "y": 2}])
    assert r.status_code == 400


def test_malformed_points_is_400_not_500(client, calibrated):
    assert client.get(
        "/dlc-3d/labeled-epilines?session=sess1&ref_cam=0&tgt_cam=1&points=notjson"
    ).status_code == 400
    r = _get(client, points=[{"bodypart": "w", "x": "abc", "y": 2}])
    assert r.status_code == 400


def test_session_key_cannot_escape_the_project(client, calibrated):
    r = _get(client, session="../../etc", points=[{"bodypart": "w", "x": 1, "y": 2}])
    assert r.status_code == 403


def test_a_point_whose_line_misses_the_image_is_null_not_missing(client, calibrated):
    """The client keys its draw loop on the bodypart, so an omitted key and a
    null mean different things — a dropped key would be read as 'not computed'."""
    segs = _get(client, points=[{"bodypart": "wrist", "x": 1e9, "y": 1e9}]
                ).get_json()["segments"]
    assert "wrist" in segs
    assert segs["wrist"] is None


def test_session_key_cannot_escape_via_lexical_sibling(client, project):
    """str(path).startswith(str(root)) is not a containment check: a sibling
    directory whose name is lexically prefixed by 'labeled-data' (e.g.
    'labeled-data-evil') would defeat it, because the resolved path's string
    form starts with the root's string form even though the directory sits
    outside labeled-data/. The guard must compare path segments
    (Path.is_relative_to), not characters.
    """
    (project / "labeled-data-evil").mkdir()
    r = _get(client, session="../labeled-data-evil",
             points=[{"bodypart": "w", "x": 1, "y": 2}])
    assert r.status_code == 403


def test_undistort_is_applied_not_skipped(client, calibrated, calibrated_distorted):
    """undistort_to_pixels is not optional (route docstring: fundamental_matrix
    acts on undistorted pixel coordinates). CALIB_TOML's cameras carry zero
    distortion, so a route that dropped the undistort_to_pixels call entirely
    and fed raw pixels straight into epiline_endpoints would still pass every
    other test in this file. Only a nonzero-distortion camera exposes that.
    """
    pts = [{"bodypart": "wrist", "x": 300, "y": 150}]
    zero = _get(client, session="sess1", points=pts).get_json()["segments"]["wrist"]
    distorted = _get(client, session="sess2", points=pts).get_json()["segments"]["wrist"]
    assert zero != distorted

"""Static wiring guards for the composite 3D-view controls + filters.

See docs/superpowers/specs/2026-07-21-inline-3d-composite-viewer-controls-filters-design.md.
- pose3d_viewer.js exposes zoomBy / orbit / setThresholds / getErrorMax and stores
  scores / errors / error_max.
- inline_analysis_3d.js mirrors getTile(...).imgEl.src into the mini-cams, wires the
  on-screen control buttons + threshold sliders, and POSTs the refilter route on Apply.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
INLINE = STATIC / "inline_analysis_3d.js"
VIEWER = STATIC / "pose3d_viewer.js"


# ── pose3d_viewer.js ─────────────────────────────────────────────────────────

def test_viewer_exposes_new_methods():
    s = VIEWER.read_text()
    for fn in ("zoomBy", "orbit", "setThresholds", "getErrorMax"):
        assert re.search(rf'function\s+{fn}\b', s), f"pose3d_viewer must define {fn}"
    # Returned handle lists the new API alongside the originals (the return whose
    # object literal carries the init/load/showFrame surface).
    m = re.search(r'return\s*\{([^}]*\binit\b[^}]*\bshowFrame\b[^}]*)\}', s)
    assert m, "makePose3dViewer must return a handle object"
    handle = m.group(1)
    for fn in ("zoomBy", "orbit", "setThresholds", "getErrorMax"):
        assert fn in handle, f"handle must expose {fn}"


def test_viewer_stores_scores_errors_error_max():
    s = VIEWER.read_text()
    assert "data.scores" in s, "load() must read data.scores"
    assert "data.errors" in s, "load() must read data.errors"
    assert "data.error_max" in s, "load() must read data.error_max"


def test_viewer_orbit_uses_spherical_with_clamp():
    s = VIEWER.read_text()
    assert "THREE.Spherical" in s, "orbit must build a THREE.Spherical from the offset"
    assert "Math.PI" in s, "orbit must clamp the polar angle near PI"


def test_viewer_showframe_gates_on_thresholds():
    s = VIEWER.read_text()
    assert "scoreThr" in s and "errThr" in s, \
        "showFrame must gate joints on the score/error thresholds"


# ── inline_analysis_3d.js ────────────────────────────────────────────────────

def test_inline_mirrors_tiles_into_mini_cams():
    s = INLINE.read_text()
    assert "getTile(" in s, "must read the main viewer tiles"
    assert ".imgEl" in s, "must mirror the tile's imgEl into the mini-cam"
    assert "ia3d-pose3d-cam0" in s and "ia3d-pose3d-cam1" in s, \
        "must target both mini-cam imgs"


def test_inline_mirror_called_on_framechange():
    s = INLINE.read_text()
    m = re.search(r'\.on\("frameChange",\s*\(n\)\s*=>\s*\{(.+?)\}\)', s, re.DOTALL)
    assert m, "expected a frameChange handler taking (n)"
    body = m.group(1)
    assert "_mirrorPose3dCams" in body, \
        "frameChange handler must mirror the mini-cams"


def test_inline_wires_control_buttons():
    s = INLINE.read_text()
    for bid in (
        "ia3d-pose3d-home",
        "ia3d-pose3d-zoom-in",
        "ia3d-pose3d-zoom-out",
        "ia3d-pose3d-orbit-left",
        "ia3d-pose3d-orbit-right",
        "ia3d-pose3d-orbit-up",
        "ia3d-pose3d-orbit-down",
    ):
        assert bid in s, f"control button #{bid} must be wired"
    assert "zoomBy(" in s, "zoom buttons must call zoomBy"
    assert "orbit(" in s, "orbit d-pad must call orbit"


def test_inline_wires_threshold_sliders():
    s = INLINE.read_text()
    assert "ia3d-pose3d-score-thr" in s and "ia3d-pose3d-error-thr" in s
    assert "setThresholds(" in s, "sliders must call setThresholds"


def test_inline_posts_refilter_on_apply():
    s = INLINE.read_text()
    assert "ia3d-pose3d-apply" in s, "the Apply button must be wired"
    assert "/dlc/project/triangulate/refilter" in s, "Apply must POST the refilter route"
    assert "offset_threshold" in s, "refilter POST body must carry offset_threshold"
    assert "medfilt" in s, "refilter POST body must carry medfilt"


def test_inline_configures_error_slider_from_error_max():
    s = INLINE.read_text()
    assert "getErrorMax" in s, "wiring must read the viewer's error_max to size the slider"

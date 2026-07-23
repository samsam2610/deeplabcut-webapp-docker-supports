"""Static wiring guards for the composite 3D-view controls + filters.

See docs/superpowers/specs/2026-07-21-inline-3d-composite-viewer-controls-filters-design.md.
- pose3d_viewer.js exposes zoomBy / orbit / setThresholds / getErrorMax and stores
  scores / errors / error_max.
- inline_analysis_3d.js composites getTile(...).imgEl + .canvasEl into the mini-cam
  <canvas>es on a rAF loop, wires the on-screen control buttons + threshold sliders,
  and POSTs the refilter route on Apply.
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
    # Composite = frame image (imgEl) + marker overlay canvas (canvasEl), both drawn.
    assert ".imgEl" in s, "must composite the tile's frame img (imgEl)"
    assert ".canvasEl" in s, "must composite the tile's marker overlay (canvasEl)"
    assert "drawImage" in s, "must draw the frame + overlay into the mini-cam canvas"
    assert "ia3d-pose3d-cam0" in s and "ia3d-pose3d-cam1" in s, \
        "must target both mini-cam canvases"


def test_inline_mirror_runs_raf_loop():
    """A continuous rAF loop drives the mirror while the panel is open (source of
    truth over the async frame/overlay), and is cancelled on close/dispose."""
    s = INLINE.read_text()
    assert "requestAnimationFrame" in s, "mini-cam mirror must run on a rAF loop"
    assert "cancelAnimationFrame" in s, "mirror loop must be cancellable (no leak)"


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


# ── Adjustable 3D marker size ────────────────────────────────────────────────

def test_viewer_exposes_set_marker_size():
    s = VIEWER.read_text()
    assert re.search(r'function\s+setMarkerSize\b', s), \
        "pose3d_viewer must define setMarkerSize"
    # Scales the sphere meshes (no geometry rebuild).
    assert "spheres.forEach" in s and "scale.setScalar" in s, \
        "setMarkerSize/load must scale the sphere meshes via scale.setScalar"
    m = re.search(r'return\s*\{([^}]*\binit\b[^}]*\bshowFrame\b[^}]*)\}', s)
    assert m and "setMarkerSize" in m.group(1), \
        "handle must expose setMarkerSize"


def test_inline_wires_marker_size_slider():
    s = INLINE.read_text()
    assert "ia3d-pose3d-marker-size" in s, "marker-size slider must be wired"
    assert "setMarkerSize(" in s, "marker-size slider must call setMarkerSize"


def test_inline_sizes_3d_container_via_view_inputs():
    """The 3D viewer box is sized by the view width/height number fields
    (#ia3d-pose3d-view-w/-h → _applyPose3dViewSize → #ia3d-pose3d-canvas-box), NOT
    auto-capped to the camera width by the mirror loop (that clobbered the width
    control every tick — see the width-clobber fix)."""
    s = INLINE.read_text()
    assert "ia3d-pose3d-canvas-box" in s, "the canvas box is the sized element"
    assert "_applyPose3dViewSize" in s, "view width/height must drive the box size"
    assert not re.search(r'container\.style\.(width|maxWidth)\s*=\s*camW', s), \
        "the mirror loop must not cap the container to the camera width"


def test_inline_triangulate_redraw_not_toggle_gated():
    """Adjustment 3: the 3D-coverage bar is always visible, so its redraw must NOT
    gate on the Triangulate toggle being checked."""
    s = INLINE.read_text()
    m = re.search(r'_redrawTriangulateCoverage\s*=\s*\(\)\s*=>\s*\{(.+?)\};', s, re.DOTALL)
    assert m, "expected the _redrawTriangulateCoverage assignment"
    assert "ia3d-triangulate-toggle" not in m.group(1), \
        "_redrawTriangulateCoverage must not gate on the triangulate toggle"

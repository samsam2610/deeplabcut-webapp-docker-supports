"""Static wiring guards for the 3D pose viewer (three.js spike).

See docs/superpowers/specs/2026-07-21-inline-3d-pose-viewer-threejs-spike-design.md.
- inline_analysis_3d.js imports pose3d_viewer.js, fetches the frozen
  /dlc/project/triangulate/poses-3d contract, and drives showFrame from a
  frameChange subscription.
- pose3d_viewer.js keeps three.js fully isolated: it imports the vendored three
  + OrbitControls and exports makePose3dViewer with init/load/showFrame/resetView.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
INLINE = STATIC / "inline_analysis_3d.js"
VIEWER = STATIC / "pose3d_viewer.js"


def test_inline_imports_pose3d_viewer():
    s = INLINE.read_text()
    assert re.search(r'import\s*\{\s*makePose3dViewer\s*\}\s*from\s*["\']\./pose3d_viewer\.js["\']', s), \
        "inline_analysis_3d.js must import makePose3dViewer from ./pose3d_viewer.js"


def test_inline_fetches_poses3d_route():
    s = INLINE.read_text()
    assert "/dlc/project/triangulate/poses-3d" in s, \
        "must fetch the poses-3d data route"
    assert "source=filtered" in s, "default 3D source is filtered"


def test_inline_drives_showframe_from_framechange():
    s = INLINE.read_text()
    # A frameChange subscription must call showFrame with the frame number.
    m = re.search(r'\.on\("frameChange",\s*\(n\)\s*=>\s*\{(.+?)\}\)', s, re.DOTALL)
    assert m, "expected a frameChange handler taking (n)"
    assert "showFrame(n)" in m.group(1), \
        "frameChange handler must call pose3d showFrame(n)"


def test_inline_wires_toggle_idempotently_and_reset():
    s = INLINE.read_text()
    assert "_pose3dChromeWired" in s, "must use a module-level idempotent wire guard"
    assert 'ia3d-pose3d-controls"' in s and 'classList.toggle("hidden"' in s, \
        "toggle must reveal/hide #ia3d-pose3d-controls via the hidden class"
    assert "ia3d-pose3d-reset" in s, "reset button must be wired"
    assert re.search(r'resetView\(\)', s), "reset button must call resetView()"


def test_viewer_imports_vendored_three_and_orbitcontrols():
    s = VIEWER.read_text()
    assert re.search(r'from\s*["\']\./vendor/three/three\.module\.js["\']', s), \
        "pose3d_viewer must import the vendored three.module.js"
    assert re.search(r'from\s*["\']\./vendor/three/OrbitControls\.js["\']', s), \
        "pose3d_viewer must import the vendored OrbitControls.js"


def test_viewer_exports_factory_with_handle_api():
    s = VIEWER.read_text()
    assert re.search(r'export\s+function\s+makePose3dViewer', s), \
        "pose3d_viewer must export makePose3dViewer"
    for fn in ("init", "load", "showFrame", "resetView"):
        assert re.search(rf'\b{fn}\b', s), f"handle must expose {fn}"
    # returned handle object lists the API
    assert re.search(r'return\s*\{[^}]*init[^}]*load[^}]*showFrame[^}]*resetView', s), \
        "makePose3dViewer must return { init, load, showFrame, resetView, ... }"

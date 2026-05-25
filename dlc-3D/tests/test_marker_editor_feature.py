"""Static-analysis contract for the MarkerEditor feature module (Phase 3d-ii).

Browser ESM cannot import under Node; enforced by regex over source + code review.
The pure overlay/edit math is node-tested separately (test_viewer_marker_overlay.mjs).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
ME = ROOT / "src" / "static" / "components" / "viewer" / "features" / "marker_editor.js"


def _src():
    assert ME.is_file(), f"missing marker_editor feature at {ME}"
    return ME.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+markerEditor\b", _src()) or \
        re.search(r"export\s*\{[^}]*\bmarkerEditor\b[^}]*\}", _src()), \
        "must export `markerEditor`"


def test_returns_attach():
    assert re.search(r"\battach\s*\(", _src()), "factory result must expose `attach(viewer)`"


@pytest.mark.parametrize("name", [
    "hitTest", "resolvePose", "setEdit", "deleteEdit", "buildMarkerEditPayload",
    "layerThreshold", "poseCacheKey", "prefetchWindow", "allCached", "nudge",
    "nextBodypart", "scaleFor", "markerRadius", "canvasToVideo",
])
def test_imports_overlay_reducer(name):
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*marker_overlay\.mjs[\"']", _src()), \
        f"must import {name} from internal/marker_overlay.mjs (no re-implementation)"


def test_imports_palette_and_shapes():
    src = _src()
    assert re.search(r"import\s*\{[^}]*\bpaletteColor\b[^}]*\}\s*from\s*[\"'][^\"']*palette\.mjs[\"']", src), \
        "must import paletteColor from internal/palette.mjs"
    assert re.search(r"import\s*\{[^}]*\b(drawShape|shapeForLayer)\b[^}]*\}\s*from\s*[\"'][^\"']*shapes\.mjs[\"']", src), \
        "must import draw helpers from internal/shapes.mjs"


@pytest.mark.parametrize("event", ["videoLoad", "frameChange", "drawTile"])
def test_subscribes_hook(event):
    src = _src()
    assert f'"{event}"' in src or f"'{event}'" in src, f'must subscribe to the "{event}" hook'


def test_gates_editing_on_single_layer():
    # editing must be disabled when comparison layers are present
    assert re.search(r"isEditable", _src()), "must gate editing via an isEditable() check"


def test_disposes_on_teardown():
    src = _src()
    assert '"teardown"' in src or "'teardown'" in src, "must subscribe to the viewer 'teardown' hook"


def test_no_hardcoded_endpoints():
    src = _src()
    for bad in ("/dlc-3d/", "/clip-cutter/", "/annotate/", "/dlc/viewer/"):
        assert bad not in src, f"endpoints must be injected, not hardcoded ({bad})"


def test_bp_chips_render_frame_labeler_structure():
    src = (ROOT / "src" / "static" / "components" / "viewer" / "features" / "marker_editor.js").read_text()
    for cls in ("vv-bp-dot", "vv-bp-name", "vv-bp-check", "vv-bp-eye-slash"):
        assert cls in src, f"rebuildBpChips must render a .{cls} element (frame-labeler chip parity)"


def test_b1_render_edit_gate_decoupled_from_overlay():
    """B1: render + edit are gated on `overlayEnabled || editingAllowed`, not
    overlayEnabled alone, so setEditable(true) makes markers render + edits live
    with no overlay toggle. Read-only consumers (no setEditable(true)) keep the
    default editingAllowed=false, so their rendering stays keyed on overlayEnabled."""
    src = _src()
    # the combined gate expression must appear (render + handlers reuse it)
    assert "overlayEnabled || editingAllowed" in src, \
        "render/edit gate must be `overlayEnabled || editingAllowed`"
    # default must be OFF so read-only consumers don't start rendering with overlay off
    assert re.search(r"editingAllowed\s*=\s*false", src), \
        "editingAllowed must default to false (read-only consumers unchanged)"
    # the bare `if (!overlayEnabled) return;` render short-circuit must be gone
    assert "if (!overlayEnabled) return;" not in src, \
        "renderTile must not short-circuit on overlayEnabled alone"


def test_b2_b3_autoadvance_and_lockbp():
    """B2: an `autoAdvance` config (default off) advances selectedBp after a place
    using nextUnlabeledBodypart over (posedBodyparts ∪ frame edits). B3: setLockBp
    state + API; when locked, no advance (re-place same bp)."""
    src = _src()
    # imports the new reducer
    assert re.search(
        r"import\s*\{[^}]*\bnextUnlabeledBodypart\b[^}]*\}\s*from\s*[\"'][^\"']*bodypart_cycle\.mjs[\"']", src), \
        "must import nextUnlabeledBodypart from internal/bodypart_cycle.mjs"
    # autoAdvance read from config, default off
    assert re.search(r"autoAdvance\s*=\s*!!\s*config\.autoAdvance", src) or \
        re.search(r"config\.autoAdvance", src), "must read autoAdvance from config"
    # Lock-BP state + public setter
    assert re.search(r"setLockBp\s*\(", src), "must expose setLockBp(bool)"
    assert "lockBp" in src, "must track lockBp state"
    # the auto-advance call passes the lock flag (so Lock-BP suppresses advance)
    assert "nextUnlabeledBodypart(" in src


def test_b4_b5_hit_select_and_hover_cursor():
    """B4: mousedown hit-tests existing markers and selects on a hit (already
    present; must stay gated on renderActive, not overlayEnabled). B5: a mousemove
    handler updates the focused tile's cursor — pointer over a marker, crosshair
    when a bp is selected + editable, else default."""
    src = _src()
    # B4: hit-test on mousedown selects (selectBp(hit))
    assert re.search(r"hitTest\([^)]*\)[\s;].*selectBp\(hit\)", src, re.S) or \
        "selectBp(hit)" in src, "mousedown must select the hit bodypart"
    # B5: a hover handler that sets the cursor based on a hover hit-test
    assert "mousemove" in src
    # cursor strings used for hover feedback
    for cur in ('"pointer"', '"crosshair"', '"default"'):
        assert cur in src, f"hover cursor logic must use {cur}"
    # a dedicated hover handler name (so the drag mousemove stays separate)
    assert "updateHoverCursor" in src, "must factor a hover-cursor updater"


def test_b6_space_toggles_per_frame_visibility():
    """B6: Space toggles the selected bp's per-frame visibility (a per-(frame,bp)
    store), reflected in render + the `.vv-bp-chip.vis-hidden` chip. Arrows stay
    VideoViewer frame-nav (no arrow handling added here)."""
    src = _src()
    # a per-frame hidden store (distinct from the global hiddenParts Set)
    assert "hiddenByFrame" in src, "must track per-frame visibility (hiddenByFrame)"
    # Space key handled in the keyboard handler
    assert re.search(r'e\.key\s*===\s*"\s"', src) or 'e.key === " "' in src, \
        "Space (' ') must be handled for visibility toggle"
    # the union helper that render + chips consult
    assert "isHiddenAt" in src, "must factor an isHiddenAt(frame, bp) union helper"
    # arrows are NOT intercepted (frame-nav stays VideoViewer's)
    assert "ArrowLeft" not in src and "ArrowRight" not in src, \
        "markerEditor must not intercept arrow keys (frame-nav is VideoViewer's)"

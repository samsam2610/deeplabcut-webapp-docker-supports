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


def test_hidden_by_frame_cleared_on_videoload():
    """Cleanup (2026-05-24): the per-frame visibility map (hiddenByFrame, Space
    toggle) must be cleared on videoLoad so hide-state does not carry across
    videos — mirroring how editsByCam is dropped on setPrimary/setSibling."""
    src = _src()
    i = src.find('v.on("videoLoad"')
    if i < 0:
        i = src.find("v.on('videoLoad'")
    assert i > 0, "videoLoad subscription not found"
    body = src[i:i + 800]
    assert re.search(r"hiddenByFrame\.clear\(\)", body), \
        "videoLoad must clear hiddenByFrame (per-frame hide-state must not leak across videos)"


def test_setEditable_comment_not_stale_default_on():
    """Cleanup (2026-05-24): editingAllowed now defaults to false, so the
    setEditable doc comment must not still claim 'Defaults on.'"""
    src = _src()
    assert "Defaults on." not in src, \
        "stale setEditable comment 'Defaults on.' must be updated (default is now false)"


def test_b7_focus_persists_across_videoload_with_clamp():
    """B7: videoLoad must NOT reset focusedCam to 0; it preserves the last focused
    cam and only clamps to a valid tile index when the new video has fewer tiles."""
    src = _src()
    i = src.find('v.on("videoLoad"')
    if i < 0:
        i = src.find("v.on('videoLoad'")
    assert i > 0, "videoLoad subscription not found"
    # capture the handler body up to the next v.on subscription
    body = src[i:i + 900]
    assert "focusedCam = 0" not in body, \
        "videoLoad must not unconditionally reset focusedCam to 0"
    # there must be a clamp guarding a stale focusedCam against the tile count
    assert ">= " in body or ">=" in body, "videoLoad must clamp focusedCam to tile count"


def test_renders_and_hittests_edits_only_markers():
    """A marker placed on a below-threshold/undetected bp (omitted by the backend
    from frame-poses) lives only in the local edits. renderTile + hit-test iterate
    `poses`, so the feature must merge edits-only bps via editedOnlyBodyparts —
    else the marker is recorded ('frame edited') but never drawn or selectable."""
    src = _src()
    assert "editedOnlyBodyparts" in src, "must import + use the edits-only merge helper"
    # hit-test goes through the augmented `hitPoses`, not raw curPosesForCam
    assert "hitPoses(" in src
    assert "hitTest(curPosesForCam(" not in src, "hit-test must use the edits-augmented poses"


def test_setMarkerSize_exists_and_mutable():
    """B1: the marker-size slider was a no-op. markerEditor must expose
    setMarkerSize(px) that updates a MUTABLE markerSize and re-renders."""
    src = _src()
    assert re.search(r"setMarkerSize\s*\(", src), "must expose setMarkerSize(px)"
    # markerSize must be reassignable (let, not const) so the setter can change it
    assert re.search(r"\blet\s+markerSize\b", src), \
        "markerSize must be `let` (mutable) so setMarkerSize can change it"
    # the setter must re-render so the change shows immediately
    i = src.find("setMarkerSize")
    body = src[i:i + 200]
    assert "renderAll()" in body or "renderTile" in body or "onFrame(" in body, \
        "setMarkerSize must re-render after changing the size"


def test_imports_labelerColor():
    """B2: primary markers + chips use the FL palette via labelerColor."""
    src = _src()
    assert re.search(
        r"import\s*\{[^}]*\blabelerColor\b[^}]*\}\s*from\s*[\"'][^\"']*palette\.mjs[\"']", src), \
        "must import labelerColor from internal/palette.mjs"


def test_primary_markers_use_labelerColor_chips_too():
    """B2: the primary layer + bp-chips color by bodypart index via labelerColor;
    comparison layers keep paletteColor (HSV)."""
    src = _src()
    # both helpers are present (comparison layers still use paletteColor)
    assert "labelerColor(" in src, "primary/chips must color via labelerColor"
    assert "paletteColor(" in src, "comparison layers must keep paletteColor"


def test_b3_selected_ring_white_no_amber_no_edited():
    """B3: selected ring is white rgba(255,255,255,0.85) at r+3.5 width 2; the
    amber #facc15 ring and the white edited ring are dropped entirely."""
    src = _src()
    assert "rgba(255,255,255,0.85)" in src, "selected ring must be white rgba(255,255,255,0.85)"
    assert "r + 3.5" in src, "selected ring offset must be r + 3.5"
    assert "#facc15" not in src, "amber selected ring must be dropped"
    # the white edited ring used 'r + 3' with '#fff' width 1.5 — that exact draw must be gone
    assert '"#fff", 1.5' not in src, "white edited ring must be dropped"


def test_b7_hit_pad_is_6():
    """B7: hit-test pad is 6 (labeler parity) at all markerEditor hitTest sites."""
    src = _src()
    # no hitTest call may pass pad 8 anymore
    assert not re.search(r"hitTest\([^;]*,\s*8\s*\)", src, re.S), \
        "hitTest pad must be 6, not 8, at every call site"
    # at least one explicit pad-6 call (the others may rely on it too).
    # NB: the call args nest parens (hitPoses(...)/frameEditsOf(...)), so scan to
    # the statement end rather than the first ')'.
    assert re.search(r"hitTest\([^;]*,\s*6\s*\)", src, re.S), \
        "hitTest must be called with pad 6"


def test_b5_b6_hover_name_and_show_names():
    """B5/B6: markerEditor tracks a hovered bp, exposes setShowNames(bool), and
    renders a marker's name when hovered OR when show-names is on, using
    name_label.mjs geometry + the labeler font/bg."""
    src = _src()
    # imports the pure label-box geometry
    assert re.search(
        r"import\s*\{[^}]*\bnameLabelBox\b[^}]*\}\s*from\s*[\"'][^\"']*name_label\.mjs[\"']", src), \
        "must import nameLabelBox from internal/name_label.mjs"
    # public setter + state
    assert re.search(r"setShowNames\s*\(", src), "must expose setShowNames(bool)"
    assert "showNames" in src, "must track showNames state"
    # hover-bp tracking
    assert "hoverBp" in src, "must track the hovered bodypart (hoverBp)"
    # the render condition: hovered OR show-names
    assert re.search(r"showNames\s*\|\|\s*\w*\s*===\s*hoverBp", src) or \
        re.search(r"hoverBp\s*===|===\s*hoverBp", src), \
        "name renders when bp === hoverBp or showNames is on"
    # the labeler label-box bg color
    assert "rgba(12,13,16,.65)" in src, "name-label box bg must match the labeler"
    # uses the geometry helper + fillText
    assert "nameLabelBox(" in src and "fillText(" in src, \
        "must draw the name via nameLabelBox geometry + fillText"

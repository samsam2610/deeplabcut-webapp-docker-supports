"""Static guards for the 3D View panel reflow + persisted view prefs
(resize width/height + flip-X/Y/Z, saved under the pose3d_view_prefs ui-setting).

See docs/superpowers/specs/2026-07-22-inline-3d-view-resize-reflow-flip-design.md.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
JS = ROOT / "src" / "static" / "inline_analysis_3d.js"
POSE3D = ROOT / "src" / "static" / "pose3d_viewer.js"


def _pose3d_controls_block(html):
    """The #ia3d-pose3d-controls div's inner region (start → the panel's close)."""
    i = html.find('id="ia3d-pose3d-controls"')
    assert i >= 0, "missing #ia3d-pose3d-controls"
    j = html.find("end ia3d-pose3d-controls", i)
    assert j >= 0, "missing the end-of-controls marker"
    return html[i:j]


# ── Markup: reflow row ──────────────────────────────────────────────────────

def test_reflow_row_left_column_and_canvas_on_right():
    """A flex row with align-items:flex-start holds the .ia3d-pose3d-ctl-col left
    column and the #ia3d-pose3d-canvas-box viewport on the right."""
    block = _pose3d_controls_block(CARD.read_text())
    # The reflow flex row exists with tops aligned.
    row = re.search(r'<div style="[^"]*display:flex[^"]*align-items:flex-start[^"]*">', block)
    assert row, "missing the align-items:flex-start reflow row"
    r0 = row.start()
    assert 'class="ia3d-pose3d-ctl-col"' in block[r0:], "reflow row must contain the left controls column"
    # canvas box on the right, and it no longer auto-centers.
    assert 'id="ia3d-pose3d-canvas-box"' in block[r0:], "reflow row must contain #ia3d-pose3d-canvas-box"
    box = block[block.index('id="ia3d-pose3d-canvas-box"'):]
    box_tag = box[:box.index(">")]
    assert "margin:0 auto" not in box_tag, "canvas box must drop the margin:0 auto centering"
    # Left column precedes the canvas box within the row.
    assert block.index('class="ia3d-pose3d-ctl-col"') < block.index('id="ia3d-pose3d-canvas-box"'), \
        "left controls column must come before the canvas viewport"


def test_reset_row_and_cams_precede_reflow_row():
    """Reset-view row + #ia3d-pose3d-cams still come before the reflow row."""
    block = _pose3d_controls_block(CARD.read_text())
    row = re.search(r'<div style="[^"]*display:flex[^"]*align-items:flex-start[^"]*">', block)
    assert row, "missing reflow row"
    assert 0 <= block.find('id="ia3d-pose3d-reset"') < row.start(), "Reset button must precede the reflow row"
    assert 0 <= block.find('id="ia3d-pose3d-cams"') < row.start(), "#ia3d-pose3d-cams must precede the reflow row"


# ── Markup: new controls ────────────────────────────────────────────────────

def test_view_width_height_inputs_present():
    block = _pose3d_controls_block(CARD.read_text())
    for iid, default in (("ia3d-pose3d-view-w", "460"), ("ia3d-pose3d-view-h", "520")):
        i = block.find(f'id="{iid}"')
        assert i >= 0, f"missing #{iid} number input"
        tag = block[block.rindex("<input", 0, i):block.index(">", i)]
        assert 'type="number"' in tag, f"#{iid} must be a number input"
        assert f'value="{default}"' in tag, f"#{iid} default should be {default}"


def test_flip_checkboxes_present():
    block = _pose3d_controls_block(CARD.read_text())
    for iid in ("ia3d-pose3d-flip-x", "ia3d-pose3d-flip-y", "ia3d-pose3d-flip-z"):
        i = block.find(f'id="{iid}"')
        assert i >= 0, f"missing #{iid} checkbox"
        tag = block[block.rindex("<input", 0, i):block.index(">", i)]
        assert 'type="checkbox"' in tag, f"#{iid} must be a checkbox"


def test_grid_origin_checkboxes_present_default_off():
    """Grid + origin toggles exist as checkboxes and are UNCHECKED by default (off)."""
    block = _pose3d_controls_block(CARD.read_text())
    for iid in ("ia3d-pose3d-grid", "ia3d-pose3d-origin"):
        i = block.find(f'id="{iid}"')
        assert i >= 0, f"missing #{iid} checkbox"
        tag = block[block.rindex("<input", 0, i):block.index(">", i)]
        assert 'type="checkbox"' in tag, f"#{iid} must be a checkbox"
        assert "checked" not in tag, f"#{iid} must default OFF (unchecked)"


# ── JS-source: viewer setFlip ───────────────────────────────────────────────

def test_set_flip_exported_and_scales_group():
    s = POSE3D.read_text()
    assert re.search(r"function\s+setFlip\s*\(", s), "must define setFlip()"
    assert "group.scale.set(" in s, "setFlip must call group.scale.set"
    m = re.search(r"return\s*\{[^}]*\binit\b[^}]*\}", s)
    assert m and "setFlip" in m.group(0), "setFlip must be in the returned viewer API"


def test_grid_origin_helpers_default_off_and_exported():
    """setGrid/setOrigin exist + are exported; the grid + axes helpers are created
    hidden (visible=false) so the default is off."""
    s = POSE3D.read_text()
    assert re.search(r"function\s+setGrid\s*\(", s), "must define setGrid()"
    assert re.search(r"function\s+setOrigin\s*\(", s), "must define setOrigin()"
    m = re.search(r"return\s*\{[^}]*\binit\b[^}]*\}", s)
    assert m and "setGrid" in m.group(0) and "setOrigin" in m.group(0), \
        "setGrid + setOrigin must be in the returned viewer API"
    assert "grid.visible = false" in s, "grid helper must be hidden by default"
    assert "axes.visible = false" in s, "origin axes helper must be hidden by default"


def test_view_width_not_clobbered_by_mirror_loop():
    """Regression: the mirror loop must NOT pin the canvas box width to the camera
    width (that clobbered the width control every tick — height was unaffected)."""
    s = JS.read_text()
    assert "style.maxWidth = camW" not in s, "mirror loop must not cap the box maxWidth to camW"
    assert "style.width = camW" not in s, "mirror loop must not set the box width to camW"


def test_grid_origin_wired_and_persisted():
    s = JS.read_text()
    assert re.search(r"setGrid\(", s), "grid toggle must call _pose3d.setGrid"
    assert re.search(r"setOrigin\(", s), "origin toggle must call _pose3d.setOrigin"
    assert re.search(r'ia3d-pose3d-grid"\)\?\.addEventListener', s), "grid checkbox must be wired"
    assert re.search(r'ia3d-pose3d-origin"\)\?\.addEventListener', s), "origin checkbox must be wired"
    assert "gridOn" in s and "originOn" in s, "grid/origin state must be in the persisted prefs"


# ── JS-source: wiring + persistence ─────────────────────────────────────────

def test_view_prefs_load_defined_and_called():
    s = JS.read_text()
    assert re.search(r"function\s+_loadPose3dViewPrefs\s*\(", s), "must define _loadPose3dViewPrefs"
    assert "_loadPose3dViewPrefs(" in s.split("function _loadPose3dViewPrefs")[0], \
        "must call _loadPose3dViewPrefs beside _loadPose3dBgColor"


def test_view_size_and_flip_wired_and_persisted():
    s = JS.read_text()
    # size inputs referenced + wired to a live-apply listener
    assert '"ia3d-pose3d-view-w"' in s, "width input must be referenced"
    assert '"ia3d-pose3d-view-h"' in s, "height input must be referenced"
    assert re.search(r'viewW\??\.addEventListener', s), "width input must be wired"
    assert re.search(r'viewH\??\.addEventListener', s), "height input must be wired"
    # flip checkboxes call setFlip + are wired
    assert re.search(r"setFlip\(", s), "flip toggle must call _pose3d.setFlip"
    assert re.search(r'ia3d-pose3d-flip-x"\)\?\.addEventListener', s), "flip-x must be wired"
    # persisted under the consolidated key via /dlc/project/ui-setting
    assert '"pose3d_view_prefs"' in s, "must persist under the pose3d_view_prefs ui-setting key"
    assert "/dlc/project/ui-setting" in s, "must save/load via /dlc/project/ui-setting"

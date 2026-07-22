"""Static guards for the editable + per-project-persisted 3D background colour
(#ia3d-pose3d-bg + setBackground + _loadPose3dBgColor).

See docs/superpowers/specs/2026-07-22-inline-3d-ui-rearrangements-design.md (feature 4).
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


def test_pose3d_bg_color_input_present():
    block = _pose3d_controls_block(CARD.read_text())
    i = block.find('id="ia3d-pose3d-bg"')
    assert i >= 0, "missing #ia3d-pose3d-bg color input in the pose3d controls"
    tag = block[block.rindex("<input", 0, i):block.index(">", i)]
    assert 'type="color"' in tag, "background control must be a color input"
    assert 'value="#12141a"' in tag, "background default should be #12141a"


def test_set_background_exported():
    s = POSE3D.read_text()
    assert re.search(r"function\s+setBackground\s*\(", s), "must define setBackground()"
    assert "scene.background.set(" in s, "setBackground must call scene.background.set"
    # The viewer's public API return (the one listing init/load/…), not _canvasSize's.
    m = re.search(r"return\s*\{[^}]*\binit\b[^}]*\}", s)
    assert m and "setBackground" in m.group(0), "setBackground must be in the returned viewer API"


def test_pose3d_bg_wired_to_setbackground_and_ui_setting():
    s = JS.read_text()
    assert re.search(r"ia3d-pose3d-bg[\s\S]{0,200}setBackground\(", s), "color input must call setBackground on input"
    assert '"pose3d_bg_color"' in s, "must persist under the pose3d_bg_color ui-setting key"
    assert "/dlc/project/ui-setting" in s, "must save/load via /dlc/project/ui-setting"
    assert re.search(r"function\s+_loadPose3dBgColor\s*\(", s), "must define _loadPose3dBgColor"

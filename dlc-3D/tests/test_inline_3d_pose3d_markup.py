"""Static markup guards for the "3D View" panel (three.js pose viewer spike).

See docs/superpowers/specs/2026-07-21-inline-3d-pose-viewer-threejs-spike-design.md.
The 3D View toggle-reveal panel sits directly AFTER the Triangulate panel and
BEFORE the Dataset Curation panel; it holds a WebGL canvas, a Reset-view button,
and a status span.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"


def _idx(hay, needle):
    i = hay.find(needle)
    assert i >= 0, f"not found: {needle}"
    return i


def test_pose3d_toggle_present_and_unchecked():
    html = CARD.read_text()
    i = _idx(html, 'id="ia3d-pose3d-toggle"')
    start = html.rindex("<input", 0, i)
    tag = html[start:html.index(">", start)]
    assert 'type="checkbox"' in tag, "3D-view toggle must be a checkbox"
    assert "checked" not in tag, "3D-view toggle must be UNCHECKED by default"


def test_pose3d_canvas_present():
    html = CARD.read_text()
    assert 'id="ia3d-pose3d-canvas"' in html


def test_pose3d_reset_and_status_present():
    html = CARD.read_text()
    assert 'id="ia3d-pose3d-reset"' in html
    assert 'id="ia3d-pose3d-status"' in html


def test_pose3d_controls_hidden_by_default():
    html = CARD.read_text()
    i = _idx(html, 'id="ia3d-pose3d-controls"')
    start = html.rindex("<div", 0, i)
    tag = html[start:html.index(">", start)]
    assert "hidden" in tag, "#ia3d-pose3d-controls must carry the hidden class by default"


def test_pose3d_panel_after_triangulate_before_curation():
    html = CARD.read_text()
    tri = _idx(html, 'id="ia3d-triangulate-panel"')
    pose = _idx(html, 'id="ia3d-pose3d-toggle"')
    cur = _idx(html, 'id="ia3d-curation-panel"')
    assert tri < pose < cur, (
        "3D View panel must appear AFTER the Triangulate panel and "
        "BEFORE the Dataset Curation panel"
    )

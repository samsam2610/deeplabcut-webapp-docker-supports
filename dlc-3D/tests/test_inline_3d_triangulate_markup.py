"""Static markup guards for the "Triangulate" panel (Phase 1 — anipose init).

See docs/superpowers/specs/2026-07-20-inline-3d-triangulate-anipose-init-design.md.
The Triangulate toggle-reveal section lives directly ABOVE the Dataset Curation
panel and (Phase 1) exposes a single button that initializes the selected stereo
pair into anipose folder layout.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
JS = ROOT / "src" / "static" / "inline_analysis_3d.js"


def _idx(hay, needle):
    i = hay.find(needle)
    assert i >= 0, f"not found: {needle}"
    return i


def test_triangulate_toggle_present_and_unchecked():
    html = CARD.read_text()
    i = _idx(html, 'id="ia3d-triangulate-toggle"')
    start = html.rindex("<input", 0, i)
    tag = html[start:html.index(">", start)]
    assert 'type="checkbox"' in tag, "triangulate toggle must be a checkbox"
    assert "checked" not in tag, "triangulate toggle must be UNCHECKED by default"


def test_triangulate_panel_before_curation_panel():
    html = CARD.read_text()
    tri = _idx(html, 'id="ia3d-triangulate-toggle"')
    cur = _idx(html, 'id="ia3d-curation-panel"')
    assert tri < cur, "Triangulate panel must appear BEFORE the Dataset Curation panel"


def test_triangulate_controls_hidden_by_default():
    html = CARD.read_text()
    i = _idx(html, 'id="ia3d-triangulate-controls"')
    start = html.rindex("<div", 0, i)
    tag = html[start:html.index(">", start)]
    assert "hidden" in tag, "#ia3d-triangulate-controls must carry the hidden class by default"


def test_anipose_init_button_and_status_present():
    html = CARD.read_text()
    assert 'id="ia3d-anipose-init-btn"' in html
    assert 'id="ia3d-anipose-init-status"' in html


def test_js_wires_triangulate_toggle_idempotently():
    js = JS.read_text()
    assert "_triangulateChromeWired" in js, "must use a module-level idempotent wire guard"
    assert re.search(r'ia3d-triangulate-controls"\)\?\.classList\.toggle\("hidden"', js), \
        "toggle must reveal/hide #ia3d-triangulate-controls via the hidden class"
    assert "/dlc-3d/anipose/init" in js, "button handler must POST to /dlc-3d/anipose/init"

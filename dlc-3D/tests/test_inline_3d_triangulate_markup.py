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


# ── Phase 2 — Triangulate keyframe range button + 3D coverage bar ──────────────

def test_triangulate_range_button_present_inside_controls_and_disabled():
    html = CARD.read_text()
    btn = _idx(html, 'id="ia3d-triangulate-range-btn"')
    # Lives inside the Triangulate controls block, ABOVE the Dataset Curation panel.
    ctrls = _idx(html, 'id="ia3d-triangulate-controls"')
    cur = _idx(html, 'id="ia3d-curation-panel"')
    assert ctrls < btn < cur, "range button must sit inside #ia3d-triangulate-controls"
    # Disabled by default (gated on keyframe lock).
    start = html.rindex("<button", 0, btn)
    tag = html[start:html.index(">", start)]
    assert "disabled" in tag, "#ia3d-triangulate-range-btn must be disabled by default"


def test_triangulate_range_status_span_present():
    html = CARD.read_text()
    assert 'id="ia3d-triangulate-range-status"' in html


def test_triangulate_coverage_bar_present():
    html = CARD.read_text()
    wrap = _idx(html, 'id="ia3d-triangulate-coverage-wrap"')
    can = _idx(html, 'id="ia3d-triangulate-coverage"')
    # canvas carries a fixed height like the finalize-coverage canvas
    start = html.rindex("<canvas", 0, can)
    tag = html[start:html.index(">", start)]
    assert 'height="14"' in tag, "#ia3d-triangulate-coverage must be a height=14 canvas"


def test_triangulate_coverage_bar_relocated_below_viewer():
    """The 3D coverage bar was relocated OUT of the collapsible Triangulate panel
    into the always-visible viewer timeline: it now sits directly AFTER the
    "Finalized frames" bar and is NOT inside #ia3d-triangulate-controls."""
    html = CARD.read_text()
    fin = _idx(html, 'id="ia3d-finalize-coverage-wrap"')
    wrap = _idx(html, 'id="ia3d-triangulate-coverage-wrap"')
    tri_ctrls = _idx(html, 'id="ia3d-triangulate-controls"')
    assert fin < wrap, "3D coverage bar must appear AFTER the Finalized-frames bar"
    assert wrap < tri_ctrls, (
        "3D coverage bar must NOT live inside #ia3d-triangulate-controls "
        "(it now precedes the Triangulate panel in the viewer timeline)"
    )

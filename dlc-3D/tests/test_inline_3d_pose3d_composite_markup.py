"""Static markup guards for the composite 3D-view panel (controls + filters).

See docs/superpowers/specs/2026-07-21-inline-3d-composite-viewer-controls-filters-design.md.
Adds, inside #ia3d-pose3d-controls: two mini-cam <img> mirroring the main viewer,
an on-screen control cluster (home / zoom / orbit d-pad), two quality-threshold
sliders (score/error) with value labels, and a median re-filter row
(medfilt / offset / apply / status).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"


def _controls_block(html):
    """The #ia3d-pose3d-controls div's inner region (start → the panel's close)."""
    i = html.find('id="ia3d-pose3d-controls"')
    assert i >= 0, "missing #ia3d-pose3d-controls"
    j = html.find("end ia3d-pose3d-controls", i)
    assert j >= 0, "missing the end-of-controls marker"
    return html[i:j]


# ── Part 1: mini multi-cam row ───────────────────────────────────────────────

def test_pose3d_mini_cams_present():
    block = _controls_block(CARD.read_text())
    assert 'id="ia3d-pose3d-cam0"' in block, "mini cam0 <canvas> must be present"
    assert 'id="ia3d-pose3d-cam1"' in block, "mini cam1 <canvas> must be present"


def test_pose3d_mini_cams_are_canvases():
    """The mini-cams composite frame+overlay, so they must be <canvas> (not <img>)."""
    html = CARD.read_text()
    for cam in ("ia3d-pose3d-cam0", "ia3d-pose3d-cam1"):
        i = html.find(f'id="{cam}"')
        start = html.rindex("<", 0, i)
        assert html[start:start + 7] == "<canvas", f"{cam} must be a <canvas>"
        # Sized 1:1 to the original tile by JS (tracks the viewer-size zoom), so it
        # must NOT be pinned to a fixed CSS width like width:100%.
        tag = html[start:html.index(">", start)]
        assert "width:100%" not in tag, f"{cam} width is set by JS, not fixed CSS"


def test_pose3d_mini_cam_wrappers_hideable():
    block = _controls_block(CARD.read_text())
    assert 'id="ia3d-pose3d-cam0-wrap"' in block
    assert 'id="ia3d-pose3d-cam1-wrap"' in block


# ── Part 2: on-screen control cluster ────────────────────────────────────────

def test_pose3d_control_buttons_present():
    block = _controls_block(CARD.read_text())
    for bid in (
        "ia3d-pose3d-home",
        "ia3d-pose3d-zoom-in",
        "ia3d-pose3d-zoom-out",
        "ia3d-pose3d-orbit-left",
        "ia3d-pose3d-orbit-right",
        "ia3d-pose3d-orbit-up",
        "ia3d-pose3d-orbit-down",
    ):
        assert f'id="{bid}"' in block, f"missing control button #{bid}"


def test_pose3d_canvas_container_is_relative():
    """The overlay cluster needs a positioned container around the canvas."""
    html = CARD.read_text()
    i = html.find('id="ia3d-pose3d-canvas"')
    # The nearest enclosing <div ...> before the canvas must be position:relative.
    div = html.rindex("<div", 0, i)
    tag = html[div:html.index(">", div)]
    assert "position:relative" in tag, "canvas container must be position:relative"


# ── Part 3: quality-threshold sliders ────────────────────────────────────────

def test_pose3d_score_slider_present():
    html = CARD.read_text()
    i = html.find('id="ia3d-pose3d-score-thr"')
    assert i >= 0, "missing #ia3d-pose3d-score-thr"
    tag = html[html.rindex("<input", 0, i):html.index(">", i)]
    assert 'type="range"' in tag
    assert 'min="0"' in tag and 'max="1"' in tag
    assert 'id="ia3d-pose3d-score-thr-val"' in html, "score value label required"


def test_pose3d_error_slider_present():
    html = CARD.read_text()
    i = html.find('id="ia3d-pose3d-error-thr"')
    assert i >= 0, "missing #ia3d-pose3d-error-thr"
    tag = html[html.rindex("<input", 0, i):html.index(">", i)]
    assert 'type="range"' in tag
    assert 'id="ia3d-pose3d-error-thr-val"' in html, "error value label required"


def test_pose3d_marker_size_slider_present():
    """Adjustable 3D marker-size range slider (0.2–5, default 1) with a value
    label, living inside the pose3d controls near the threshold sliders."""
    block = _controls_block(CARD.read_text())
    i = block.find('id="ia3d-pose3d-marker-size"')
    assert i >= 0, "missing #ia3d-pose3d-marker-size"
    tag = block[block.rindex("<input", 0, i):block.index(">", i)]
    assert 'type="range"' in tag, "marker-size control must be a range slider"
    assert 'value="1"' in tag, "marker-size default should be 1"
    assert 'id="ia3d-pose3d-marker-size-val"' in block, "marker-size value label required"


# ── Part 4: median re-filter row ─────────────────────────────────────────────

def test_pose3d_refilter_controls_present():
    block = _controls_block(CARD.read_text())
    assert 'id="ia3d-pose3d-medfilt"' in block
    assert 'id="ia3d-pose3d-offset"' in block
    assert 'id="ia3d-pose3d-apply"' in block
    assert 'id="ia3d-pose3d-refilter-status"' in block


def test_pose3d_medfilt_offset_defaults():
    html = CARD.read_text()
    m = html.find('id="ia3d-pose3d-medfilt"')
    mtag = html[html.rindex("<input", 0, m):html.index(">", m)]
    assert 'value="17"' in mtag, "medfilt default should be 17"
    o = html.find('id="ia3d-pose3d-offset"')
    otag = html[html.rindex("<input", 0, o):html.index(">", o)]
    assert 'value="15"' in otag, "offset default should be 15"

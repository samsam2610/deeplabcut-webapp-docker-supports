"""Static guards for the inline-3D panel consolidation.

- analyze buttons + new add-frame button moved into the finalize panel;
- keyframe group and a new finalize-outputs group are both gated by the toggle;
- marker area (chips + edit controls) relocated into the .ia3d-marker-flank;
- the finalize panel (.ia3d-right) stays sticky (still follows the scroll).

See docs/superpowers/specs/2026-07-09-inline-3d-panel-consolidation-design.md.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
JS = ROOT / "src" / "static" / "inline_analysis_3d.js"
CSS = ROOT / "src" / "static" / "inline_analysis_3d.css"


def _idx(hay, needle):
    i = hay.find(needle)
    assert i >= 0, f"not found: {needle}"
    return i


# ── Template ────────────────────────────────────────────────────────────────
def test_analyze_buttons_live_in_finalize_panel():
    html = CARD.read_text()
    assert 'class="ia3d-start-flank"' not in html, "old analysis-start flank must be gone"
    panel = _idx(html, 'id="ia3d-finalize-panel"')
    curation = _idx(html, 'id="ia3d-curation-panel"')
    for bid in ('id="ia3d-btn-analyze-current"', 'id="ia3d-btn-analyze-range-confined"',
                'id="ia3d-add-frame-nomarkers-btn"'):
        i = _idx(html, bid)
        assert panel < i < curation, f"{bid} must sit inside the finalize panel"


def test_two_gated_groups_present():
    html = CARD.read_text()
    kf = _idx(html, 'id="ia3d-finalize-controls"')
    analyze = _idx(html, 'class="ia3d-analyze-block"')
    outputs = _idx(html, 'id="ia3d-finalize-outputs"')
    # keyframe group, then the always-visible analyze block, then the outputs group
    assert kf < analyze < outputs, "order must be keyframe group → analyze block → outputs group"


def test_marker_area_relocated_into_flank():
    html = CARD.read_text()
    flank = _idx(html, 'class="ia3d-marker-flank"')
    chips = _idx(html, 'id="ia3d-bp-list-wrap"')
    edit = _idx(html, 'id="ia3d-marker-edit-controls"')
    panel = _idx(html, 'id="ia3d-finalize-panel"')
    # chips + edit controls come after the flank opens and before the finalize panel
    assert flank < chips < panel and flank < edit < panel, "marker area must be inside the marker flank"


# ── JS ──────────────────────────────────────────────────────────────────────
def test_toggle_and_reset_drive_both_gated_groups():
    js = JS.read_text()
    assert 'ia3d-finalize-outputs")?.classList.toggle("hidden"' in js, "toggle must gate finalize-outputs"
    assert 'ia3d-finalize-outputs")?.classList.remove("hidden"' in js, "reset must show finalize-outputs"


def test_new_button_reuses_shared_extract_fn():
    js = JS.read_text()
    assert "_extractCurrentFrameToLabeledData" in js, "extract logic must be a shared function"
    assert re.search(
        r'ia3d-add-frame-nomarkers-btn"\)[\s\S]{0,120}_extractCurrentFrameToLabeledData', js
    ), "new button must be wired to the shared extract function"


# ── CSS ─────────────────────────────────────────────────────────────────────
def test_finalize_panel_still_sticky():
    css = CSS.read_text()
    m = re.search(r"#inline-analysis-3d-card\s+\.ia3d-right\s*\{([^}]*)\}", css)
    assert m and "position: sticky" in m.group(1), "finalize panel must remain sticky (scroll-follow)"


def test_marker_flank_css_present():
    css = CSS.read_text()
    assert re.search(r"\.ia3d-marker-flank\s*\{", css), "marker flank needs a layout rule"
    assert re.search(r"\.ia3d-analyze-block\s*\{", css), "analyze block needs a layout rule"

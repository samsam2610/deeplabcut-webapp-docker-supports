"""Static guards for the 3D Inline Analysis card.

Cloned from viewer_3d.js / card_viewer_3d.html with va*->ia* rename, plus a
stereo analysis-dispatch IIFE. These parse the source files directly (no
runtime). See docs/superpowers/specs/2026-05-20-3d-inline-analysis-design.md.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS   = ROOT / "src" / "static" / "inline_analysis_3d.js"
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
PAGE = ROOT / "src" / "templates" / "dlc_3d.html"


def test_files_exist():
    assert JS.is_file() and CARD.is_file()


def test_no_va_identifier_leaks_in_clone():
    src = JS.read_text()
    assert "va3d-" not in src, "DOM id va3d- leaked into the clone"
    assert not re.search(r"\bva[A-Z]", src), "camelCase va* identifier leaked"
    assert "view-analyzed-3d-card" not in src
    # The clone wires its OWN (renamed) open button…
    assert "btn-open-inline-analysis-3d" in src
    # …and may reference btn-open-view-analyzed at most ONCE, solely as the
    # nav-placement insertion anchor (not as the card's own open button).
    assert src.count("btn-open-view-analyzed") <= 1, (
        "btn-open-view-analyzed should appear at most once (the nav-placement "
        "anchor); more suggests the clone's open-button rename regressed"
    )


def test_card_has_analysis_params_and_dual_tile():
    html = CARD.read_text()
    for needed in [
        "inline-analysis-3d-card", "btn-close-inline-analysis-3d",
        "ia3d-snapshot", "ia3d-batch-size", "ia3d-frames-per-click",
        "ia3d-keep-warm-seconds", "ia3d-btn-analyze-range",
        "ia3d-last-run-status", "ia3d-warm-indicator", "ia3d-sibling-status",
        "ia3d-overlay-toggle", "ia3d-frame-img-0",
    ]:
        assert needed in html, f"missing id {needed!r}"
    assert "va3d-" not in html


def test_page_wires_card_button_and_script():
    page = PAGE.read_text()
    assert "partials/card_inline_analysis_3d.html" in page
    assert "inline_analysis_3d.js" in page
    assert 'id="btn-open-inline-analysis-3d"' in page


def test_dispatch_runs_both_cameras_against_main_webapp_api():
    src = JS.read_text()
    # uses the main webapp inline-analysis endpoints
    assert "/dlc/project/inline-analysis/session/start" in src
    assert "/dlc/project/inline-analysis/range" in src
    assert "/dlc/project/inline-analysis/range/status" in src
    assert "/dlc/project/snapshots" in src
    # resolves the sibling camera + gates the button
    assert "/dlc-3d/sibling-camera" in src
    assert "_siblingPath" in src
    # submits TWO ranges and polls both (stereo)
    assert "_submitRange(sk, cam0" in src
    assert "_submitRange(sk, _siblingPath" in src
    assert "Promise.all([_pollReq(req0), _pollReq(req1)])" in src
    # on done: re-discovers + force-loads the frame (inherited render path)
    assert "_iaDiscoverVariants(cam0)" in src
    assert "_iaLoadFrame(_iaCurrentFrame)" in src


def test_analyze_button_disabled_by_default():
    html = CARD.read_text()
    m = re.search(r'<button[^>]*id="ia3d-btn-analyze-range"[^>]*>', html, re.S)
    assert m and "disabled" in m.group(0), (
        "Analyze button must default disabled until a sibling is resolved"
    )


def test_open_button_relocated_into_launcher_nav():
    """The open button is defined in dlc_3d.html (so the cloned viewer wires its
    click handler at module-eval) but relocated into the shared launcher nav
    (#dlc-frame-extract-launch) at runtime — that list is baked into a
    main-webapp partial we can't edit from this module. Guard the relocation +
    that the button is styled to match the nav (inspect-btn). See session
    2026-05-21.
    """
    page = PAGE.read_text()
    js = JS.read_text()
    assert 'id="btn-open-inline-analysis-3d"' in page
    assert 'class="inspect-btn"' in page, "button must match nav-item styling"
    assert "dlc-frame-extract-launch" in js, "JS must target the launcher nav container"
    assert "btn-open-view-analyzed" in js, "JS should anchor after View Analyzed"
    assert "insertAdjacentElement" in js or "appendChild" in js


# ─── 2026-05-21 follow-up fixes (markers, compare-removal, horizontal layout) ─

def test_compare_and_customize_threshold_removed_from_card():
    """Comparison-layer + per-layer-threshold UI must NOT be in the 3D card
    (removed per user request 2026-05-21)."""
    html = CARD.read_text()
    for frag in [
        "ia3d-overlay-compare-block", "ia3d-overlay-add-compare",
        "ia3d-overlay-compare-list", "ia3d-overlay-customize-thresholds",
        "ia3d-overlay-primary-row", "Comparison layers",
        "Customize threshold per layer",
    ]:
        assert frag not in html, f"compare/customize UI reintroduced: {frag!r}"
    # the primary picker + global threshold must remain
    assert "ia3d-overlay-primary-select" in html
    assert "ia3d-overlay-threshold" in html


def test_discover_does_not_depend_on_removed_compare_dropdown():
    """_iaDiscoverVariants must not early-return on the (removed) compare
    dropdown — that bug silently killed all marker discovery."""
    src = JS.read_text()
    i = src.find("async function _iaDiscoverVariants(")
    assert i > 0
    body = src[i:i + 500]
    assert "ia3d-overlay-add-compare" not in body, (
        "_iaDiscoverVariants must not reference the removed compare dropdown"
    )


def test_layer_errored_cleared_and_tile_fetch_not_pre_filtered():
    """Markers fix: successful fetch clears layer.errored, and the sibling
    tile render fetches all VISIBLE layers (not pre-filtered on errored) so a
    sticky errored flag self-heals."""
    src = JS.read_text()
    assert src.count("layer.errored = false;") >= 2
    # the sibling fetch must NOT pre-filter on errored (only on visible)
    assert ".filter(l => l.visible)\n" in src or ".filter(l => l.visible)" in src


def test_clone_css_exists_and_linked():
    """Horizontal layout: the clone needs its own .ia3d-* CSS (the va3d-
    rename orphaned viewer_3d.css's selectors)."""
    css = ROOT / "src" / "static" / "inline_analysis_3d.css"
    assert css.is_file(), "inline_analysis_3d.css must exist"
    assert "ia3d-tile-row" in css.read_text()
    assert "inline_analysis_3d.css" in PAGE.read_text(), "must be linked in dlc_3d.html"


def test_section_order_browser_then_params_then_player():
    """Layout order (user request 2026-05-21): file browser (Source tabs) →
    Analysis Parameters → Player section."""
    html = CARD.read_text()
    i_tabs   = html.find("<!-- Source tabs -->")
    i_params = html.find("Analysis Parameters")
    i_player = html.find("Player section")
    assert 0 < i_tabs < i_params < i_player, (
        "order must be file browser → analysis params → player viewer"
    )


def test_init_analysis_file_button_wired():
    """3D 'Initialize analysis files (both cameras)' button + endpoint wiring."""
    html = CARD.read_text()
    js = JS.read_text()
    assert 'id="ia3d-init-analysis-file"' in html
    assert "ia3d-init-analysis-file" in js
    assert "/dlc/project/analysis-file/initialize" in js
    assert "/dlc/project/analysis-file/status" in js


def test_analyze_button_matches_start_analysis_style():
    """3D Analyze button mirrors the Analyze-card 'Start Analysis' button:
    btn-create class, outline play-triangle SVG, 'Start Analysis' label.
    It must stay default-disabled (sibling gating)."""
    html = CARD.read_text()
    m = re.search(r'<button[^>]*id="ia3d-btn-analyze-range".*?</button>', html, re.S)
    assert m, "ia3d-btn-analyze-range button not found"
    btn = m.group(0)
    assert "btn-create" in btn
    assert "<svg" in btn and 'points="5 3 19 12 5 21 5 3"' in btn
    assert "Start Analysis" in btn
    assert "disabled" in btn, "must remain default-disabled until a sibling resolves"
    assert "width:100%" not in btn


def test_init_button_three_way_state_logic():
    """_refreshInitFileBtn distinguishes both-exist / neither / partial, and the
    partial branch writes a 'will generate camN only' note to the status line."""
    js = JS.read_text()
    i = js.find("async function _refreshInitFileBtn")
    assert i > 0, "_refreshInitFileBtn definition not found"
    body = js[i:i + 2500]
    # both exist -> disabled with the 'exist' wording
    assert "Analysis files exist" in body
    # file-wide: the old 'ready' wording must be gone everywhere, not just in this function
    assert "Analysis files ready" not in js, "old 'ready' wording must be replaced"
    # partial-state note text (both directions)
    assert "Initialize will generate cam1 only" in body
    assert "Initialize will generate cam0 only" in body
    # partial-state names the missing camera on the button
    assert "Initialize cam1 analysis file" in body
    assert "Initialize cam0 analysis file" in body
    # partial messaging is guarded by a resolved sibling
    assert "_siblingPath" in body
    # the note is written to the existing status line
    assert "initFileStatus" in body


def test_per_tile_edit_helpers_exist():
    js = JS.read_text()
    assert "_ia3dTileCanvasToVideo" in js, "per-tile coord helper missing"
    assert "_ia3dTileHitTest" in js, "per-tile hit-test helper missing"
    assert "_ia3dFlushTileEdit" in js and "_ia3dFlushTileDelete" in js, "per-tile flush helpers missing"
    assert "tile.canvasEl" in js and "tile.imgEl" in js
    assert "this.dragging" in js and "this.dragBp" in js


def test_sibling_editing_wired():
    js = JS.read_text()
    assert "_wireSiblingEditing" in js, "sibling editing method missing"
    assert js.count("_wireSiblingEditing(") >= 2, "must be defined and called at least once"
    i = js.find("_wireSiblingEditing(tile)")
    body = js[i:i + 2600]
    assert "tile.canvasEl.addEventListener" in body
    assert "tile.pendingEdits" in body
    assert "_ia3dFlushTileEdit(tile" in body
    assert "_ia3dTileHitTest(tile" in body


def test_sibling_render_overlays_pending_edits():
    js = JS.read_text()
    i = js.find("async _renderTileMarkers(tile)")
    assert i > 0
    body = js[i:i + 3600]
    assert "tile.pendingEdits.get(" in body, "render must apply pending edits for the focused/edited tile"


def test_save_adjustments_persists_all_tiles():
    js = JS.read_text()
    i = js.find("iaSaveAdjBtn.addEventListener")
    assert i > 0
    body = js[i:i + 3000]
    # the handler saves siblings too: iterate Controller.tiles beyond tile-0,
    # filter to those with pending edits, and save each to its own primary h5.
    assert "Controller.tiles" in body, "save handler must iterate the tiles"
    assert "pendingEdits" in body, "must filter siblings with pending edits"
    assert "primaryH5Path" in body, "must save each sibling to its own resolved h5 path"
    # and the sibling save uses the marker-edits endpoint
    assert "/dlc/viewer/save-marker-edits" in body


def test_finalize3d_minicard_present_after_curation():
    html = CARD.read_text()
    for needed in ["ia3d-finalize-toggle", "ia3d-finalize-controls", "ia3d-finalize-start",
                   "ia3d-finalize-count", "ia3d-finalize-add-btn", "ia3d-finalize-status"]:
        assert f'id="{needed}"' in html, f"missing {needed!r}"
    assert html.find('id="ia3d-curation-panel"') < html.find('id="ia3d-finalize-toggle"')


def test_marker_edit3d_controls_moved_below_marker_list():
    html = CARD.read_text()
    assert 'id="ia3d-marker-edit-banner"' not in html, "old top banner must be removed"
    assert 'id="ia3d-marker-edit-controls"' in html
    pos_list  = html.find('id="ia3d-bp-list-wrap"')
    pos_ctrls = html.find('id="ia3d-marker-edit-controls"')
    pos_cur   = html.find('id="ia3d-curation-panel"')
    assert 0 < pos_list < pos_ctrls < pos_cur
    for needed in ["ia3d-marker-edit-count", "ia3d-save-adjustments-btn",
                   "ia3d-discard-adjustments-btn", "ia3d-clear-frame-btn"]:
        assert f'id="{needed}"' in html


def test_js3d_edit_gated_on_finalize():
    js = JS.read_text()
    assert "_ia3dFinalizeEnabled" in js
    i = js.find("function _iaIsEditable")
    seg = js[i:i + 120]
    assert "_ia3dFinalizeEnabled" in seg, "_iaIsEditable must require _ia3dFinalizeEnabled"
    assert 'getElementById("ia3d-marker-edit-controls")' in js
    assert 'getElementById("ia3d-marker-edit-banner")' not in js

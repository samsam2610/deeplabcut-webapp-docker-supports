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
CSS  = ROOT / "src" / "static" / "inline_analysis_3d.css"


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


def test_card_has_analysis_params_and_viewer_mount():
    html = CARD.read_text()
    for needed in [
        "inline-analysis-3d-card", "btn-close-inline-analysis-3d",
        "ia3d-snapshot", "ia3d-batch-size", "ia3d-frames-per-click",
        "ia3d-keep-warm-seconds", "ia3d-btn-analyze-range",
        "ia3d-last-run-status", "ia3d-warm-indicator", "ia3d-sibling-status",
        "ia3d-overlay-toggle", "ia3d-viewer-mount",
    ]:
        assert needed in html, f"missing id {needed!r}"
    # Phase 4c: the static tile-row markup + tile template were replaced by the
    # single VideoViewer mount — they must be gone.
    assert "ia3d-tile-row" not in html, "old static tile-row markup must be removed"
    assert "ia3d-tile-template" not in html, "old tile <template> must be removed"
    assert "ia3d-frame-img-0" not in html, "old static tile-0 img must be removed"
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
    # on done: re-discovers the cam0 h5 variants (auto-picks the freshly-written
    # primary + resolves the sibling) then force-reloads the shared viewer so
    # markers paint deterministically (Phase 4c: VideoViewer.load replaces the
    # old direct _iaLoadFrame call).
    assert "_iaDiscoverVariants(cam0)" in src
    assert "_viewer.load(" in src
    assert "setOverlayEnabled(true)" in src


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


def test_marker_rendering_delegated_to_library():
    """Phase 4c: the old per-layer / sibling-tile rendering internals
    (_iaLayers, layer.errored, _renderTileMarkers, posesCache filtering) were
    removed — the shared markerEditor library now owns all overlay rendering.
    The consumer must compose markerEditor and feed it the bp-chip / edit-banner
    elements, and must NOT re-implement the removed rendering internals."""
    src = JS.read_text()
    assert "markerEditor(" in src, "must compose the shared markerEditor feature"
    assert "_viewer.use(_markerEditor)" in src
    # removed old-fork rendering internals must be gone
    assert "_iaLayers" not in src
    assert "_renderTileMarkers" not in src
    assert "posesCache" not in src
    assert "markersByFrame" not in src


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


def test_per_tile_edit_delegated_to_library():
    """Phase 4c: the old per-tile edit helpers (_ia3dTileCanvasToVideo,
    _ia3dTileHitTest, _ia3dFlushTileEdit/_ia3dFlushTileDelete) + the Tile
    drag-state class were removed; the markerEditor library now owns coord
    mapping, hit-testing, and per-edit server flush. The consumer must NOT
    re-implement them."""
    js = JS.read_text()
    for removed in [
        "_ia3dTileCanvasToVideo", "_ia3dTileHitTest",
        "_ia3dFlushTileEdit", "_ia3dFlushTileDelete",
    ]:
        assert removed not in js, f"removed per-tile helper leaked: {removed!r}"
    # the library handles edit flush via the saveMarker endpoint, injected here
    assert "/dlc/viewer/marker-edit" in js, "marker-edit flush endpoint must be wired to markerEditor"


def test_focused_cam_editing_delegated_to_library():
    """Phase 4c: sibling (cam1) editing is now the library's focused-cam model —
    the old consumer-side _wireSiblingEditing + Controller tile machinery were
    removed. The consumer composes markerEditor (which wires both tiles) and the
    sibling layer is fed via setSibling()."""
    js = JS.read_text()
    assert "_wireSiblingEditing" not in js, "old consumer-side sibling editing must be gone"
    assert "Controller" not in js, "old Controller singleton must be gone"
    assert "setSibling(" in js, "consumer must feed the cam1 sibling layer to markerEditor"


def test_save_adjustments_persists_both_cams():
    js = JS.read_text()
    i = js.find("async function _iaSaveAdjustments")
    assert i > 0, "_iaSaveAdjustments handler not found"
    body = js[i:i + 1600]
    # the handler saves BOTH cams: cam0 = _overlayPrimaryH5, cam1 = _siblingPrimaryH5,
    # each gated on that cam's edit count via markerEditor.getEditCount(cam).
    assert "getEditCount(0)" in body and "getEditCount(1)" in body, "must check per-cam edit counts"
    assert "_overlayPrimaryH5" in body, "cam0 saves to the consumer-tracked primary h5"
    assert "_siblingPrimaryH5" in body, "cam1 saves to the consumer-tracked sibling h5"
    # and the save uses the marker-edits endpoint
    assert "/dlc/viewer/save-marker-edits" in body


def test_finalize3d_minicard_present_after_curation():
    html = CARD.read_text()
    for needed in ["ia3d-finalize-toggle", "ia3d-finalize-controls",
                   "ia3d-finalize-add-btn", "ia3d-finalize-status"]:
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
    """Phase 4c: marker editing is gated on the Finalize toggle via the
    markerEditor master edit gate (setEditable). The old _iaIsEditable() /
    _ia3dFinalizeEnabled module gate was removed — editing now defaults OFF and
    the Finalize toggle flips setEditable(true)."""
    js = JS.read_text()
    # editing defaults OFF in this card
    assert "setEditable(false)" in js, "editing must default OFF (only on when Finalize toggled)"
    # the Finalize toggle drives setEditable
    i = js.find('ia3d-finalize-toggle')
    assert i > 0
    # find the toggle change handler and confirm it calls setEditable with the
    # checked state
    j = js.find('ia3dFinalizeToggle?.addEventListener')
    assert j > 0, "Finalize toggle change handler not found"
    body = js[j:j + 500]
    assert "setEditable(on)" in body, "Finalize toggle must drive markerEditor.setEditable"
    # the edit-count banner element is the controls wrapper (no separate banner id)
    assert 'editBanner: $("ia3d-marker-edit-controls")' in js
    assert "ia3d-marker-edit-banner" not in js


def test_js3d_finalize_flow_and_autopopulate():
    js = JS.read_text()
    # the finalize controls are referenced by id (via the $() id helper)
    assert '"ia3d-finalize-toggle"' in js
    assert '"ia3d-finalize-add-btn"' in js
    assert "/dlc/project/inline-analysis/finalize-range" in js
    assert "/dlc/viewer/save-marker-edits" in js
    assert "_ia3dPopulateFinalizeFields" in js
    # the finalize-add handler resolves the cam1 source from the sibling path /
    # the consumer-tracked sibling h5
    i = js.find("async function _onFinalizeAddClick")
    assert i > 0, "_onFinalizeAddClick handler not found"
    body = js[i:i + 2600]
    assert "_siblingPath" in body
    assert "_siblingPrimaryH5" in body, "cam1 finalize source must come from the resolved sibling h5"


def test_btn_sm_disabled_styling_exists_3d():
    css = (ROOT / "src" / "static" / "inline_analysis_3d.css").read_text()
    assert ".btn-sm:disabled" in css, "disabled .btn-sm must be visually greyed (e.g. Init button)"


def test_finalize3d_confirms_before_overwrite():
    js = JS.read_text()
    i = js.find("async function _onFinalizeAddClick")
    assert i > 0
    body = js[i:i + 2000]
    assert "window.confirm" in body, "3D finalize must confirm before overwriting _analyzed"
    assert "analysis-file/status" in body, "confirm must be gated on whether _analyzed already exists"


def test_granular_player_controls_present():
    """Clip-cutter-style granular controls: play-backward + click-to-jump to an
    exact frame (the numeric fps/step/skip-N inputs already cover step granularity)."""
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    assert 'id="ia3d-btn-play-back"' in html, "play-backward button missing"
    assert 'id="ia3d-frame-jump"' in html, "frame-jump input missing"
    js = JS.read_text()
    # play-back wires the library's reverse direction; frame-jump seeks to the typed frame
    assert "setPlayDir(-1)" in js, "play-back must drive VideoViewer.setPlayDir(-1)"
    assert 'ia3d-btn-play-back' in js and 'ia3d-frame-jump' in js, "granular controls not wired"


def test_skip_presets_present_and_wired():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    assert 'class="ia3d-skip-preset"' in html, "skip-size preset buttons missing"
    js = JS.read_text()
    assert "ia3d-skip-preset" in js and "setSkipN" in js, "skip presets not wired to setSkipN"


def test_status_note_timeline_outside_curation_panel():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    cur_start = html.index('id="ia3d-curation-panel"')
    bars = html.index('id="ia3d-csv-bars"')
    assert bars < cur_start, "status/note timeline must be surfaced above the curation panel"


def test_size_row_left_aligned_and_help_present():
    css = (ROOT / "src" / "static" / "inline_analysis_3d.css").read_text()
    i = css.index(".vv-tile-size-row")
    assert "flex-start" in css[i:i+200], "size-row must be left-aligned (justify-content:flex-start)"
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    assert 'id="ia3d-help-btn"' in html and 'id="ia3d-help-tooltip"' in html, "shortcuts help missing"


def test_clip_extractor_composed():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    for el in ("ia3d-clip-enable", "ia3d-clip-panel", "ia3d-clip-start",
               "ia3d-clip-frames", "ia3d-clip-extract-btn"):
        assert f'id="{el}"' in html, f"missing clip element {el}"
    i = html.index('id="ia3d-clip-enable"')
    assert "checked" not in html[i-120:i+120], "clip-extract enable must be UNCHECKED by default"
    js = JS.read_text()
    assert "clipExtractor(" in js, "clipExtractor not composed"
    assert "/dlc-3d/extract-clip" in js, "extractClip endpoint not injected"


def test_inline_keyboard_document_scoped():
    js = JS.read_text()
    # Document-scoped (not mount/card-scoped) so shortcuts work regardless of which
    # element has focus while the card is open; the base gates on viewer visibility.
    assert "keyboardTarget: document" in js, \
        "inline viewer must use document keyboardTarget so shortcuts work regardless of focus"


def test_surfaced_timeline_wraps_not_hidden_class():
    """The surfaced status/note bar wraps must NOT use class="hidden"
    (.hidden is display:none !important, which statusNoteTimeline's style.display
    reveal cannot override). They start as inline display:none, which the feature
    toggles by content."""
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    for wid in ("ia3d-status-bar-wrap", "ia3d-note-bar-wrap"):
        i = html.index(f'id="{wid}"')
        tag = html[i-40:i+90]
        assert 'class="hidden"' not in tag, f"{wid} must not use class=hidden (blocks the timeline reveal)"
    # the bars container must be visible (not hidden) so the surfaced timeline shows
    j = html.index('id="ia3d-csv-bars"')
    assert 'class="hidden"' not in html[j-20:j+60], "#ia3d-csv-bars must not be class=hidden once surfaced"


def test_main_timeline_is_canvas():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    assert 'id="ia3d-seek-canvas"' in html, "main timeline must be a canvas"
    assert 'id="ia3d-seek"' not in html, "the range-input seek must be removed"
    js = JS.read_text()
    assert "coverage_timeline.mjs" in js, "must import the coverage reducer"
    assert "ia3d-seek-canvas" in js and "coverageRects" in js and "xToFrame" in js


def test_coverage_fetch_wired_and_threshold_recomputes():
    js = JS.read_text()
    assert "/dlc/viewer/pose-coverage" in js, "coverage endpoint not fetched"
    assert "_refreshCoverage" in js, "coverage refresh helper missing"
    i = js.find('$("ia3d-overlay-threshold")')
    assert i > 0 and "_refreshCoverage" in js[i:i+400], "threshold change must refresh coverage (debounced)"


def test_coverage_bar_draw_and_seek_helpers_factored():
    js = JS.read_text()
    assert "function _drawCoverageBar(" in js, "shared coverage-bar draw helper missing"
    assert "function _wireSeekCanvas(" in js, "shared seek-canvas wiring helper missing"


def test_finalize_coverage_bar_present_and_wired():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    fc = html.index('id="ia3d-finalize-controls"')
    cov = html.index('id="ia3d-finalize-coverage"')
    assert cov > fc, "finalize coverage canvas must be inside the finalize controls"
    js = JS.read_text()
    assert "_refreshFinalizeCoverage" in js, "finalize coverage refresh helper missing"
    assert "mode=presence" in js, "must request presence-mode coverage"
    assert "/dlc/project/analysis-file/status" in js
    ti = js.find('ia3dFinalizeToggle?.addEventListener')
    assert ti > 0 and "_refreshFinalizeCoverage" in js[ti:ti+400], "toggle must refresh finalize coverage"
    fi = js.find("async function _onFinalizeAddClick")
    assert fi > 0 and "_refreshFinalizeCoverage" in js[fi:fi+3200], "finalize-add must refresh coverage"


def test_bp_chip_height_reserved():
    css = (ROOT / "src" / "static" / "inline_analysis_3d.css").read_text()
    assert "ia3d-measuring" in css, "measuring class (force-show checkmarks) missing"
    js = JS.read_text()
    assert "_reserveBpChipHeight" in js, "chip-height reserve helper missing"
    i = js.find("async function _applyOverlayPrimary")
    assert i > 0 and "_reserveBpChipHeight" in js[i:i+1200], "must reserve chip height after setPrimary"


def test_finalize_region_nav_present_and_wired():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    assert 'id="ia3d-finalize-prev"' in html and 'id="ia3d-finalize-next"' in html, "finalize nav buttons missing"
    js = JS.read_text()
    assert "nextCoveredBucket" in js, "finalize nav must use nextCoveredBucket"
    assert "ia3d-finalize-prev" in js and "ia3d-finalize-next" in js, "finalize nav not wired"


def test_skip_buttons_paired_in_one_group():
    html = CARD.read_text()
    # Both skip buttons + the N input + presets live inside one .ia3d-skip-group
    # so the controls-row wrap can't orphan skip-forward on a second line.
    m = re.search(r'<span class="ia3d-skip-group">(.*?)</span>\s*</span>', html, re.S)
    assert m, "skip controls must be wrapped in a single .ia3d-skip-group span"
    group = m.group(1)
    assert 'id="ia3d-btn-skip-back"' in group
    assert 'id="ia3d-btn-skip-fwd"' in group
    assert 'id="ia3d-skip-n"' in group
    assert 'class="ia3d-skip-presets"' in group
    # skip-forward sits immediately after skip-back (the chosen pairing)
    assert group.index('id="ia3d-btn-skip-back"') < group.index('id="ia3d-btn-skip-fwd"') \
        < group.index('id="ia3d-skip-n"')


def test_skip_group_css_keeps_it_together():
    css = CSS.read_text()
    m = re.search(r"\.ia3d-skip-group\s*\{([^}]*)\}", css)
    assert m, "missing .ia3d-skip-group CSS rule"
    body = m.group(1)
    assert "inline-flex" in body and "flex-shrink: 0" in body, \
        "group must be an inline-flex item that does not shrink (so it wraps as a unit)"


def test_zoom_mirrors_geometry_onto_timelines():
    js = JS.read_text()
    # a helper that applies the row geometry to the timeline canvases
    assert js.count("_applyTimelineWidth") >= 2, \
        "_applyTimelineWidth must be defined and called"
    # the zoom handler feeds setZoom's return into it
    assert re.search(r"v\.setZoom\([^)]*\)", js)
    assert re.search(r"_applyTimelineWidth\(\s*g\s*\)", js), \
        "zoom handler must pass setZoom's returned geometry to _applyTimelineWidth"
    # all four timeline canvases are mirrored
    for cid in ["ia3d-seek-canvas", "ia3d-status-canvas", "ia3d-note-canvas", "ia3d-finalize-coverage"]:
        assert cid in js
    # the status/note feature handle is captured and redrawn
    assert "_snTimeline" in js
    assert re.search(r"_snTimeline\s*\.\s*redraw\s*\(", js), \
        "must call the status/note feature's redraw() after resizing"


def test_controls_split_into_three_rows():
    html = CARD.read_text()
    assert html.count('class="ia3d-ctrl-row"') == 3, "controls must be three .ia3d-ctrl-row rows"
    # the last row carries the frame counter + time display (+ help)
    rows = re.findall(r'<div class="ia3d-ctrl-row"[^>]*>(.*?)</div>\s*(?=<div class="ia3d-ctrl-row"|</div>)', html, re.S)
    assert len(rows) == 3
    last = rows[2]
    assert 'id="ia3d-frame-counter"' in last and 'id="ia3d-time-display"' in last and 'id="ia3d-help-btn"' in last
    # playback row has play + step; jump row has the skip group
    assert 'id="ia3d-btn-play"' in rows[0]
    assert 'class="ia3d-skip-group"' in rows[1]


def test_controls_three_row_css():
    css = CSS.read_text()
    assert re.search(r"#inline-analysis-3d-card\s+\.fe-controls\s*\{[^}]*flex-direction:\s*column", css), \
        "missing column layout for .fe-controls in the inline card"
    assert re.search(r"\.ia3d-ctrl-row\s*\{[^}]*display:\s*flex", css), "missing .ia3d-ctrl-row flex rule"


def test_coverage_cache_keyed_by_width_and_refetched_on_zoom():
    js = JS.read_text()
    # cache key includes the fetch width (so each zoom level caches its own
    # resolution) — the key template ends with ":${w}"
    assert ":${w}" in js, "coverage cache key must include the width component :${w}"
    # the zoom handler triggers a coverage re-fetch at the new width
    assert js.count("_refreshCoverageForZoom") >= 2, \
        "_refreshCoverageForZoom must be defined and called from the zoom handler"
    # the zoom re-fetch refreshes BOTH the working-layer and finalize bars
    m = re.search(r"function _refreshCoverageForZoom\(\)\s*\{(.*?)\n\}", js, re.S)
    assert m and "_refreshCoverage(" in m.group(1) and "_refreshFinalizeCoverage(" in m.group(1), \
        "_refreshCoverageForZoom must refresh both coverage bars"


def test_skip_preset_100_exists():
    html = CARD.read_text()
    assert re.search(r'class="ia3d-skip-preset"\s+data-n="100"\s*>\s*100\s*<', html), \
        "missing the 100-frame skip preset button"
    # it lives inside the skip-presets cluster
    presets = re.search(r'class="ia3d-skip-presets"[^>]*>(.*?)</span>', html, re.S).group(1)
    assert 'data-n="100"' in presets


def test_finalize_keyframe_window_markup():
    html = CARD.read_text()
    for need in ["ia3d-finalize-keyframe", "ia3d-finalize-lock", "ia3d-finalize-before",
                 "ia3d-finalize-after", "ia3d-finalize-length", "ia3d-finalize-range"]:
        assert need in html, f"missing finalize keyframe element id {need!r}"
    # the old start/count inputs are gone
    assert "ia3d-finalize-start" not in html, "old finalize Start-frame input must be removed"
    assert "ia3d-finalize-count" not in html, "old finalize Frames-count input must be removed"
    # the Add button + finalized coverage bar are kept
    assert "ia3d-finalize-add-btn" in html and "ia3d-finalize-coverage" in html


def test_finalize_keyframe_glue_wired():
    js = JS.read_text()
    assert ("syncWindow" in js and "finalizeRange" in js and "keyframe_window.mjs" in js), \
        "must import syncWindow + finalizeRange from keyframe_window.mjs"
    assert "finalizeRange(" in js and "syncWindow(" in js
    assert "_finalizeKeyframe" in js and "_finalizeLocked" in js
    assert re.search(r'e\.key\s*===\s*"l"', js) or re.search(r"\.key\s*===\s*'l'", js), \
        "must wire an 'l' key shortcut for the finalize lock"
    assert "ia3d-finalize-start" not in js and "ia3d-finalize-count" not in js
    assert "_ia3dLastRun" not in js, "old last-run finalize autopopulate state must be removed"

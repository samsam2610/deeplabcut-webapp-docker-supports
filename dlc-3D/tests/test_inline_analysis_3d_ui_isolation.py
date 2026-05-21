"""Static guards for the 3D Inline Analysis card.

Cloned from viewer_3d.js / card_viewer_3d.html with va*->ia* rename, plus a
stereo analysis-dispatch IIFE. These parse the source files directly (no
runtime). See docs/superpowers/specs/2026-05-20-3d-inline-analysis-design.md.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS   = ROOT / "src" / "static" / "inline_analysis_3d.js"
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
PAGE = ROOT / "src" / "templates" / "dlc_3d.html"


def test_files_exist():
    assert JS.is_file() and CARD.is_file()


def test_no_va_identifier_leaks_in_clone():
    src = JS.read_text()
    import re
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
    import re
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

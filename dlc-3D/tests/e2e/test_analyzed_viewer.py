"""E2E tests for the dlc-3D analyzed frame/video viewer."""
import pytest

OPEN_BTN_TEXT = "View Analyzed"  # nav button label in base.html


def _open_card(page):
    page.click(f"button:has-text('{OPEN_BTN_TEXT}')")
    page.wait_for_selector("#view-analyzed-3d-card:not(.hidden)", timeout=5000)


def test_card_opens_and_lists_project_content(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    # Project Content tab is the default; list should populate.
    page.wait_for_selector("#va3d-content-list a, #va3d-content-list .explorer-empty",
                           timeout=10000)
    # Must NOT be the "Loading…" placeholder anymore.
    initial_text = page.text_content("#va3d-content-list")
    assert "Loading…" not in initial_text
    # Positive check: list either has entries or shows the explicit empty state
    assert "explorer-empty" in page.inner_html("#va3d-content-list") or \
           page.query_selector("#va3d-content-list a") is not None


def test_close_button_hides_card(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    page.click("#btn-close-view-analyzed-3d")
    page.wait_for_selector("#view-analyzed-3d-card.hidden", state="attached", timeout=2000)


SYNC_VIDEO_DIR = (
    "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/042426"
)
SYNC_VIDEO_HINT = "OM-2_cam0_20260424"  # picks the cam0 video from the OM-2 fixture


def _select_sync_video(page):
    """Navigate Browse Folders to the OM-2 dir and click the cam0 video."""
    # Switch to Browse Folders tab
    page.click("#va3d-tab-browse")
    page.wait_for_selector("#va3d-tab-browse-panel:not(.hidden)", timeout=2000)
    # Type the directory into the breadcrumb and Enter
    page.fill("#va3d-browse-breadcrumb", SYNC_VIDEO_DIR)
    page.press("#va3d-browse-breadcrumb", "Enter")
    # Show videos that lack h5 too (OM-2 cam videos may not have h5 in this dir)
    if page.is_checked("#va3d-browse-hide-no-h5"):
        page.uncheck("#va3d-browse-hide-no-h5")
    page.wait_for_selector(
        f"#va3d-browse-list .fe-video-item[data-has-h5]:has-text('{SYNC_VIDEO_HINT}')",
        timeout=10000,
    )
    page.click(f"#va3d-browse-list .fe-video-item[data-has-h5]:has-text('{SYNC_VIDEO_HINT}')")
    page.wait_for_function(
        "() => window.__va3dController && window.__va3dController.tiles.length > 0",
        timeout=10000,
    )


def test_sync_cam_auto_on_when_sibling_exists(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    # Wait for sibling probe + tile creation
    page.wait_for_function(
        "() => window.__va3dController.tiles.length === 2",
        timeout=5000,
    )
    assert page.is_checked("#va3d-sync-cam")
    tiles = page.query_selector_all("#va3d-tile-row .va3d-tile")
    assert len(tiles) == 2


def test_sync_cam_toggle_collapses_to_single_tile(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    page.uncheck("#va3d-sync-cam")
    page.wait_for_function("() => window.__va3dController.tiles.length === 1", timeout=2000)


def test_seek_advances_both_tiles(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    # Wait for both tiles' first frames to load
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-frame-img'))"
        ".every(img => img.complete && img.naturalWidth > 0)",
        timeout=10000,
    )
    # Click the next-frame button several times; both tile imgs should advance
    src_before = page.evaluate(
        "() => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-frame-img')).map(i => i.src)"
    )
    for _ in range(3):
        page.click("#va3d-btn-next")
    page.wait_for_function(
        "(prev) => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-frame-img'))"
        ".every((img, i) => img.src !== prev[i])",
        arg=src_before, timeout=5000,
    )
    # Both tiles must agree on the controller's currentFrame
    assert page.evaluate("() => window.__va3dController.currentFrame") > 0


def test_per_tile_size_slider_updates_flex_grow(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    # Drag tile-1's slider to 200%
    page.evaluate("""() => {
      const s = document.querySelectorAll('#va3d-tile-row .va3d-tile-size')[1];
      s.value = 200;
      s.dispatchEvent(new Event('input', {bubbles:true}));
    }""")
    weights = page.evaluate(
      "() => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-tile')).map(t => t.style.flexGrow)"
    )
    assert weights == ['100', '200']
    # Click Equalize, both should return to 100
    page.click("#va3d-equalize-btn")
    weights = page.evaluate(
      "() => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-tile')).map(t => t.style.flexGrow)"
    )
    assert weights == ['100', '100']


def test_primary_layer_pairs_to_both_tiles(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    # Toggle overlay on
    page.check("#va3d-overlay-toggle")
    # Pick the first option in the primary select (any cam0 h5 from the OM-2 fixture)
    has_h5 = page.evaluate("() => document.querySelectorAll('#va3d-overlay-primary-select option').length > 1")
    if not has_h5:
        pytest.skip("OM-2 fixture has no analyzed h5 to pick")
    page.evaluate("""() => {
      const s = document.getElementById('va3d-overlay-primary-select');
      s.selectedIndex = 1;
      s.dispatchEvent(new Event('change', {bubbles:true}));
    }""")
    # Wait until the controller has assigned a primary path to each tile (or set a pill)
    page.wait_for_function(
      "() => window.__va3dController.tiles.every(t => t.primaryH5Path !== null || t.pillEl.textContent.includes('no sibling'))",
      timeout=5000,
    )
    states = page.evaluate(
      "() => window.__va3dController.tiles.map(t => ({path: t.primaryH5Path, pill: t.pillEl.textContent}))"
    )
    # cam0 must have a path; cam1 must have either a path or the pill text
    assert states[0]['path'], states
    assert states[1]['path'] or 'no sibling h5' in states[1]['pill'], states


def test_both_cams_checkbox_default_checked_in_sync(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    page.check("#va3d-curation-toggle")
    assert page.is_visible("#va3d-both-cams-label")
    assert page.is_checked("#va3d-both-cams")


def test_extract_frame_calls_endpoint_per_cam(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    page.check("#va3d-curation-toggle")
    # Intercept the curator endpoint
    calls = []

    def _intercept(route):
        calls.append(route.request.post_data_json)
        route.fulfill(
            status=201,
            content_type="application/json",
            body='{"saved":"x.png","folder":"f","frame_count":1,"duplicate":false}',
        )

    page.route("**/dlc/curator/extract-frame", _intercept)
    try:
        page.click("#va3d-extract-frame-btn")
        # Deterministic wait: poll until we have both calls (cap at ~2s)
        for _ in range(20):
            if len(calls) >= 2:
                break
            page.wait_for_timeout(100)
    finally:
        page.unroute("**/dlc/curator/extract-frame")
    assert len(calls) >= 2, f"expected 2 endpoint calls, got {len(calls)}: {calls}"
    # Sibling sends video_name in 'video' mode and video_path in 'browse-video' mode
    video_fields = [(c or {}).get("video_path") or (c or {}).get("video_name") for c in calls]
    distinct = set(v for v in video_fields if v)
    assert len(distinct) >= 2, f"expected per-cam videos in calls, got: {video_fields!r}"


def test_marker_edit_banner_uses_split_format_in_sync_mode(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    # Programmatically inject a pending edit on tile 0 to make the banner appear.
    # The refresh helper reads from Controller.tiles[*].pendingEdits and renders
    # the cam0/cam1 split when there are 2 tiles.
    page.evaluate("""() => {
      window.__va3dController.tiles[0].pendingEdits.set(0, {});
      if (typeof window.__va3dRefreshMarkerBanner === 'function') {
        window.__va3dRefreshMarkerBanner();
      }
    }""")
    text = page.text_content("#va3d-marker-edit-count")
    assert "cam0:" in text and "cam1:" in text, f"Banner text was: {text!r}"


def test_tile0_canvas_wrap_does_not_overflow_into_tile1(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    # Wait for both tile imgs to actually load (otherwise canvas-wrap height is 0)
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-frame-img'))"
        ".every(i => i.complete && i.naturalWidth > 0)",
        timeout=15000,
    )
    page.wait_for_timeout(300)  # let layout settle after img load + ResizeObserver
    layout = page.evaluate(
        """() => {
          const tiles = Array.from(document.querySelectorAll('#va3d-tile-row .va3d-tile'));
          return tiles.map(t => {
            const tr = t.getBoundingClientRect();
            const w  = t.querySelector('.va3d-tile-canvas-wrap').getBoundingClientRect();
            return {tileX: tr.x, tileW: tr.width, wrapX: w.x, wrapW: w.width};
          });
        }"""
    )
    assert len(layout) == 2, layout
    # tile-0's canvas-wrap must not extend past tile-0's right edge
    t0 = layout[0]
    assert t0["wrapW"] <= t0["tileW"] + 4, (  # 4px slack for borders
        f"tile-0 canvas-wrap width {t0['wrapW']} exceeds tile width {t0['tileW']} - overflow"
    )
    # tile-0 wrap must not start before tile-0 OR extend into tile-1
    t1 = layout[1]
    assert t0["wrapX"] + t0["wrapW"] <= t1["tileX"] + 1, (
        f"tile-0 wrap right edge {t0['wrapX'] + t0['wrapW']} overlaps tile-1 start {t1['tileX']}"
    )

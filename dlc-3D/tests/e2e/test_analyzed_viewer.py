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


def test_extract_both_cams_routes_through_dlc3d_save_frame(page, base_url):
    """In sync+Both-cams mode, Extract Frame must call /dlc-3d/save-frame
    (single atomic call with extract_sibling=true) — not /dlc/curator/extract-frame."""
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    page.check("#va3d-curation-toggle")
    assert page.is_checked("#va3d-both-cams")

    save_calls = []
    curator_calls = []
    def _capture_save(route):
        save_calls.append(route.request.post_data_json)
        route.fulfill(status=201, content_type="application/json",
                      body='{"saved":["img_cam0_0001_00000.png","img_cam1_0001_00000.png"],"skipped":[],"calibration_copied":true,"session_folder":"labeled-data/test"}')
    def _capture_curator(route):
        curator_calls.append(route.request.post_data_json)
        route.fulfill(status=201, content_type="application/json", body='{"saved":[]}')
    page.route("**/dlc-3d/save-frame", _capture_save)
    page.route("**/dlc/curator/extract-frame", _capture_curator)
    try:
        page.click("#va3d-extract-frame-btn")
        for _ in range(20):
            if save_calls:
                break
            page.wait_for_timeout(100)
    finally:
        page.unroute("**/dlc-3d/save-frame")
        page.unroute("**/dlc/curator/extract-frame")
    assert len(save_calls) == 1, f"expected 1 /dlc-3d/save-frame call, got {len(save_calls)}: {save_calls}"
    body = save_calls[0]
    assert body.get("extract_sibling") is True, body
    assert body.get("primary_video") and body.get("sibling_video"), body
    assert body.get("primary_frame_number") == 0, body
    assert body.get("sibling_frame_number") == 0, body
    # And the legacy curator endpoint must NOT have been called in Both-cams mode
    assert not curator_calls, f"unexpected /dlc/curator/extract-frame call: {curator_calls}"


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


def test_sibling_tile_renders_markers_for_primary_layer(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    page.check("#va3d-overlay-toggle")
    has_h5 = page.evaluate("() => document.querySelectorAll('#va3d-overlay-primary-select option').length > 1")
    if not has_h5:
        pytest.skip("OM-2 fixture has no analyzed h5")
    page.evaluate("""() => {
      const s = document.getElementById('va3d-overlay-primary-select');
      s.selectedIndex = 1;
      s.dispatchEvent(new Event('change', {bubbles:true}));
    }""")
    # Wait for tile-1's primaryH5Path to be resolved (or pill to indicate missing)
    page.wait_for_function(
      "() => window.__va3dController.tiles.every(t => t.primaryH5Path !== null"
      " || (t.pillEl && t.pillEl.textContent && t.pillEl.textContent.includes('no sibling')))",
      timeout=10000,
    )
    # If sibling has no h5, this test verifies nothing useful — skip
    has_sibling_h5 = page.evaluate("() => window.__va3dController.tiles[1].primaryH5Path !== null")
    if not has_sibling_h5:
        pytest.skip("OM-2 fixture sibling h5 not present for this video")
    # Wait for both tile imgs to load
    page.wait_for_function(
      "() => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-frame-img'))"
      ".every(i => i.complete && i.naturalWidth > 0)",
      timeout=15000,
    )
    page.wait_for_timeout(500)  # let initial pose fetch + draw settle
    # Drop the global threshold to 0 so even low-confidence poses are returned;
    # the OM-2 fixture's cam1 h5 has very few high-confidence frames so the
    # default 0.60 threshold yields empty results at most frames.
    page.evaluate("""() => {
      const t = document.getElementById('va3d-overlay-threshold');
      t.value = '0';
      t.dispatchEvent(new Event('input', {bubbles:true}));
    }""")
    page.wait_for_timeout(500)
    # Tile-0's _vaLoadFrame triggers a re-render which propagates to siblings
    # via _vaRenderAllSiblings(). Probe a handful of frames and accept the
    # first one with markers.
    nonzero = 0
    last_diag = None
    for n in [0, 10, 50, 100, 250, 500, 1000]:
        page.evaluate(f"() => window.__va3dController.seek({n})")
        page.wait_for_function(
            "() => !window.__va3dController.tiles[1].layers[0]"
            " || window.__va3dController.tiles[1].layers[0].posesCache.has(window.__va3dController.currentFrame)",
            timeout=5000,
        )
        page.wait_for_timeout(200)
        last_diag = page.evaluate("""() => {
          const tile = window.__va3dController.tiles[1];
          const c = tile.canvasEl;
          const f = window.__va3dController.currentFrame;
          const cached = tile.layers[0] ? tile.layers[0].posesCache.get(f) : null;
          let n = 0;
          if (c && c.width && c.height) {
            const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            for (let i = 3; i < data.length; i += 4) if (data[i] > 0) n++;
          }
          return {nonzero: n, frame: f, n_poses: cached ? (cached.poses||[]).length : 0};
        }""")
        if last_diag['nonzero'] > 0:
            nonzero = last_diag['nonzero']
            break
    assert nonzero > 0, f"Tile-1 overlay canvas never showed markers across probed frames; last={last_diag}"


def test_both_cams_label_hidden_when_curation_off(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    # Curation toggle is OFF by default — the Both-cams label must be hidden
    assert not page.is_visible("#va3d-both-cams-label")
    # Now toggle curation on — Both-cams label should appear
    page.check("#va3d-curation-toggle")
    assert page.is_visible("#va3d-both-cams-label")
    # Toggle curation off — label should hide again
    page.uncheck("#va3d-curation-toggle")
    assert not page.is_visible("#va3d-both-cams-label")

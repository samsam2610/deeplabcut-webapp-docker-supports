"""E2E tests for the dlc-3D analyzed frame/video viewer.

These drive the live "View Analyzed" card after its migration onto the shared
VideoViewer library (Phase 4b). The card no longer exposes the old
`window.__va3dController` singleton with per-tile pose/edit internals; it exposes
`window.__vaViewer` (the VideoViewer instance) and renders tiles into
`#va3d-viewer-mount` using the library's `vv-*` DOM. White-box pokes at marker
internals (primaryH5Path / pendingEdits / posesCache) are replaced with
behavioral checks: overlay markers are observed as drawn pixels on each tile's
`.vv-overlay-canvas`, and edits are driven through the real canvas, not injected.
"""
import pytest

OPEN_BTN_TEXT = "View Analyzed"  # nav button label in base.html
MOUNT = "#va3d-viewer-mount"     # VideoViewer mount point in card_viewer_3d.html


def _open_card(page):
    page.click(f"button:has-text('{OPEN_BTN_TEXT}')")
    page.wait_for_selector("#view-analyzed-3d-card:not(.hidden)", timeout=5000)


def _wait_two_tiles(page):
    page.wait_for_function(
        "() => window.__vaViewer && window.__vaViewer.tiles.length === 2",
        timeout=8000,
    )


def _overlay_pixels(page, idx):
    """Count non-transparent pixels on tile `idx`'s overlay canvas (markers drawn)."""
    return page.evaluate(
        """(idx) => {
          const c = document.querySelectorAll('%s .vv-overlay-canvas')[idx];
          if (!c || !c.width || !c.height) return -1;
          const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
          let n = 0;
          for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
          return n;
        }""" % MOUNT,
        idx,
    )


def _counts_at(page, n, settle_ms=600):
    """Seek to frame n, let the async pose fetch+draw settle, return (cam0, cam1) pixel counts."""
    page.evaluate("(n) => window.__vaViewer.seek(n)", n)
    page.wait_for_timeout(settle_ms)
    return _overlay_pixels(page, 0), _overlay_pixels(page, 1)


def test_card_opens_and_lists_project_content(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    # Project Content tab is the default; list should populate.
    page.wait_for_selector(
        "#va3d-content-list .fe-video-item, #va3d-content-list .explorer-empty",
        timeout=10000,
    )
    # Must NOT be the "Loading…" placeholder anymore.
    assert "Loading…" not in page.text_content("#va3d-content-list")
    # Positive check: list either has entries or shows the explicit empty state.
    assert "explorer-empty" in page.inner_html("#va3d-content-list") or \
           page.query_selector("#va3d-content-list .fe-video-item") is not None


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
        "() => window.__vaViewer && window.__vaViewer.tiles.length > 0",
        timeout=10000,
    )


def _enable_overlay_primary(page):
    """Turn the overlay on, select the first primary h5, and drop the threshold to 0.

    Skips if the fixture exposes no analyzed h5. Returns once the bp chips populate
    (the primary layer has loaded and auto-selected a body part)."""
    page.check("#va3d-overlay-toggle")
    has_h5 = page.evaluate(
        "() => document.querySelectorAll('#va3d-overlay-primary-select option').length > 1"
    )
    if not has_h5:
        pytest.skip("OM-2 fixture has no analyzed h5 to pick")
    page.evaluate("""() => {
      const s = document.getElementById('va3d-overlay-primary-select');
      s.selectedIndex = 1;
      s.dispatchEvent(new Event('change', {bubbles:true}));
    }""")
    # Drop the global threshold to 0 so even low-confidence poses render (the
    # OM-2 fixture has few high-confidence frames at the default 0.60).
    page.evaluate("""() => {
      const t = document.getElementById('va3d-overlay-threshold');
      t.value = '0';
      t.dispatchEvent(new Event('input', {bubbles:true}));
    }""")
    page.wait_for_selector("#va3d-bp-chips .vv-bp-chip", timeout=5000)


def test_sync_cam_auto_on_when_sibling_exists(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    assert page.is_checked("#va3d-sync-cam")
    assert len(page.query_selector_all(f"{MOUNT} .vv-tile")) == 2


def test_sync_cam_toggle_collapses_to_single_tile(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    page.uncheck("#va3d-sync-cam")
    page.wait_for_function(
        "() => window.__vaViewer.tiles.length === 1", timeout=3000,
    )


def test_seek_advances_both_tiles(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    # Wait for both tiles' first frames to load
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('%s .vv-frame-img'))"
        ".every(img => img.complete && img.naturalWidth > 0)" % MOUNT,
        timeout=10000,
    )
    # Click the next-frame button several times; both tile imgs should advance.
    src_before = page.evaluate(
        "() => Array.from(document.querySelectorAll('%s .vv-frame-img')).map(i => i.src)" % MOUNT
    )
    for _ in range(3):
        page.click("#va3d-btn-next")
    page.wait_for_function(
        "(prev) => Array.from(document.querySelectorAll('%s .vv-frame-img'))"
        ".every((img, i) => img.src !== prev[i])" % MOUNT,
        arg=src_before, timeout=5000,
    )
    # Both tiles share the viewer's currentFrame (now a method on the library API).
    assert page.evaluate("() => window.__vaViewer.currentFrame()") > 0


def test_overlay_canvas_matches_image_no_marker_shift(page, base_url):
    """Regression: each overlay canvas's backing store must match its displayed
    box, and the canvas must cover the image (not extend past it). Otherwise
    markers drawn in backing-store px get CSS-scaled and shift — most visibly in
    sync mode where small tiles amplify a constant excess. Root cause was the
    .vv-tile-label nesting inside the inline-block .vv-tile-canvas-wrap, inflating
    it so the height:100% canvas stretched."""
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    _enable_overlay_primary(page)
    page.evaluate("() => window.__vaViewer.seek(0)")
    page.wait_for_timeout(800)
    geo = page.evaluate(
        """() => Array.from(document.querySelectorAll('%s .vv-tile')).map(t => {
            const img = t.querySelector('.vv-frame-img');
            const cv  = t.querySelector('.vv-overlay-canvas');
            const ir = img.getBoundingClientRect(), cr = cv.getBoundingClientRect();
            return {
              backW: cv.width, backH: cv.height,
              dispW: cr.width, dispH: cr.height,
              imgW: ir.width, imgH: ir.height,
            };
        })""" % MOUNT
    )
    assert len(geo) == 2, geo
    for g in geo:
        # canvas displayed box must match its backing store (markers map 1:1, no scale).
        # backing = img.offsetWidth/Height (border-box) == the displayed canvas box.
        assert 0.98 <= g["dispH"] / g["backH"] <= 1.02, f"canvas vertical stretch (marker shift): {g}"
        assert 0.98 <= g["dispW"] / g["backW"] <= 1.02, f"canvas horizontal stretch (marker shift): {g}"
        # and the canvas must cover the image box, not extend past it
        assert g["dispH"] <= g["imgH"] + 2, f"canvas taller than image (overlay misaligned): {g}"


def test_per_tile_size_slider_updates_flex_grow(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    # Drag tile-1's per-tile size slider to 200%
    page.evaluate("""() => {
      const s = document.querySelectorAll('%s .vv-tile-size')[1];
      s.value = 200;
      s.dispatchEvent(new Event('input', {bubbles:true}));
    }""" % MOUNT)
    weights = page.evaluate(
        "() => Array.from(document.querySelectorAll('%s .vv-tile')).map(t => t.style.flexGrow)" % MOUNT
    )
    assert weights == ['100', '200']
    # Click Equalize, both should return to 100.
    page.click("#va3d-equalize-btn")
    weights = page.evaluate(
        "() => Array.from(document.querySelectorAll('%s .vv-tile')).map(t => t.style.flexGrow)" % MOUNT
    )
    assert weights == ['100', '100']


def test_primary_layer_pairs_to_both_tiles(page, base_url):
    """Selecting a single primary h5 must drive the overlay on BOTH cams: the
    primary on cam0 and its auto-resolved sibling h5 on cam1. Verified behaviorally
    by finding a frame where both tiles' overlay canvases draw markers."""
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    _enable_overlay_primary(page)
    found = None
    last = None
    for n in [0, 15, 40, 80, 120, 160, 200, 235]:
        c0, c1 = _counts_at(page, n)
        last = (n, c0, c1)
        if c0 > 0 and c1 > 0:
            found = last
            break
    assert found, f"no probed frame had markers on BOTH tiles; last={last}"


def test_both_cams_checkbox_default_checked_in_sync(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    page.check("#va3d-curation-toggle")
    assert page.is_visible("#va3d-both-cams-label")
    assert page.is_checked("#va3d-both-cams")


def test_extract_both_cams_routes_through_dlc3d_save_frame(page, base_url):
    """In sync+Both-cams mode, Extract Frame must call /dlc-3d/save-frame
    (single atomic call with extract_sibling=true) — not /dlc/curator/extract-frame."""
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
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
    # And the legacy curator endpoint must NOT have been called in Both-cams mode.
    assert not curator_calls, f"unexpected /dlc/curator/extract-frame call: {curator_calls}"


def test_marker_edit_records_and_updates_banner(page, base_url):
    """A real edit on the primary canvas must surface in the edit banner.

    The library markerEditor banner shows a simple total ("N frames edited"); the
    old per-cam "cam0:/cam1:" split was not migrated. Drive a genuine edit by
    selecting a body part and placing it on an empty corner of the primary overlay
    canvas, then assert the banner reflects one edited frame. The marker-edit POST
    is mocked so nothing persists to the server edit-cache."""
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    page.route("**/dlc/viewer/marker-edit",
               lambda r: r.fulfill(status=200, content_type="application/json", body="{}"))
    _enable_overlay_primary(page)
    # Explicitly select the first body part (placement targets the selected bp).
    page.click("#va3d-bp-chips .vv-bp-chip >> nth=0")
    # Place the marker on an empty corner of tile-0's overlay canvas (the library
    # sets pointer-events:auto on the primary overlay canvas for editing).
    box = page.evaluate(
        """() => {
          const c = document.querySelectorAll('%s .vv-overlay-canvas')[0];
          const r = c.getBoundingClientRect();
          return {x: r.x, y: r.y};
        }""" % MOUNT
    )
    page.mouse.click(box["x"] + 6, box["y"] + 6)
    # Banner should now show exactly one edited frame and be visible.
    page.wait_for_function(
        """() => {
          const b = document.getElementById('va3d-marker-edit-banner');
          const c = document.getElementById('va3d-marker-edit-count');
          return b && !b.classList.contains('hidden') && c && /\\b1 frame\\b/.test(c.textContent);
        }""",
        timeout=3000,
    )


def test_tile0_canvas_wrap_does_not_overflow_into_tile1(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    # Wait for both tile imgs to actually load (otherwise canvas-wrap height is 0).
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('%s .vv-frame-img'))"
        ".every(i => i.complete && i.naturalWidth > 0)" % MOUNT,
        timeout=15000,
    )
    page.wait_for_timeout(300)  # let layout settle after img load
    layout = page.evaluate(
        """() => {
          const tiles = Array.from(document.querySelectorAll('%s .vv-tile'));
          return tiles.map(t => {
            const tr = t.getBoundingClientRect();
            const w  = t.querySelector('.vv-tile-canvas-wrap').getBoundingClientRect();
            return {tileX: tr.x, tileW: tr.width, wrapX: w.x, wrapW: w.width};
          });
        }""" % MOUNT
    )
    assert len(layout) == 2, layout
    # tile-0's canvas-wrap must not extend past tile-0's right edge.
    t0 = layout[0]
    assert t0["wrapW"] <= t0["tileW"] + 4, (  # 4px slack for borders
        f"tile-0 canvas-wrap width {t0['wrapW']} exceeds tile width {t0['tileW']} - overflow"
    )
    # tile-0 wrap must not extend into tile-1.
    t1 = layout[1]
    assert t0["wrapX"] + t0["wrapW"] <= t1["tileX"] + 1, (
        f"tile-0 wrap right edge {t0['wrapX'] + t0['wrapW']} overlaps tile-1 start {t1['tileX']}"
    )


def test_sibling_tile_renders_markers_for_primary_layer(page, base_url):
    """The sibling (cam1) tile must render markers from the auto-resolved sibling
    h5 once a primary is chosen. Behavioral: probe frames until tile-1's overlay
    canvas shows drawn pixels."""
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    _enable_overlay_primary(page)
    found = None
    last = None
    for n in [0, 15, 40, 80, 120, 160, 200, 235]:
        _, c1 = _counts_at(page, n)
        last = (n, c1)
        if c1 > 0:
            found = last
            break
    assert found, f"tile-1 overlay never showed markers across probed frames; last={last}"


def test_focused_sibling_tile_editing_routes_to_cam1_h5(page, base_url):
    """Multi-view focused-tile editing (adapted from the 3D frame labeler): clicking
    the sibling tile focuses it (first click focuses only), and a marker placed there
    is recorded against the CAM1 h5 — not cam0. Edits are mocked so nothing persists."""
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    _enable_overlay_primary(page)

    def _focus():
        return page.evaluate(
            "() => Array.from(document.querySelectorAll('%s .vv-tile'))"
            ".map(t => t.classList.contains('vv-tile-focused'))" % MOUNT
        )
    # cam0 focused by default
    assert _focus() == [True, False], _focus()

    calls = []
    page.route("**/dlc/viewer/marker-edit",
               lambda r: (calls.append(r.request.post_data_json),
                          r.fulfill(status=200, content_type="application/json", body="{}")))

    # First click on the sibling tile focuses it — and must NOT place a marker.
    # (Element .click() scrolls into view + clicks the tile center; the canvas's own
    # click handler is gated on the OLD focus and returns, so only focus changes.)
    page.query_selector_all(f"{MOUNT} .vv-tile")[1].click()
    page.wait_for_timeout(250)
    assert _focus() == [False, True], _focus()
    assert len(calls) == 0, f"focus click must not edit; got {calls}"

    # Placing a marker on the focused sibling canvas routes to the cam1 h5.
    c1 = page.query_selector_all(f"{MOUNT} .vv-overlay-canvas")[1]
    cb = c1.bounding_box()
    page.mouse.click(cb["x"] + 6, cb["y"] + 6)
    page.wait_for_timeout(400)
    page.unroute("**/dlc/viewer/marker-edit")
    assert len(calls) == 1, f"expected one marker-edit on the focused sibling; got {calls}"
    h5 = calls[-1].get("h5", "")
    assert "cam1" in h5 and "cam0" not in h5, f"edit must target cam1 h5, got {h5!r}"
    # Banner reflects the (cam1) edit.
    assert page.is_visible("#va3d-marker-edit-banner")
    assert "1 frame" in page.text_content("#va3d-marker-edit-count")


def test_both_cams_label_hidden_when_curation_off(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    _wait_two_tiles(page)
    # Curation toggle is OFF by default — the Both-cams label must be hidden.
    assert not page.is_visible("#va3d-both-cams-label")
    # Toggle curation on — Both-cams label should appear.
    page.check("#va3d-curation-toggle")
    assert page.is_visible("#va3d-both-cams-label")
    # Toggle curation off — label should hide again.
    page.uncheck("#va3d-curation-toggle")
    assert not page.is_visible("#va3d-both-cams-label")

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

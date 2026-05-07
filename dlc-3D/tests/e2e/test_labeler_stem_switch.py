"""Frame labeler must reconcile sync state when the user switches stems."""
import pytest


def _open_labeler(page):
    page.click("#btn-open-frame-labeler")
    page.wait_for_selector("#frame-labeler-card:not(.hidden)", timeout=5000)
    page.wait_for_function("() => document.querySelectorAll('#fl3d-stem-select option').length > 1", timeout=10000)


def _pick_first_multi_cam_stem(page):
    """Cycle through stems until we find one whose sync label appears (>=2 cams)."""
    stems = page.evaluate("() => Array.from(document.querySelectorAll('#fl3d-stem-select option')).map(o => o.value).filter(v => v)")
    for v in stems:
        page.evaluate("(v) => { const s = document.getElementById('fl3d-stem-select'); s.value = v; s.dispatchEvent(new Event('change', {bubbles:true})); }", v)
        page.wait_for_timeout(400)
        if page.evaluate("() => { const l = document.getElementById('fl3d-sync-frame-label'); return l && getComputedStyle(l).display !== 'none'; }"):
            return v
    return None


def _pick_first_single_cam_stem(page, exclude):
    stems = page.evaluate("() => Array.from(document.querySelectorAll('#fl3d-stem-select option')).map(o => o.value).filter(v => v)")
    for v in stems:
        if v == exclude:
            continue
        page.evaluate("(v) => { const s = document.getElementById('fl3d-stem-select'); s.value = v; s.dispatchEvent(new Event('change', {bubbles:true})); }", v)
        page.wait_for_timeout(400)
        is_multi = page.evaluate("() => window.__fl3d && window.__fl3d.camSet && window.__fl3d.camSet.length >= 2")
        if not is_multi:
            return v
    return None


def test_switch_from_multi_cam_with_sync_on_to_single_cam_resets_sync(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_labeler(page)

    multi = _pick_first_multi_cam_stem(page)
    if not multi:
        pytest.skip("No multi-cam stem in fixture")

    # Enable sync on the multi-cam stem
    page.check("#fl3d-sync-frame")
    page.wait_for_timeout(300)
    assert page.evaluate("() => document.querySelectorAll('#fl3d-canvas-row .fl3d-tile').length") == 2

    single = _pick_first_single_cam_stem(page, exclude=multi)
    if not single:
        pytest.skip("No single-cam stem to switch to")

    # Switch to single-cam stem
    page.evaluate("(v) => { const s = document.getElementById('fl3d-stem-select'); s.value = v; s.dispatchEvent(new Event('change', {bubbles:true})); }", single)
    page.wait_for_timeout(800)

    # Sync should be off, sibling tile should be gone, only the primary tile remains
    assert not page.is_checked("#fl3d-sync-frame"), "sync should auto-disable when switching to single-cam stem"
    tiles = page.evaluate("() => document.querySelectorAll('#fl3d-canvas-row .fl3d-tile').length")
    assert tiles == 1, f"expected 1 tile after switch to single-cam, got {tiles}"
    siblings = page.evaluate("() => document.querySelectorAll('#fl3d-canvas-row .fl3d-tile-sibling').length")
    assert siblings == 0, f"sibling tile should be torn down, got {siblings}"
    # Loading state should not be stuck visible
    loading = page.evaluate("() => { const el = document.getElementById('fl3d-canvas-loading'); return el && !el.classList.contains('hidden'); }")
    # We don't strictly assert loading is hidden (it may briefly show during img load), but allow up to 5s for it to clear
    if loading:
        page.wait_for_function("() => document.getElementById('fl3d-canvas-loading').classList.contains('hidden')", timeout=5000)

"""e2e tests for per-tile viewer size sliders + Equalize button + sync-mode 500% global max.

Mirrors the conftest pattern from test_sync_frame.py (autouse session activation,
om2_fixture_present skip).
"""
import re
import pytest
from playwright.sync_api import Page, expect

SESSION = "OM-2_20260424"


@pytest.fixture(autouse=True)
def _open_labeler(page: Page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-frame-labeler").click()
    page.locator("#frame-labeler-card").wait_for(state="visible")
    page.wait_for_function(
        f"() => Array.from(document.getElementById('fl3d-stem-select').options)"
        f".some(o => o.value === '{SESSION}')",
        timeout=10000,
    )
    page.locator("#fl3d-stem-select").select_option(SESSION)
    page.wait_for_function(
        '() => document.querySelector("#fl3d-canvas-row .fl3d-tile")?.dataset?.fname'
    )


def _enable_sync(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")


# ---------- Group A: Visibility gating ----------

def test_a1_per_tile_sliders_hidden_when_sync_off(page: Page):
    sliders = page.locator("#fl3d-canvas-row .fl3d-tile-size")
    assert sliders.count() >= 1
    for i in range(sliders.count()):
        expect(sliders.nth(i)).to_be_hidden()


def test_a2_equalize_hidden_when_sync_off(page: Page):
    expect(page.locator("#fl3d-equalize-btn")).to_be_hidden()


def test_a3_per_tile_sliders_visible_when_sync_on(page: Page):
    _enable_sync(page)
    sliders = page.locator("#fl3d-canvas-row .fl3d-tile-size")
    cam_count = page.evaluate("window.__fl3d.camSet.length")
    assert sliders.count() == cam_count
    for i in range(sliders.count()):
        expect(sliders.nth(i)).to_be_visible()


def test_a4_equalize_visible_when_sync_on(page: Page):
    _enable_sync(page)
    expect(page.locator("#fl3d-equalize-btn")).to_be_visible()


# ---------- Group B: Global slider max ----------

def test_b1_global_max_300_when_sync_off(page: Page):
    assert page.eval_on_selector("#fl3d-zoom", "el => el.max") == "300"


def test_b2_global_max_500_when_sync_on(page: Page):
    _enable_sync(page)
    assert page.eval_on_selector("#fl3d-zoom", "el => el.max") == "500"


def test_b3_global_value_clamped_when_sync_off(page: Page):
    _enable_sync(page)
    page.locator("#fl3d-zoom").evaluate(
        "(el) => { el.value = '450'; el.dispatchEvent(new Event('input')); }"
    )
    page.locator("#fl3d-sync-frame").uncheck()
    page.wait_for_function("window.__fl3d.syncOn === false")
    assert page.eval_on_selector("#fl3d-zoom", "el => el.max") == "300"
    assert int(page.eval_on_selector("#fl3d-zoom", "el => el.value")) <= 300


# ---------- Group C: Per-tile weight redistribution ----------

def test_c1_default_weights_equal(page: Page):
    _enable_sync(page)
    weights = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => parseInt(t.style.flexGrow || t.dataset.weight || '100', 10))",
    )
    assert all(w == 100 for w in weights), f"expected all 100, got {weights}"


def test_c2_drag_one_slider_grows_that_tile(page: Page):
    _enable_sync(page)
    tiles = page.locator("#fl3d-canvas-row .fl3d-tile")
    n = tiles.count()
    assert n >= 2

    widths_before = [
        tiles.nth(i).evaluate("el => el.getBoundingClientRect().width") for i in range(n)
    ]

    # Drag tile 0's slider to 300
    tiles.nth(0).locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '300'; el.dispatchEvent(new Event('input')); }"
    )

    widths_after = [
        tiles.nth(i).evaluate("el => el.getBoundingClientRect().width") for i in range(n)
    ]
    assert widths_after[0] > widths_before[0], "tile 0 should grow"
    for i in range(1, n):
        assert widths_after[i] < widths_before[i], f"tile {i} should shrink"


def test_c3_row_width_unchanged_when_redistributing(page: Page):
    _enable_sync(page)
    row = page.locator("#fl3d-canvas-row")
    row_w_before = row.evaluate("el => el.getBoundingClientRect().width")
    page.locator("#fl3d-canvas-row .fl3d-tile").first.locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '250'; el.dispatchEvent(new Event('input')); }"
    )
    row_w_after = row.evaluate("el => el.getBoundingClientRect().width")
    # Row width may shift by sub-pixel rounding; assert within 2px.
    assert abs(row_w_after - row_w_before) <= 2


def test_c4_slider_label_updates(page: Page):
    _enable_sync(page)
    tile = page.locator("#fl3d-canvas-row .fl3d-tile").first
    tile.locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '175'; el.dispatchEvent(new Event('input')); }"
    )
    label_text = tile.locator(".fl3d-tile-size-val").inner_text()
    assert label_text.strip() == "175%"


# ---------- Group D: Equalize ----------

def test_d1_equalize_resets_all_weights(page: Page):
    _enable_sync(page)
    tiles = page.locator("#fl3d-canvas-row .fl3d-tile")
    # Skew weights
    tiles.nth(0).locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '300'; el.dispatchEvent(new Event('input')); }"
    )
    page.locator("#fl3d-equalize-btn").click()
    weights = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => parseInt(t.style.flexGrow, 10))",
    )
    assert all(w == 100 for w in weights), f"expected all 100, got {weights}"
    sliders_vals = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile-size",
        "els => els.map(e => parseInt(e.value, 10))",
    )
    assert all(v == 100 for v in sliders_vals)


# ---------- Group E: Sync toggle resets weights ----------

def test_e1_sync_off_then_on_resets_weights(page: Page):
    _enable_sync(page)
    page.locator("#fl3d-canvas-row .fl3d-tile").first.locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '275'; el.dispatchEvent(new Event('input')); }"
    )
    page.locator("#fl3d-sync-frame").uncheck()
    page.wait_for_function("window.__fl3d.syncOn === false")
    _enable_sync(page)
    weights = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => parseInt(t.style.flexGrow || '100', 10))",
    )
    assert all(w == 100 for w in weights), f"expected all 100 after sync re-enable, got {weights}"


# ---------- Group F: Marker placement still works after resize ----------

def test_f1_click_focused_tile_at_300pct_places_marker(page: Page):
    _enable_sync(page)
    # Pick first body part chip
    page.wait_for_function("document.querySelectorAll('#fl3d-bodypart-list .fl-bp-chip').length > 0")
    page.locator("#fl3d-bodypart-list .fl-bp-chip").first.click()
    bp = page.evaluate("window.__fl3d.selectedBp")
    assert bp

    # Resize the focused (primary) tile to 300%
    primary = page.locator("#fl3d-canvas-row .fl3d-tile.focused")
    primary.locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '300'; el.dispatchEvent(new Event('input')); }"
    )

    canvas = primary.locator("canvas.fl3d-tile-canvas")
    box = canvas.bounding_box()
    assert box
    # Click ~10% from top-left — labels (body parts) are typically in the
    # central region of the frame, so a corner click is unlikely to overlap
    # an existing marker (which would select it instead of placing a new one).
    page.mouse.click(box["x"] + box["width"] * 0.1, box["y"] + box["height"] * 0.1)

    primary_fname = primary.evaluate("t => t.dataset.fname")
    page.wait_for_function(
        f"window.__fl3d.dirtyFrames.includes('{primary_fname}')"
    )


# ---------- Group G: Sibling weight persists across frame nav ----------

def test_g1_sibling_weight_persists_across_frame_nav(page: Page):
    _enable_sync(page)
    sibling = page.locator("#fl3d-canvas-row .fl3d-tile.fl3d-tile-sibling").first
    sibling_cam = sibling.evaluate("t => t.dataset.cam")
    sibling.locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '250'; el.dispatchEvent(new Event('input')); }"
    )

    before_idx = page.evaluate("window.__fl3d.frameNumberIdx")
    page.locator("#fl3d-btn-next").click()
    page.wait_for_function(f"window.__fl3d.frameNumberIdx > {before_idx}")

    sibling_after = page.locator(
        f'#fl3d-canvas-row .fl3d-tile.fl3d-tile-sibling[data-cam="{sibling_cam}"]'
    )
    weight     = sibling_after.evaluate("t => parseInt(t.style.flexGrow || '100', 10)")
    slider_val = int(sibling_after.locator(".fl3d-tile-size").evaluate("e => e.value"))
    label_text = sibling_after.locator(".fl3d-tile-size-val").inner_text().strip()

    assert weight == 250, f"expected flex-grow 250 after frame nav, got {weight}"
    assert slider_val == 250, f"expected slider value 250, got {slider_val}"
    assert label_text == "250%", f"expected label '250%', got {label_text!r}"


def test_g2_primary_weight_persists_across_frame_nav(page: Page):
    """Regression guard: primary tile is preserved across renders, so its weight
    should survive frame nav even before the sibling-stash fix. Locks in that
    behavior so future refactors don't break it."""
    _enable_sync(page)
    primary = page.locator("#fl3d-canvas-row .fl3d-tile.focused")
    primary.locator(".fl3d-tile-size").evaluate(
        "(el) => { el.value = '175'; el.dispatchEvent(new Event('input')); }"
    )

    before_idx = page.evaluate("window.__fl3d.frameNumberIdx")
    page.locator("#fl3d-btn-next").click()
    page.wait_for_function(f"window.__fl3d.frameNumberIdx > {before_idx}")

    weight = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile:not(.fl3d-tile-sibling)",
        "t => parseInt(t.style.flexGrow || '100', 10)",
    )
    assert weight == 175, f"expected primary flex-grow 175 after frame nav, got {weight}"

"""e2e tests for Sync Frame — groups A (Visibility), B (Initial state),
C (Sync ON transition), D (Focus switching), E (Lock-step navigation),
F (Marker placement), G (Shared display controls), H (Save round-trip),
I (Clear Frame), J (Sync OFF transition), K (Window resize),
L (Refresh), M (Non-regression).

Fixture dependency: om2_fixture_present (conftest.py) probes the main webapp's
/dlc/project/labeled-frames endpoint and skips the whole module if the session
OM-2_20260424 is absent or has fewer than 2 cameras.
"""
import os
import re
import pytest
from playwright.sync_api import Page, expect

SESSION = "OM-2_20260424"


@pytest.fixture(autouse=True)
def _open_labeler(page: Page, base_url):
    """Project activation is handled by _active_dlc_project (conftest, autouse).
    This fixture just opens the Frame Labeler card and selects the test session.
    """
    page.goto(base_url)
    page.locator("#btn-open-frame-labeler").click()
    page.locator("#frame-labeler-card").wait_for(state="visible")
    # _flLoadStems fetches /dlc/project/labeled-frames after open-click;
    # wait for the SESSION option to actually appear before selecting.
    page.wait_for_function(
        f"() => Array.from(document.getElementById('fl3d-stem-select').options)"
        f".some(o => o.value === '{SESSION}')",
        timeout=10000,
    )
    page.locator("#fl3d-stem-select").select_option(SESSION)
    page.wait_for_function(
        '() => document.querySelector("#fl3d-canvas-row .fl3d-tile")?.dataset?.fname'
    )


def _focused_class_re():
    return re.compile(r"\bfocused\b")


# ---------- Group A: Visibility gate ----------

def test_a1_sync_checkbox_visible_when_two_cams(page: Page):
    expect(page.locator("#fl3d-sync-frame-label")).to_be_visible()
    cam_count = page.evaluate("window.__fl3d.camSet.length")
    assert cam_count >= 2


# ---------- Group B: Initial state with sync OFF ----------

def test_b1_sync_off_one_tile(page: Page):
    tiles = page.locator("#fl3d-canvas-row .fl3d-tile")
    assert tiles.count() == 1


def test_b2_sole_tile_focused(page: Page):
    tile = page.locator("#fl3d-canvas-row .fl3d-tile").first
    expect(tile).to_have_class(_focused_class_re())


def test_b3_tile_width_matches_card_at_100pct(page: Page):
    card_w = page.evaluate("document.getElementById('frame-labeler-card').clientWidth")
    tile_w = page.evaluate(
        "document.querySelector('#fl3d-canvas-row .fl3d-tile').getBoundingClientRect().width"
    )
    assert tile_w <= card_w
    assert tile_w >= card_w * 0.6


# ---------- Group C: Sync ON transition ----------

def test_c1_sync_on_creates_one_tile_per_cam(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    tile_count = page.locator("#fl3d-canvas-row .fl3d-tile").count()
    cam_count = page.evaluate("window.__fl3d.camSet.length")
    assert tile_count == cam_count


def test_c2_tiles_ordered_ascending_by_cam(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => Number(t.dataset.cam))",
    )
    assert cams == sorted(cams)


def test_c3_focused_tile_is_primary_cam(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    focused_cam = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => Number(t.dataset.cam)"
    )
    primary = page.evaluate("window.__fl3d.primaryCam")
    assert focused_cam == primary


def test_c4_focused_border_color_matches_accent(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    # Read --accent from the *card* scope (.dlc-theme redefines it from the global :root)
    accent = page.evaluate(
        "getComputedStyle(document.getElementById('frame-labeler-card'))"
        ".getPropertyValue('--accent').trim()"
    )
    focused_color = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused",
        "t => getComputedStyle(t).borderColor",
    )
    accent_rgb = page.evaluate(
        "(c) => { const el = document.createElement('div'); el.style.color = c; "
        "document.body.appendChild(el); const got = getComputedStyle(el).color; "
        "el.remove(); return got; }",
        accent,
    )
    assert focused_color == accent_rgb


def test_c5_each_tile_has_image_or_placeholder(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    statuses = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        """tiles => tiles.map(t => {
          const c = t.querySelector('canvas');
          const e = t.querySelector('.fl3d-tile-empty');
          if (e && !e.classList.contains('hidden')) return { kind: 'empty', text: e.textContent.trim() };
          if (c && c.dataset.fname) return { kind: 'image', fname: c.dataset.fname };
          return { kind: 'unknown' };
        })""",
    )
    for s in statuses:
        if s["kind"] == "empty":
            assert re.match(r"^No frame extracted for cam\d+ @ \d+$", s["text"])
        elif s["kind"] == "image":
            assert s["fname"]
        else:
            pytest.fail(f"tile in unknown state: {s}")


# ---------- Group D: Focus switching ----------

def test_d1_click_unfocused_tile_swaps_focus(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => Number(t.dataset.cam))"
    )
    other = next(c for c in cams if c != primary)
    page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{other}"]').click()
    new_focused = page.evaluate("window.__fl3d.focusedCam")
    assert new_focused == other


def test_d3_focused_cam_state_reflects_click(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => Number(t.dataset.cam))"
    )
    for cam in cams:
        page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{cam}"]').click()
        assert page.evaluate("window.__fl3d.focusedCam") == cam


# ---------- Group E: Lock-step navigation ----------

def test_e1_next_advances_all_tiles(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    before = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => ({cam: +t.dataset.cam, fname: t.dataset.fname}))",
    )
    before_idx = page.evaluate("window.__fl3d.frameNumberIdx")
    page.locator("#fl3d-btn-next").click()
    page.wait_for_function(f"window.__fl3d.frameNumberIdx === {before_idx + 1}")
    after = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => ({cam: +t.dataset.cam, fname: t.dataset.fname}))",
    )
    assert [t["cam"] for t in before] == [t["cam"] for t in after]
    assert before != after  # at least one tile changed

def test_e2_prev_returns_to_original(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    original = page.evaluate("window.__fl3d.frameNumberIdx")
    page.locator("#fl3d-btn-next").click()
    page.locator("#fl3d-btn-prev").click()
    assert page.evaluate("window.__fl3d.frameNumberIdx") == original

def test_e3_navigate_until_one_tile_empty(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    # Walk the entire frame-number axis; if no missing sibling exists in this
    # fixture (every frame number is fully paired), skip — the placeholder
    # path is exercised by C5 when at least one tile lacks a paired entry.
    total = page.evaluate("window.__fl3d.frameNumbers.length")
    found = False
    for _ in range(min(total, 500)):
        if page.locator("#fl3d-canvas-row .fl3d-tile-empty:not(.hidden)").count() >= 1:
            found = True
            break
        page.locator("#fl3d-btn-next").click()
    if not found:
        pytest.skip("OM-2_20260424 fixture is fully paired across cams — no placeholder to exercise here.")
    empty_tile = page.locator("#fl3d-canvas-row .fl3d-tile:has(.fl3d-tile-empty:not(.hidden))").first
    empty_cam = empty_tile.evaluate("t => +t.dataset.cam")
    empty_tile.click()
    assert page.evaluate("window.__fl3d.focusedCam") == empty_cam


# ---------- Group F: Marker placement ----------

def _select_unlabeled_chip(page: Page, fname: str):
    """Pick a body-part chip and clear ALL existing labels on `fname`.

    The OM-2 fixture's CSV pre-labels most body parts. Even with an unlabeled
    chip selected, a canvas click that lands near a pre-existing marker hits
    `_flHitTest` and takes the "select existing marker" early-return path —
    skipping the placement and dirty-set add. Wiping the in-memory label set
    for this fname guarantees a fresh-placement code path. Server-side CSV is
    unaffected (auto-save only fires on frame-switch + dirty=true).
    """
    chips = page.eval_on_selector_all(
        "#fl3d-bodypart-list .fl3d-bp-chip",
        "chips => chips.map(c => c.getAttribute('data-bp'))",
    )
    labels = page.evaluate(f"window.__fl3d.labels['{fname}'] || {{}}")
    bp = next((c for c in chips if labels.get(c) in (None, [None, None])), chips[0])
    page.evaluate(f"window.__fl3d.labels['{fname}'] = {{}}")
    page.locator(f'.fl3d-bp-chip[data-bp="{bp}"]').click()
    page.wait_for_function(f"window.__fl3d.selectedBp === '{bp}'")
    return bp


# Backwards-compat alias for tests still using the old name.
def _select_first_chip(page: Page):
    fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    return _select_unlabeled_chip(page, fname)


def _click_canvas_center(page: Page, tile_cam: int):
    canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{tile_cam}"] canvas')
    box = canvas.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

def test_f1_marker_added_on_focused_tile(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    bp = _select_first_chip(page)
    focused = page.evaluate("window.__fl3d.focusedCam")
    focused_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    _click_canvas_center(page, focused)
    page.wait_for_function(f"window.__fl3d.dirtyFrames.includes('{focused_fname}')")
    pt = page.evaluate(f"window.__fl3d.labels['{focused_fname}']?.['{bp}']")
    assert pt is not None and len(pt) == 2

def test_f2_focus_swap_then_marker_routes_to_sibling(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    bp = _select_first_chip(page)
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => +t.dataset.cam)"
    )
    sibling_cam = next(c for c in cams if c != primary)
    sibling_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling_cam}"]')
    if sibling_tile.locator(".fl3d-tile-empty:not(.hidden)").count() > 0:
        pytest.skip("sibling tile is empty placeholder for current frame_number")
    sibling_tile.click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {sibling_cam}")
    sibling_fname = sibling_tile.evaluate("t => t.dataset.fname")
    _click_canvas_center(page, sibling_cam)
    page.wait_for_function(f"window.__fl3d.dirtyFrames.includes('{sibling_fname}')")
    pt = page.evaluate(f"window.__fl3d.labels['{sibling_fname}']?.['{bp}']")
    assert pt is not None

def test_f7_keyboard_nudge_only_when_hover_focused(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    bp = _select_first_chip(page)
    focused = page.evaluate("window.__fl3d.focusedCam")
    focused_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    _click_canvas_center(page, focused)
    page.wait_for_function(f"window.__fl3d.labels['{focused_fname}']?.['{bp}']")
    # The placement runs _flAutoAdvanceBp which switches the selected chip to
    # the next unlabeled body-part — re-select our bp so W targets the right one.
    page.locator(f'.fl3d-bp-chip[data-bp="{bp}"]').click()
    page.wait_for_function(f"window.__fl3d.selectedBp === '{bp}'")
    before = page.evaluate(f"window.__fl3d.labels['{focused_fname}']['{bp}']")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => +t.dataset.cam)"
    )
    other = next(c for c in cams if c != focused)
    other_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{other}"] canvas')
    other_box = other_canvas.bounding_box()
    page.mouse.move(other_box["x"] + 5, other_box["y"] + 5)
    page.keyboard.press("w")
    page.wait_for_timeout(50)
    after_unhover = page.evaluate(f"window.__fl3d.labels['{focused_fname}']['{bp}']")
    assert after_unhover == before, "nudge fired when cursor was on unfocused tile"
    focused_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{focused}"] canvas')
    fb = focused_canvas.bounding_box()
    page.mouse.move(fb["x"] + fb["width"] / 2, fb["y"] + fb["height"] / 2)
    page.keyboard.press("w")
    page.wait_for_timeout(50)
    after_hover = page.evaluate(f"window.__fl3d.labels['{focused_fname}']['{bp}']")
    assert after_hover != before


# ---------- Group G: Shared display controls ----------

def test_g1_zoom_200_breaks_out(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    page.locator("#fl3d-zoom").evaluate("(el) => { el.value = '200'; el.dispatchEvent(new Event('input')); }")
    margin = page.eval_on_selector("#fl3d-canvas-row", "el => parseFloat(el.style.marginLeft) || 0")
    assert margin < 0

def test_g2_zoom_50_no_negative_margin(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    page.locator("#fl3d-zoom").evaluate("(el) => { el.value = '50'; el.dispatchEvent(new Event('input')); }")
    margin = page.eval_on_selector("#fl3d-canvas-row", "el => parseFloat(el.style.marginLeft) || 0")
    assert margin >= 0

def test_g3_marker_size_updates_state(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    page.locator("#fl3d-marker-size").evaluate("(el) => { el.value = '12'; el.dispatchEvent(new Event('input')); }")
    page.wait_for_function("window.__fl3d.markerRadius === 12")

def test_g4_show_names_toggle_updates_state(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    before = page.evaluate("window.__fl3d.showNames")
    page.locator("#fl3d-show-names").click()
    after = page.evaluate("window.__fl3d.showNames")
    assert after != before


# ---------- Group H: Save round-trip ----------

@pytest.mark.skipif(os.environ.get("FL3D_E2E_WRITE") != "1",
                    reason="Destructive write test; set FL3D_E2E_WRITE=1 to enable.")
def test_h1_h2_h3_save_persists_multi_cam_dirty(page: Page, base_url):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    bp = _select_first_chip(page)
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => +t.dataset.cam)"
    )
    sibling = next(c for c in cams if c != primary)
    sibling_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling}"]')
    if sibling_tile.locator(".fl3d-tile-empty:not(.hidden)").count() > 0:
        pytest.skip("sibling empty for current frame_number — pick another fixture frame")

    primary_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    sibling_fname = sibling_tile.evaluate("t => t.dataset.fname")

    _click_canvas_center(page, primary)
    sibling_tile.click()
    _click_canvas_center(page, sibling)

    page.wait_for_function(
        f"window.__fl3d.dirtyFrames.includes('{primary_fname}') && "
        f"window.__fl3d.dirtyFrames.includes('{sibling_fname}')"
    )

    page.locator("#fl3d-btn-save").click()
    page.wait_for_function("window.__fl3d.dirtyFrames.length === 0", timeout=10000)

    page.reload()
    page.locator("#btn-open-frame-labeler").click()
    page.locator("#fl3d-stem-select").select_option(SESSION)
    page.wait_for_function("document.querySelector('#fl3d-canvas-row .fl3d-tile')?.dataset?.fname")
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    for _ in range(500):
        cur = page.eval_on_selector_all(
            "#fl3d-canvas-row .fl3d-tile", "ts => ts.map(t => t.dataset.fname)"
        )
        if primary_fname in cur and sibling_fname in cur:
            break
        page.locator("#fl3d-btn-next").click()
    p_pt = page.evaluate(f"window.__fl3d.labels['{primary_fname}']?.['{bp}']")
    s_pt = page.evaluate(f"window.__fl3d.labels['{sibling_fname}']?.['{bp}']")
    assert p_pt is not None and s_pt is not None

    page.evaluate(
        f"window.__fl3d.labels['{primary_fname}']['{bp}'] = null;"
        f"window.__fl3d.labels['{sibling_fname}']['{bp}'] = null;"
    )
    page.locator("#fl3d-btn-save").click()


# ---------- Group I: Clear Frame ----------

def test_i1_clear_frame_focused_tile_only(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    bp = _select_first_chip(page)
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => +t.dataset.cam)"
    )
    sibling = next(c for c in cams if c != primary)
    sibling_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling}"]')
    if sibling_tile.locator(".fl3d-tile-empty:not(.hidden)").count() > 0:
        pytest.skip("sibling empty for current frame_number")
    primary_fname = page.eval_on_selector("#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname")
    sibling_fname = sibling_tile.evaluate("t => t.dataset.fname")
    # Wipe the sibling fname's labels to a single known bp marker. Otherwise,
    # the placement on sibling triggers _flAutoAdvanceBp -> all bps labeled ->
    # advances to the next frame, defocusing primary_fname before clear runs.
    page.evaluate(
        f"window.__fl3d.labels['{sibling_fname}'] = {{ '{bp}': null }};"
    )
    _click_canvas_center(page, primary)
    sibling_tile.click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {sibling}")
    # Re-select bp on sibling (auto-advance from primary may have changed it).
    page.locator(f'.fl3d-bp-chip[data-bp="{bp}"]').click()
    page.wait_for_function(f"window.__fl3d.selectedBp === '{bp}'")
    _click_canvas_center(page, sibling)
    # Refocus primary by clicking the tile's top label area (not the canvas) to
    # avoid placing a new marker via the canvas-click handler.
    page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{primary}"] .fl3d-tile-label').click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {primary}")
    page.locator("#fl3d-btn-clear-frame").dblclick()
    page.wait_for_timeout(200)
    p_pt = page.evaluate(f"window.__fl3d.labels['{primary_fname}']?.['{bp}']")
    s_pt = page.evaluate(f"window.__fl3d.labels['{sibling_fname}']?.['{bp}']")
    # Task 10 uses `delete _flLabels[fname]`, so labels[fname] becomes undefined
    # → ?.[bp] is undefined → Python None.
    assert p_pt is None
    assert s_pt is not None, "sibling marker should be untouched by clear of focused (primary) tile"


# ---------- Group J: Sync OFF transition ----------

def test_j1_sync_off_preserves_focused_cam(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => +t.dataset.cam)"
    )
    other = next(c for c in cams if c != primary)
    page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{other}"]').click()
    fname_at_toggle = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    page.locator("#fl3d-sync-frame").uncheck()
    page.wait_for_function("window.__fl3d.syncOn === false")
    tiles = page.locator("#fl3d-canvas-row .fl3d-tile")
    assert tiles.count() == 1
    sole_cam = tiles.first.evaluate("t => +t.dataset.cam")
    assert sole_cam == other
    sole_fname = tiles.first.evaluate("t => t.dataset.fname")
    assert sole_fname == fname_at_toggle


# ---------- Group K: Window resize ----------

def test_k1_shrink_viewport_no_horizontal_scrollbar(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    page.set_viewport_size({"width": 800, "height": 720})
    page.wait_for_timeout(150)
    has_scroll = page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert not has_scroll

def test_k2_grow_viewport_tiles_fit(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    page.set_viewport_size({"width": 1600, "height": 900})
    page.wait_for_timeout(150)
    tile_w = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.getBoundingClientRect().width"
    )
    assert tile_w > 200


# ---------- Group L: Refresh rebuilds pair map ----------

def test_l1_refresh_preserves_sync_state(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    pair_size_before = page.evaluate("window.__fl3d.pairMapSize")
    focused_before = page.evaluate("window.__fl3d.focusedCam")
    page.locator("#fl3d-refresh-btn").click()
    page.wait_for_function("document.querySelector('#fl3d-canvas-row .fl3d-tile')?.dataset?.fname")
    pair_size_after = page.evaluate("window.__fl3d.pairMapSize")
    focused_after = page.evaluate("window.__fl3d.focusedCam")
    assert pair_size_after == pair_size_before
    assert focused_after == focused_before


# ---------- Group M: Non-regression ----------

def test_m1_ml_panel_toggle_still_works(page: Page):
    cb = page.locator("#fl3d-ml-checkbox")
    assert cb.is_visible()
    cb.click()
    expect(page.locator("#fl3d-ml-opts")).not_to_have_class(_focused_class_re_for("hidden"))
    cb.click()
    expect(page.locator("#fl3d-ml-opts")).to_have_class(_focused_class_re_for("hidden"))

def test_m2_tap_panel_toggle_still_works(page: Page):
    cb = page.locator("#fl3d-tap-checkbox")
    assert cb.is_visible()
    cb.click()
    expect(page.locator("#fl3d-tap-opts")).not_to_have_class(_focused_class_re_for("hidden"))
    cb.click()
    expect(page.locator("#fl3d-tap-opts")).to_have_class(_focused_class_re_for("hidden"))


def _focused_class_re_for(token: str):
    return re.compile(rf"\b{token}\b")

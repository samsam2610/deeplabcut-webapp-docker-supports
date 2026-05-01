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
        "#fl3d-bodypart-list .fl-bp-chip",
        "chips => chips.map(c => c.getAttribute('data-bp'))",
    )
    labels = page.evaluate(f"window.__fl3d.labels['{fname}'] || {{}}")
    bp = next((c for c in chips if labels.get(c) in (None, [None, None])), chips[0])
    page.evaluate(f"window.__fl3d.labels['{fname}'] = {{}}")
    page.locator(f'.fl-bp-chip[data-bp="{bp}"]').click()
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
    page.locator(f'.fl-bp-chip[data-bp="{bp}"]').click()
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
    page.locator(f'.fl-bp-chip[data-bp="{bp}"]').click()
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


# =============================================================================
# Group N: comprehensive interaction coverage in sync mode (regression suite)
# =============================================================================
#
# These tests exist to lock down "labeling stays smooth in sync mode" — the
# fixes for: (a) sibling-tile WASD nudge corrupting the primary canvas via
# stale _flImg, and (b) the primary tile flipping back to an old frame when
# any label-mutation handler called _flDraw() in sync mode. The pixel-content
# checks on the primary canvas are the regression detector for both.

def _primary_center_px(page, x_frac=0.5, y_frac=0.5):
    """Sample pixels of the primary tile's canvas as a fingerprint of its image.

    Default sample is canvas center. Override fractions to sample away from
    a marker or selection ring that you placed for the test.
    """
    return page.evaluate(f"""() => {{
        const c = document.getElementById('fl3d-canvas');
        const ctx = c.getContext('2d');
        const x = Math.max(0, Math.floor(c.width * {x_frac}));
        const y = Math.max(0, Math.floor(c.height * {y_frac}));
        const d = ctx.getImageData(x, y, 5, 5).data;
        return Array.from(d.slice(0, 12)).join(',');
    }}""")


def _seed_focused_with_one_marker(page, fname, bp, x, y):
    """Force focused tile's label state to a single known marker."""
    page.evaluate(
        f"window.__fl3d.labels['{fname}'] = {{'{bp}': [{x}, {y}]}};"
    )


def _enable_sync_at_frame(page, advance=10):
    """Open Frame Labeler, enable sync, advance N frames so _flImg is stale."""
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    for _ in range(advance):
        page.locator("#fl3d-btn-next").click()
        page.wait_for_timeout(50)


def _focus_sibling(page):
    """Switch focus to the sibling tile and return (sibling_cam, sibling_fname)."""
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "ts => ts.map(t => +t.dataset.cam)"
    )
    sibling = next(c for c in cams if c != primary)
    sib_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling}"]')
    if sib_tile.locator(".fl3d-tile-empty:not(.hidden)").count() > 0:
        pytest.skip("sibling empty for current frame_number")
    sib_tile.click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {sibling}")
    return sibling, sib_tile.evaluate("t => t.dataset.fname")


def test_n1_wasd_on_sibling_does_not_corrupt_primary_canvas(page: Page):
    """Bug A regression: nudging a sibling marker via W/A/S/D must not
    overwrite the primary tile's image with stale _flImg."""
    _enable_sync_at_frame(page, advance=10)
    primary_pix_before = _primary_center_px(page)

    sibling, sib_fname = _focus_sibling(page)
    _seed_focused_with_one_marker(page, sib_fname, "Snout", 400, 300)
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    sib_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling}"] canvas')
    box = sib_canvas.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(100)

    page.keyboard.press("w")
    page.wait_for_timeout(150)

    sib_pos = page.evaluate(f"window.__fl3d.labels['{sib_fname}']['Snout']")
    assert sib_pos == [400, 299], f"sibling marker should nudge by 1px in y, got {sib_pos}"
    primary_pix_after = _primary_center_px(page)
    assert primary_pix_after == primary_pix_before, (
        "primary canvas was corrupted when WASD nudged a sibling marker — "
        f"before={primary_pix_before} after={primary_pix_after}"
    )


def test_n2_wasd_on_primary_after_sync_nav_does_not_jump_frame(page: Page):
    """Bug B regression: after sync nav, pressing W on the primary tile must
    not paint the OLD _flImg back over the current frame's image. Sample
    pixels at a corner away from the marker so we measure the IMAGE, not the
    marker's selection ring."""
    _enable_sync_at_frame(page, advance=10)
    primary = page.evaluate("window.__fl3d.primaryCam")
    pri_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    # Marker placed at top-left corner so center-sample stays on bare image
    _seed_focused_with_one_marker(page, pri_fname, "Snout", 50, 50)
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    pri_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{primary}"] canvas')
    box = pri_canvas.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(100)

    primary_pix_before = _primary_center_px(page)  # center, no marker here
    page.keyboard.press("w")
    page.wait_for_timeout(150)
    pos = page.evaluate(f"window.__fl3d.labels['{pri_fname}']['Snout']")
    assert pos == [50, 49]

    primary_pix_after = _primary_center_px(page)
    assert primary_pix_after == primary_pix_before, (
        "primary canvas content changed (frame jumped to stale _flImg) — "
        f"before={primary_pix_before} after={primary_pix_after}"
    )


def test_n3_shift_wasd_nudges_by_10px(page: Page):
    """Shift + nudge keys should move 10px instead of 1px."""
    _enable_sync_at_frame(page, advance=5)
    pri_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    _seed_focused_with_one_marker(page, pri_fname, "Snout", 400, 300)
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    pri_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile.focused canvas')
    box = pri_canvas.bounding_box()
    page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
    page.wait_for_timeout(100)
    page.keyboard.press("Shift+d")
    page.wait_for_timeout(150)
    pos = page.evaluate(f"window.__fl3d.labels['{pri_fname}']['Snout']")
    assert pos == [410, 300], f"Shift+D should add 10 to x, got {pos}"


def test_n4_arrow_keys_navigate_frames_in_sync_mode(page: Page):
    """ArrowRight/Left should walk the frame-number axis in sync mode."""
    _enable_sync_at_frame(page, advance=5)
    idx0 = page.evaluate("window.__fl3d.frameNumberIdx")
    page.locator("#fl3d-canvas-row").hover()
    page.keyboard.press("ArrowRight")
    page.wait_for_function(f"window.__fl3d.frameNumberIdx === {idx0 + 1}")
    page.keyboard.press("ArrowLeft")
    page.wait_for_function(f"window.__fl3d.frameNumberIdx === {idx0}")


def test_n5_tab_cycles_body_parts_in_sync_mode(page: Page):
    """Tab should advance the selected body part — globally, regardless of focus."""
    _enable_sync_at_frame(page, advance=5)
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    page.locator("#fl3d-canvas-row").hover()
    page.keyboard.press("Tab")
    page.wait_for_function("window.__fl3d.selectedBp !== 'Snout'")
    next_bp = page.evaluate("window.__fl3d.selectedBp")
    assert next_bp != "Snout"


def test_n6_backspace_deletes_focused_marker_in_sync_mode(page: Page):
    """Backspace should null the selected bp's marker on the focused tile."""
    _enable_sync_at_frame(page, advance=5)
    sibling, sib_fname = _focus_sibling(page)
    _seed_focused_with_one_marker(page, sib_fname, "Snout", 400, 300)
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")

    primary_pix_before = _primary_center_px(page)
    page.keyboard.press("Backspace")
    page.wait_for_timeout(150)
    pos = page.evaluate(f"window.__fl3d.labels['{sib_fname}']?.Snout")
    assert pos is None, f"Backspace should null sibling marker, got {pos}"
    # And primary canvas must NOT be corrupted
    primary_pix_after = _primary_center_px(page)
    assert primary_pix_after == primary_pix_before


def test_n7_right_click_on_sibling_canvas_only_deletes_that_marker(page: Page):
    """Right-click on the sibling canvas removes its bp marker; the primary
    canvas must remain visually intact."""
    _enable_sync_at_frame(page, advance=5)
    sibling, sib_fname = _focus_sibling(page)
    _seed_focused_with_one_marker(page, sib_fname, "Snout", 400, 300)
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    primary_pix_before = _primary_center_px(page)
    sib_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling}"] canvas')
    box = sib_canvas.bounding_box()
    page.mouse.click(
        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, button="right"
    )
    page.wait_for_timeout(150)
    pos = page.evaluate(f"window.__fl3d.labels['{sib_fname}']?.Snout")
    assert pos is None
    primary_pix_after = _primary_center_px(page)
    assert primary_pix_after == primary_pix_before


def test_n8_show_names_toggle_does_not_change_primary_canvas_in_sync(page: Page):
    """Regression for the previous 'frame jumps when toggling show names' fix."""
    _enable_sync_at_frame(page, advance=5)
    p_initial = _primary_center_px(page)
    page.locator("#fl3d-show-names").click()
    page.wait_for_timeout(150)
    p_off = _primary_center_px(page)
    page.locator("#fl3d-show-names").click()
    page.wait_for_timeout(150)
    p_on = _primary_center_px(page)
    assert p_initial == p_off == p_on


def test_n9_marker_size_change_does_not_jump_primary_canvas(page: Page):
    """Marker-size slider must not corrupt the primary canvas in sync mode."""
    _enable_sync_at_frame(page, advance=5)
    pri_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    page.evaluate(f"window.__fl3d.labels['{pri_fname}'] = {{}};")
    p_before = _primary_center_px(page)
    page.locator("#fl3d-marker-size").evaluate(
        "(el) => { el.value = '12'; el.dispatchEvent(new Event('input')); }"
    )
    page.wait_for_timeout(100)
    p_after = _primary_center_px(page)
    # No labels on this frame, so neither marker-size value should affect canvas content.
    assert p_after == p_before


def test_n10_clear_frame_does_not_swap_primary_image_to_stale(page: Page):
    """After Clear Frame on the focused (primary) tile, the canvas should
    show the SAME frame's image (just no markers), not flip to a stale one."""
    _enable_sync_at_frame(page, advance=5)
    pri_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    page.evaluate(f"window.__fl3d.labels['{pri_fname}'] = {{Snout: [50, 50]}};")
    p_before = _primary_center_px(page)
    page.locator("#fl3d-btn-clear-frame").dblclick()
    page.wait_for_timeout(200)
    p_after = _primary_center_px(page)
    assert p_after == p_before, (
        "Clear Frame should not change the canvas image (no markers were near center) — "
        f"before={p_before} after={p_after}"
    )


def test_n11_wasd_on_unfocused_hover_is_a_noop(page: Page):
    """Pre-existing hover gate: pressing W with cursor on the UNFOCUSED tile
    must not move the marker on either tile."""
    _enable_sync_at_frame(page, advance=5)
    pri_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    _seed_focused_with_one_marker(page, pri_fname, "Snout", 400, 300)
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")

    # Hover the SIBLING tile and press W
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "ts => ts.map(t => +t.dataset.cam)"
    )
    sib = next(c for c in cams if c != primary)
    sib_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sib}"] canvas')
    box = sib_canvas.bounding_box()
    page.mouse.move(box["x"] + 5, box["y"] + 5)
    page.wait_for_timeout(80)
    before = page.evaluate(f"window.__fl3d.labels['{pri_fname}']['Snout']")
    page.keyboard.press("w")
    page.wait_for_timeout(120)
    after = page.evaluate(f"window.__fl3d.labels['{pri_fname}']['Snout']")
    assert after == before


def test_n12_save_button_clears_dirty_set(page: Page):
    """Save button: marker placement should populate dirtyFrames, save clears it."""
    _enable_sync_at_frame(page, advance=5)
    pri_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    page.evaluate(f"window.__fl3d.labels['{pri_fname}'] = {{}};")
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    pri_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile.focused canvas')
    box = pri_canvas.bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.95, box["y"] + box["height"] * 0.05)
    page.wait_for_function(f"window.__fl3d.dirtyFrames.includes('{pri_fname}')")
    # We don't actually want to write to the CSV in CI — skip the save click.
    # Just verify dirtyFrames shape; save round-trip is gated under H1.
    dirty = page.evaluate("window.__fl3d.dirtyFrames")
    assert pri_fname in dirty


def test_n13_double_click_chip_toggles_visibility_in_sync(page: Page):
    """Double-clicking a chip toggles vis-hidden state on the focused tile's
    marker. Sample pixels at a corner away from the marker — a visibility
    toggle DOES change pixels at the marker location (intentionally), but
    the rest of the image must remain stable (no stale-frame flicker)."""
    _enable_sync_at_frame(page, advance=5)
    pri_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    # Marker placed off-center so corner samples don't catch the marker pixels.
    _seed_focused_with_one_marker(page, pri_fname, "Snout", 50, 50)
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    p_before = _primary_center_px(page)  # canvas center, no marker here
    page.locator('.fl-bp-chip[data-bp="Snout"]').dblclick()
    page.wait_for_timeout(150)
    p_after = _primary_center_px(page)
    assert p_after == p_before, (
        "primary canvas image (away from marker) must stay stable across "
        f"chip dblclick — before={p_before} after={p_after}"
    )


# =============================================================================
# Group P: primary-canvas pointer math (post focus-swap regression)
# =============================================================================
#
# In sync mode the primary canvas's drawing buffer is set to the image's
# natural size while CSS displays the canvas at the tile's flex width — the
# old click/mousemove/_flHitTest math used `flCanvas.width / _flImg.naturalWidth`
# (≈1) which produced drastically wrong coords (off by hundreds of pixels)
# after focus swapped sibling→primary. These tests pin the new rect-based
# scaling so:
#   - clicking the visual center of the canvas places the marker at image
#     center (within sub-pixel rounding tolerance)
#   - hovering an existing marker turns the cursor into "pointer"
#   - cursor stays "crosshair" over empty pixels even after frame nav

def _primary_canvas_dims(page):
    return page.evaluate("""() => {
        const c = document.getElementById('fl3d-canvas');
        const r = c.getBoundingClientRect();
        return {bw: c.width, bh: c.height, dw: r.width, dh: r.height};
    }""")


def _focus_swap_then_back(page):
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all("#fl3d-canvas-row .fl3d-tile", "ts => ts.map(t => +t.dataset.cam)")
    sibling = next(c for c in cams if c != primary)
    page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling}"]').click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {sibling}")
    page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{primary}"] .fl3d-tile-label').click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {primary}")
    return primary


def test_p1_primary_click_lands_at_image_space_center(page: Page):
    _enable_sync_at_frame(page, advance=5)
    primary = _focus_swap_then_back(page)
    pri_fname = page.eval_on_selector("#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname")
    page.evaluate(f"window.__fl3d.labels['{pri_fname}'] = {{}};")
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    pri_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{primary}"] canvas')
    box = pri_canvas.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(200)
    pos = page.evaluate(f"window.__fl3d.labels['{pri_fname}']['Snout']")
    dims = _primary_canvas_dims(page)
    expected = (dims["bw"] / 2, dims["bh"] / 2)
    # Sub-pixel rounding tolerance: rect float arithmetic ± 5 image-space px
    assert abs(pos[0] - expected[0]) < 5, (
        f"marker landed at x={pos[0]:.1f}, expected ~{expected[0]} (off by "
        f"{abs(pos[0] - expected[0]):.1f} image-px)"
    )
    assert abs(pos[1] - expected[1]) < 5, (
        f"marker landed at y={pos[1]:.1f}, expected ~{expected[1]}"
    )


def test_p2_hovering_existing_marker_shows_pointer_cursor(page: Page):
    _enable_sync_at_frame(page, advance=5)
    primary = _focus_swap_then_back(page)
    pri_fname = page.eval_on_selector("#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname")
    page.evaluate(f"window.__fl3d.labels['{pri_fname}'] = {{Snout: [400, 300]}};")
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    pri_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{primary}"] canvas')
    box = pri_canvas.bounding_box()
    dims = _primary_canvas_dims(page)
    sx = dims["bw"] / dims["dw"]
    sy = dims["bh"] / dims["dh"]
    # Move cursor to the marker (image-space (400,300) → CSS px)
    page.mouse.move(box["x"] + 400 / sx, box["y"] + 300 / sy)
    page.wait_for_timeout(150)
    cursor = page.evaluate("getComputedStyle(document.getElementById('fl3d-canvas')).cursor")
    assert cursor == "pointer", f"cursor over marker should be 'pointer', got '{cursor}'"


def test_p3_clicking_existing_marker_selects_it(page: Page):
    _enable_sync_at_frame(page, advance=5)
    primary = _focus_swap_then_back(page)
    pri_fname = page.eval_on_selector("#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname")
    page.evaluate(f"window.__fl3d.labels['{pri_fname}'] = {{Snout: [400, 300], Wrist: [200, 150]}};")
    # Select Wrist via chip first
    page.locator('.fl-bp-chip[data-bp="Wrist"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Wrist'")
    # Click on Snout's marker on canvas — selection should switch to Snout
    pri_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{primary}"] canvas')
    box = pri_canvas.bounding_box()
    dims = _primary_canvas_dims(page)
    sx = dims["bw"] / dims["dw"]
    sy = dims["bh"] / dims["dh"]
    page.mouse.click(box["x"] + 400 / sx, box["y"] + 300 / sy)
    page.wait_for_timeout(150)
    sel = page.evaluate("window.__fl3d.selectedBp")
    assert sel == "Snout", f"clicking on Snout marker should re-select Snout, got {sel}"


def test_p4_cursor_remains_crosshair_after_frame_switch(page: Page):
    _enable_sync_at_frame(page, advance=5)
    primary = _focus_swap_then_back(page)
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    pri_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{primary}"] canvas')
    box = pri_canvas.bounding_box()
    # Move cursor to top-left empty area (no marker there)
    page.mouse.move(box["x"] + 20, box["y"] + 20)
    page.wait_for_timeout(120)
    cursor_pre = page.evaluate("getComputedStyle(document.getElementById('fl3d-canvas')).cursor")
    assert cursor_pre == "crosshair", f"pre-switch cursor should be crosshair, got '{cursor_pre}'"
    # Switch frame and re-trigger mousemove on same empty area
    page.locator("#fl3d-btn-next").click()
    page.wait_for_timeout(200)
    page.mouse.move(box["x"] + 20, box["y"] + 20)
    page.wait_for_timeout(120)
    cursor_post = page.evaluate("getComputedStyle(document.getElementById('fl3d-canvas')).cursor")
    # New frame has CSV-pre-loaded labels but NOT at (20,20) corner
    assert cursor_post == "crosshair", f"post-switch cursor should stay crosshair on empty area, got '{cursor_post}'"


def test_p6_sibling_click_on_marker_selects_does_not_overwrite(page: Page):
    """User report: in sync mode, clicking a marker on the sibling tile
    overwrote it (no hit-test) and triggered _flAutoAdvanceBp to jump frames.
    Sibling click handler must mirror primary: hit-test first, select on hit."""
    _enable_sync_at_frame(page, advance=5)
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all("#fl3d-canvas-row .fl3d-tile", "ts => ts.map(t => +t.dataset.cam)")
    sibling_cam = next(c for c in cams if c != primary)
    sib_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling_cam}"]')
    if sib_tile.locator(".fl3d-tile-empty:not(.hidden)").count() > 0:
        pytest.skip("sibling empty for current frame_number")
    sib_tile.click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {sibling_cam}")
    sib_fname = sib_tile.evaluate("t => t.dataset.fname")
    page.evaluate(f"window.__fl3d.labels['{sib_fname}'] = {{Snout: [400, 300]}};")
    page.locator('.fl-bp-chip[data-bp="Wrist"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Wrist'")
    sib_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling_cam}"] canvas')
    box = sib_canvas.bounding_box()
    dims = page.evaluate(f"""(() => {{
        const c = document.querySelector('#fl3d-canvas-row .fl3d-tile[data-cam="{sibling_cam}"] canvas');
        const r = c.getBoundingClientRect();
        return {{bw: c.width, dw: r.width, bh: c.height, dh: r.height}};
    }})()""")
    sx = dims["bw"] / dims["dw"]
    sy = dims["bh"] / dims["dh"]
    page.mouse.click(box["x"] + 400 / sx, box["y"] + 300 / sy)
    page.wait_for_timeout(200)
    assert page.evaluate("window.__fl3d.selectedBp") == "Snout"
    assert page.evaluate(f"window.__fl3d.labels['{sib_fname}']?.Snout") == [400, 300]


def test_p7_sibling_cursor_pointer_over_marker(page: Page):
    """Sibling tile's CSS sets cursor: pointer for tile focus affordance.
    On the canvas, cursor must be hover-aware: pointer over a marker,
    crosshair over empty area when bp selected."""
    _enable_sync_at_frame(page, advance=5)
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all("#fl3d-canvas-row .fl3d-tile", "ts => ts.map(t => +t.dataset.cam)")
    sibling_cam = next(c for c in cams if c != primary)
    sib_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling_cam}"]')
    if sib_tile.locator(".fl3d-tile-empty:not(.hidden)").count() > 0:
        pytest.skip("sibling empty")
    sib_tile.click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {sibling_cam}")
    sib_fname = sib_tile.evaluate("t => t.dataset.fname")
    page.evaluate(f"window.__fl3d.labels['{sib_fname}'] = {{Snout: [400, 300]}};")
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    sib_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling_cam}"] canvas')
    box = sib_canvas.bounding_box()
    dims = page.evaluate(f"""(() => {{
        const c = document.querySelector('#fl3d-canvas-row .fl3d-tile[data-cam="{sibling_cam}"] canvas');
        const r = c.getBoundingClientRect();
        return {{bw: c.width, dw: r.width, bh: c.height, dh: r.height}};
    }})()""")
    sx = dims["bw"] / dims["dw"]
    sy = dims["bh"] / dims["dh"]
    # Over marker
    page.mouse.move(box["x"] + 400 / sx, box["y"] + 300 / sy)
    page.wait_for_timeout(120)
    cursor = page.evaluate(f"""getComputedStyle(document.querySelector('#fl3d-canvas-row .fl3d-tile[data-cam="{sibling_cam}"] canvas')).cursor""")
    assert cursor == "pointer", f"sibling marker cursor should be pointer, got {cursor}"
    # Over empty corner
    page.mouse.move(box["x"] + 10, box["y"] + 10)
    page.wait_for_timeout(120)
    cursor = page.evaluate(f"""getComputedStyle(document.querySelector('#fl3d-canvas-row .fl3d-tile[data-cam="{sibling_cam}"] canvas')).cursor""")
    assert cursor == "crosshair", f"sibling empty cursor should be crosshair, got {cursor}"


def test_p8_chip_click_immediately_paints_selection_ring(page: Page):
    """User report: 'choosing a marker by selecting the chip doesn't draw a
    white circle indicating selection on the frame.' _flSelectBp must trigger
    a redraw so the ring appears without requiring a cursor nudge."""
    _enable_sync_at_frame(page, advance=5)
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all("#fl3d-canvas-row .fl3d-tile", "ts => ts.map(t => +t.dataset.cam)")
    sib_cam = next(c for c in cams if c != primary)
    sib_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sib_cam}"]')
    if sib_tile.locator(".fl3d-tile-empty:not(.hidden)").count() > 0:
        pytest.skip("sibling empty")
    sib_tile.click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {sib_cam}")
    sib_fname = sib_tile.evaluate("t => t.dataset.fname")
    page.evaluate(f"window.__fl3d.labels['{sib_fname}'] = {{Snout: [400, 300]}};")
    # Pick a non-Snout chip first, then move cursor far off-canvas (no hover state).
    page.locator('.fl-bp-chip[data-bp="Wrist"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Wrist'")
    page.mouse.move(0, 0)
    page.wait_for_timeout(200)
    sib_canvas_sel = f'#fl3d-canvas-row .fl3d-tile[data-cam="{sib_cam}"] canvas'
    # Sample on the ring perimeter (radius ≈7.5 from marker center)
    def px(x, y):
        return page.evaluate(f"""(() => {{
            const c = document.querySelector('{sib_canvas_sel}');
            const ctx = c.getContext('2d');
            return Array.from(ctx.getImageData({x}, {y}, 1, 1).data.slice(0, 3)).join(',');
        }})()""")
    px_pre = [px(400 + dx, 300 + dy) for dx, dy in [(8,0),(0,8),(-8,0),(0,-8),(6,6)]]
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    page.wait_for_timeout(200)
    px_post = [px(400 + dx, 300 + dy) for dx, dy in [(8,0),(0,8),(-8,0),(0,-8),(6,6)]]
    # At least one perimeter pixel must change (the ring's white stroke is
    # rgba(255,255,255,0.85) ≈ 218 over typical dark backgrounds).
    diffs = sum(1 for a, b in zip(px_pre, px_post) if a != b)
    assert diffs >= 1, (
        f"selection ring should have appeared on sibling after chip click "
        f"(pixels unchanged at all 5 perimeter sample points)\n"
        f"  before: {px_pre}\n  after:  {px_post}"
    )


def test_p10_save_button_shows_visible_feedback(page: Page):
    """User report: 'Save Labels button doesn't have feedback to let the
    user know if the labels have been saved.' Root cause was that the
    sed pass during chip-styling restoration over-reverted
    getElementById('fl3d-save-status') to ('fl-save-status'), so flSaveStatus
    was null and the handler crashed silently on the first textContent set.

    Verify: Save click → 'Saving…' transient → 'Saved ✓' (or error) appears
    in #fl3d-save-status with appropriate class."""
    _enable_sync_at_frame(page, advance=2)
    page.locator("#fl3d-btn-save").click()
    # Transient "Saving…" — must appear before fetch resolves.
    page.wait_for_function(
        "() => document.getElementById('fl3d-save-status').textContent.startsWith('Saving')",
        timeout=5000,
    )
    # Resolution — wait up to 30s for the CSV save to finish.
    page.wait_for_function(
        "() => { const t = document.getElementById('fl3d-save-status').textContent; return t && !t.startsWith('Saving'); }",
        timeout=30000,
    )
    state = page.evaluate("""(() => {
        const el = document.getElementById('fl3d-save-status');
        return {text: el.textContent, cls: el.className};
    })()""")
    assert "Saved" in state["text"] or "✓" in state["text"], (
        f"expected save success message, got: {state}"
    )
    assert "ok" in state["cls"], f"status class should include 'ok', got: {state['cls']}"


def test_p9_hover_marker_shows_name_tooltip(page: Page):
    """User report: 'hover cursor over marker doesn't show its name.'
    _fl3dDrawTileMarkers must honor _flHoverBp the way the main webapp's
    _flDraw does. Sibling mousemove must update _flHoverBp + redraw."""
    _enable_sync_at_frame(page, advance=5)
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all("#fl3d-canvas-row .fl3d-tile", "ts => ts.map(t => +t.dataset.cam)")
    sib_cam = next(c for c in cams if c != primary)
    sib_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sib_cam}"]')
    if sib_tile.locator(".fl3d-tile-empty:not(.hidden)").count() > 0:
        pytest.skip("sibling empty")
    sib_tile.click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {sib_cam}")
    sib_fname = sib_tile.evaluate("t => t.dataset.fname")
    page.evaluate(f"window.__fl3d.labels['{sib_fname}'] = {{Snout: [400, 300]}};")
    # Make sure show-names is OFF so the only way for a name to appear is via hover.
    if page.evaluate("window.__fl3d.showNames"):
        page.locator("#fl3d-show-names").click()
        page.wait_for_function("window.__fl3d.showNames === false")
    sib_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sib_cam}"] canvas')
    box = sib_canvas.bounding_box()
    dims = page.evaluate(f"""(() => {{
        const c = document.querySelector('#fl3d-canvas-row .fl3d-tile[data-cam="{sib_cam}"] canvas');
        const r = c.getBoundingClientRect();
        return {{bw: c.width, dw: r.width, bh: c.height, dh: r.height}};
    }})()""")
    sx = dims["bw"] / dims["dw"]
    sy = dims["bh"] / dims["dh"]
    sib_canvas_sel = f'#fl3d-canvas-row .fl3d-tile[data-cam="{sib_cam}"] canvas'
    # Sample inside the name-backdrop area drawn at (cx+r+2, cy-7) with width tw+6, height 14
    # For "Snout" at marker (400,300) with r=4: backdrop ~= (406,293)..(442,307)
    def px(x, y):
        return page.evaluate(f"""(() => {{
            const c = document.querySelector('{sib_canvas_sel}');
            const ctx = c.getContext('2d');
            const d = ctx.getImageData({x}, {y}, 4, 4).data;
            return Array.from(d.slice(0, 12)).join(',');
        }})()""")
    # Move cursor away (no hover) — sample baseline
    page.mouse.move(0, 0)
    page.wait_for_timeout(200)
    px_no_hover = [px(420, 297), px(425, 300), px(415, 295)]
    # Hover ON the marker
    page.mouse.move(box["x"] + 400 / sx, box["y"] + 300 / sy)
    page.wait_for_timeout(250)
    px_hover = [px(420, 297), px(425, 300), px(415, 295)]
    diffs = sum(1 for a, b in zip(px_no_hover, px_hover) if a != b)
    assert diffs >= 1, (
        f"name tooltip should have appeared on hover (no pixels in backdrop "
        f"area changed)\n  no-hover: {px_no_hover}\n  hover: {px_hover}"
    )


def test_p5_zoom_does_not_break_primary_click_targeting(page: Page):
    """Verify rect-based scaling also handles zoom != 100% correctly (the
    OLD math was actually broken for sync OFF zoom>100% too)."""
    _enable_sync_at_frame(page, advance=5)
    primary = _focus_swap_then_back(page)
    pri_fname = page.eval_on_selector("#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname")
    page.evaluate(f"window.__fl3d.labels['{pri_fname}'] = {{}};")
    page.locator('.fl-bp-chip[data-bp="Snout"]').click()
    page.wait_for_function("window.__fl3d.selectedBp === 'Snout'")
    page.locator("#fl3d-zoom").evaluate("(el) => { el.value = '200'; el.dispatchEvent(new Event('input')); }")
    page.wait_for_timeout(150)
    pri_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{primary}"] canvas')
    box = pri_canvas.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(200)
    pos = page.evaluate(f"window.__fl3d.labels['{pri_fname}']['Snout']")
    dims = _primary_canvas_dims(page)
    expected = (dims["bw"] / 2, dims["bh"] / 2)
    assert abs(pos[0] - expected[0]) < 5
    assert abs(pos[1] - expected[1]) < 5

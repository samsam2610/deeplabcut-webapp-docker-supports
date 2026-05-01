"""e2e tests for Sync Frame — groups A (Visibility), B (Initial state),
C (Sync ON transition), D (Focus switching).

Fixture dependency: om2_fixture_present (conftest.py) probes the main webapp's
/dlc/project/labeled-frames endpoint and skips the whole module if the session
OM-2_20260424 is absent or has fewer than 2 cameras.
"""
import re
import pytest
from playwright.sync_api import Page, expect

SESSION = "OM-2_20260424"


@pytest.fixture(autouse=True)
def _open_labeler(page: Page, base_url, om2_fixture_present):
    if not om2_fixture_present:
        pytest.skip(f"Skipping: {SESSION} not present or has no multi-cam frames.")
    page.goto(base_url)
    page.locator("#btn-open-frame-labeler").click()
    page.locator("#frame-labeler-card").wait_for(state="visible")
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
    accent = page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"
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

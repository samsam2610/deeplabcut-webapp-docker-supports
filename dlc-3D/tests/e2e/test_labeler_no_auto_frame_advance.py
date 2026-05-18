"""e2e: labeling every BP on a frame must NOT auto-advance to the next frame.

Two tests cover both sync modes — _flAutoAdvanceBp's fall-through used to
call _flShowFrame using either _flFrameIdx/_flFrames (sync off) or
_fl3dFrameNumIdx/_fl3dFrameNumbers (sync on). Both code paths must stay put.
"""
import pytest
from playwright.sync_api import Page

SESSION = "OM-2_20260424"


@pytest.fixture(autouse=True)
def _open_labeler(page: Page, base_url):
    """Same opening dance as test_sync_frame.py: open the labeler card,
    wait for the SESSION option to appear, select it, wait for the first
    tile's data-fname to be populated.
    """
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


def _label_every_bp_on_focused_frame(page: Page, starting_fname: str) -> list[str]:
    """For each BP chip in DOM order, click the chip and click the canvas at
    a unique offset, waiting for the label to land in window.__fl3d.labels.

    Returns the list of BP names (in chip DOM order) for the caller's assertions.
    """
    # Wipe any pre-existing labels on this frame so every chip click is a
    # fresh placement (mirrors _select_unlabeled_chip in test_sync_frame.py).
    page.evaluate(f"window.__fl3d.labels['{starting_fname}'] = {{}}")

    bps: list[str] = page.eval_on_selector_all(
        "#fl3d-bodypart-list .fl-bp-chip",
        "chips => chips.map(c => c.getAttribute('data-bp'))",
    )
    assert bps, "no BP chips rendered — fixture mismatch"

    canvas = page.locator("#fl3d-canvas-row .fl3d-tile.focused canvas")
    canvas.scroll_into_view_if_needed()
    box = canvas.bounding_box()
    assert box is not None, "focused tile canvas has no bounding box"

    # Lay clicks on a grid with 25 px spacing so consecutive clicks never
    # land within the 10 CSS-px hit-test radius of a previously placed marker.
    cols = max(1, int(box["width"] * 0.7 / 25))
    for i, bp in enumerate(bps):
        page.locator(f'.fl-bp-chip[data-bp="{bp}"]').click()
        page.wait_for_function(f"window.__fl3d.selectedBp === '{bp}'")
        # Spread offsets so we never hit-test a marker we just placed and
        # accidentally take the select-only path.
        col = i % cols
        row = i // cols
        x = box["x"] + box["width"] * 0.1 + col * 25
        y = box["y"] + box["height"] * 0.1 + row * 25
        page.mouse.click(x, y)
        page.wait_for_function(
            f"window.__fl3d.labels['{starting_fname}']?.['{bp}']"
        )

    return bps


def test_no_auto_advance_when_last_bp_labeled_sync_off(page: Page):
    starting_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    _label_every_bp_on_focused_frame(page, starting_fname)

    # Every BP is now labeled. The fall-through (deleted) used to call
    # _flShowFrame(_flFrameIdx + 1) here; with the fix it must not fire.
    final_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    assert final_fname == starting_fname, (
        f"Frame auto-advanced unexpectedly (sync off): "
        f"{starting_fname} -> {final_fname}"
    )


def test_no_auto_advance_when_last_bp_labeled_sync_on(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")

    starting_idx = page.evaluate("window.__fl3d.frameNumberIdx")
    starting_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    _label_every_bp_on_focused_frame(page, starting_fname)

    # Sync-on uses _fl3dFrameNumIdx / _fl3dFrameNumbers; assert both surfaces
    # of "current frame" stayed put.
    final_idx = page.evaluate("window.__fl3d.frameNumberIdx")
    final_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    assert final_idx == starting_idx, (
        f"frameNumberIdx auto-advanced unexpectedly (sync on): "
        f"{starting_idx} -> {final_idx}"
    )
    assert final_fname == starting_fname, (
        f"Focused tile fname auto-advanced unexpectedly (sync on): "
        f"{starting_fname} -> {final_fname}"
    )

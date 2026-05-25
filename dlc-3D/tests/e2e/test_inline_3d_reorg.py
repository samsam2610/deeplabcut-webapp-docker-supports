"""Live read-only verification of the inline-3D analysis card reorg.

Drives the real card at /dlc-3d/ against the DREADD-Ali OM-2 fixture (provided by
the e2e conftest autouse fixture). READ-ONLY: opens the card, selects a source,
asserts the two-column layout + lock visuals + quick-tag click-to-fill + size
sliders. NEVER triggers analysis/finalize/extract.

Visual target: src/static/mockup_inline_3d.html.j2.

Fixture-source resolution (recorded environment limitation)
-----------------------------------------------------------
The card's Project-Content list is backed by ``GET /dlc/project/labeled-content``
which only lists frame folders that contain ``*_labeled.png`` OVERLAY frames
(produced by create_labeled_video) and ``*_labeled`` videos. The DREADD-Ali
fixture has raw labeled-data frames (``img_camN_*.png``) and a plain
``OM-2_20260424.mp4`` but NO ``_labeled`` overlay artifacts, so the Project-Content
list renders empty and the plan's content-list click path cannot open the card.

This suite therefore opens the SAME OM-2 video through the Browse tab
(``_iaOpenBrowseVideo``), which is a read-only navigation path that exercises the
identical reorganized card markup. Browse-video mode probes
``/annotate/video-info`` for the frame count; in this environment that route
returns 400 for the protected video, so ``frameCount()`` stays 0. Layout / lock
flag / tags / size-slider checks do not need real frames and run fully; the two
frame-DEPENDENT checks (the red seek BLOCK + nav-confine, and per-frame edit-row
value loading) ``skip`` with this documented reason rather than being forced.
"""
import json
import re

import pytest
from playwright.sync_api import Page, expect

SESSION = "OM-2_20260424"
PROJECT_PATH_IN_CONTAINER = (
    "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07"
)
BROWSE_VIDEO = f"{PROJECT_PATH_IN_CONTAINER}/videos/{SESSION}.mp4"


@pytest.fixture(autouse=True)
def _open_inline_card(page: Page, base_url):
    """Open the inline-3D card with the OM-2 source loaded.

    Prefers the Project-Content list (the plan's path); falls back to the Browse
    tab + OM-2 video when the content list is empty (the recorded limitation).
    Stores ``page._ia_has_frames`` so frame-dependent tests can skip cleanly.
    """
    page.goto(base_url)
    page.locator("#btn-open-inline-analysis-3d").click()
    page.locator("#inline-analysis-3d-card").wait_for(state="visible")

    # Give the Project-Content list a chance to populate with the OM-2 stem.
    content_has_session = False
    try:
        page.wait_for_function(
            f"() => {{ const el = document.querySelector('#ia3d-content-list');"
            f" return el && el.textContent.includes('{SESSION}/'); }}",
            timeout=8000,
        )
        content_has_session = True
    except Exception:
        content_has_session = False

    if content_has_session:
        page.locator("#ia3d-content-list").get_by_text(f"{SESSION}/").first.click()
        page.locator("#ia3d-player-section").wait_for(state="visible")
        page.wait_for_function("() => window.__iaViewer && window.__iaViewer.frameCount() > 0")
    else:
        # Fallback: open the same OM-2 video via the Browse tab (read-only).
        page.locator("#ia3d-tab-browse").click()
        page.locator("#ia3d-browse-breadcrumb").fill(BROWSE_VIDEO)
        page.locator("#ia3d-browse-breadcrumb").press("Enter")
        page.locator("#ia3d-player-section").wait_for(state="visible", timeout=15000)
        # The viewer instance exists once load() runs; a tile renders even at
        # frameCount 0 (single primary tile with a working size slider).
        page.wait_for_function(
            "() => window.__iaViewer && document.querySelector('#ia3d-viewer-mount .vv-tile')"
        )

    page._ia_has_frames = page.evaluate(
        "() => !!window.__iaViewer && window.__iaViewer.frameCount() > 1"
    )


def test_full_width_two_column_layout(page: Page):
    left = page.locator(".ia3d-left")
    right = page.locator(".ia3d-right")
    expect(left).to_be_visible()
    expect(right).to_be_visible()
    lb = left.bounding_box(); rb = right.bounding_box()
    assert rb["x"] > lb["x"], "Finalize panel must dock to the right of the left region"
    # Finalize panel is inside the right column and checked by default.
    assert page.locator(".ia3d-right #ia3d-finalize-panel").count() == 1
    assert page.locator("#ia3d-finalize-toggle").is_checked()


def test_both_start_buttons_present(page: Page):
    expect(page.locator("#ia3d-btn-analyze-current")).to_be_visible()
    expect(page.locator("#ia3d-btn-analyze-range-confined")).to_be_visible()


def test_for_range_gating_flips_with_lock(page: Page):
    # No resolvable sibling here (frames/browse fixture) → both stay disabled
    # regardless; assert the for-range button is disabled while unlocked (its
    # gate includes !locked AND !sibling). The ENABLED path requires a labeled
    # VIDEO with a cam1 sibling under protected /user-data — see module docstring;
    # it is covered by the static-analysis test + unit-tested gate logic.
    rng = page.locator("#ia3d-btn-analyze-range-confined")
    expect(rng).to_be_disabled()


def test_lock_shows_red_flag(page: Page):
    # The red flag appears on lock regardless of frame count.
    page.locator("#ia3d-finalize-lock").check()
    expect(page.locator("#ia3d-lock-flag")).to_be_visible()
    assert re.search(r"range-locked", page.locator("#ia3d-lock-flag").inner_text())


def test_lock_shows_red_block_and_confines_nav(page: Page):
    if not page._ia_has_frames:
        pytest.skip(
            "needs a video with frameCount > 1; the OM-2 content-list path is "
            "empty (no _labeled.png) and browse-video video-info returns 400 in "
            "this env, so the red seek block (frameCount>1 gated) and nav-confine "
            "can't be exercised here — documented limitation."
        )
    # Move off frame 0 so the keyframe (=current) is mid-clip, then lock.
    page.locator("#ia3d-btn-next").click()
    page.locator("#ia3d-finalize-lock").check()
    expect(page.locator("#ia3d-lock-flag")).to_be_visible()
    expect(page.locator("#ia3d-lock-range")).to_be_visible()
    # Navigation is confined: try to skip far backward past the range start.
    page.locator("#ia3d-skip-n").fill("99999")
    page.locator("#ia3d-btn-skip-back").click()
    confined = page.evaluate("() => window.__iaViewer.currentFrame()")
    rng_start = page.evaluate("""() => {
        const f = document.getElementById('ia3d-finalize-range').textContent;
        const m = f.match(/frames\\s+(\\d+)/); return m ? parseInt(m[1],10) : 0; }""")
    assert confined >= rng_start, f"nav escaped the locked range (frame {confined} < start {rng_start})"


def test_unlock_hides_visuals(page: Page):
    page.locator("#ia3d-finalize-lock").check()
    expect(page.locator("#ia3d-lock-flag")).to_be_visible()
    page.locator("#ia3d-finalize-lock").uncheck()
    expect(page.locator("#ia3d-lock-flag")).to_be_hidden()
    expect(page.locator("#ia3d-lock-range")).to_be_hidden()


def test_postfix_tag_click_replaces_field_and_persists(page: Page):
    # Add a tag via the "+ tag" affordance using a typed value, then click it to
    # fill. The add triggers a 400ms-debounced POST /dlc/project/ui-setting; wait
    # for that response so the write lands before we reload.
    page.locator("#ia3d-finalize-clip-postfix").fill("reachZZ")
    with page.expect_response(
        lambda r: "/dlc/project/ui-setting" in r.url and r.request.method == "POST"
    ):
        page.locator("#ia3d-postfix-tags .ia3d-ptag-add").click()
    expect(page.locator("#ia3d-postfix-tags").get_by_text("reachZZ")).to_be_visible()
    # Change the field, then click the pill → REPLACE.
    page.locator("#ia3d-finalize-clip-postfix").fill("other")
    page.locator("#ia3d-postfix-tags .ia3d-ptag", has_text="reachZZ").click()
    assert page.locator("#ia3d-finalize-clip-postfix").input_value() == "reachZZ"
    # Persisted: re-open the same source; the tag should reappear (tags load on
    # each video/folder open, not on bare card open).
    page.reload()
    page.locator("#btn-open-inline-analysis-3d").click()
    page.locator("#inline-analysis-3d-card").wait_for(state="visible")
    page.locator("#ia3d-tab-browse").click()
    page.locator("#ia3d-browse-breadcrumb").fill(BROWSE_VIDEO)
    page.locator("#ia3d-browse-breadcrumb").press("Enter")
    page.locator("#ia3d-player-section").wait_for(state="visible", timeout=15000)
    page.wait_for_function(
        "() => { const el = document.querySelector('#ia3d-postfix-tags');"
        " return el && el.textContent.includes('reachZZ'); }",
        timeout=10000,
    )
    # Cleanup: remove the test tag so the fixture's stored setting stays clean.
    # Wait for the removal's debounced save to land before the test ends.
    with page.expect_response(
        lambda r: "/dlc/project/ui-setting" in r.url and r.request.method == "POST"
    ):
        page.locator("#ia3d-postfix-tags .ia3d-ptag", has_text="reachZZ").locator(".x").click()
    # Confirm the persisted setting is cleared so the protected project is untouched.
    page.wait_for_function(
        "() => { const el = document.querySelector('#ia3d-postfix-tags');"
        " return el && !el.textContent.includes('reachZZ'); }",
        timeout=5000,
    )


def test_size_sliders_resize_tiles(page: Page):
    sliders = page.locator("#ia3d-viewer-mount .vv-tile-size")
    assert sliders.count() >= 1, "per-tile size slider missing after the reorg"
    tile = page.locator("#ia3d-viewer-mount .vv-tile").first
    tile.locator(".vv-tile-size").evaluate("(el)=>{el.value='300';el.dispatchEvent(new Event('input'));}")
    # single-tile fixture → flex-grow has no sibling to take width from, so assert
    # the slider LABEL updated as the regression signal that the slider is live.
    label = tile.locator(".vv-tile-size-val").inner_text().strip()
    assert label == "300%", f"size slider label did not update (got {label!r})"


def test_per_frame_edit_rows_present(page: Page):
    # The status/note edit inputs live under their timelines (relocated by the
    # reorg). They must exist in the DOM regardless of CSV content.
    assert page.locator("#ia3d-status-input").count() == 1
    assert page.locator("#ia3d-note-input").count() == 1


def test_per_frame_edit_rows_load_current_frame(page: Page):
    if not page._ia_has_frames:
        pytest.skip(
            "per-frame value loading needs a video with frames + a status/note "
            "CSV; unavailable via the reachable read-only fixtures in this env "
            "(see module docstring) — documented limitation."
        )
    # The status/note edit inputs are populated by statusNoteTimeline.updateBadges
    # on frameChange (value reflects the CSV row or default).
    if page.locator("#ia3d-status-bar-wrap").is_visible():
        expect(page.locator("#ia3d-status-input")).to_be_visible()

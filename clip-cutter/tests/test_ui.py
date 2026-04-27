"""
Playwright GUI tests for the clip-cutter frontend.

All API endpoints are mocked so tests run without real video data and
finish in seconds. The app must be running at BASE_URL before running.

Run:
    cd clip-cutter
    pytest tests/test_ui.py -v --headed          # visible browser
    pytest tests/test_ui.py -v                    # headless (default)
    BASE_URL=http://192.168.1.x:5002 pytest tests/test_ui.py -v
"""

import base64
import json
import os
import re
import pytest
from playwright.sync_api import Page, Route, expect

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5002")

# ── Mock data ─────────────────────────────────────────────────────────────────

# Minimal 1×1 white JPEG in base64.
_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAA"
    "AAAAAAAAAAAAAAAAAP/EABQBAQAAAAAAAAAAAAAAAAAAAAD/xAAUEQEAAAAAAAAAAAAAAAAA"
    "AAAA/9oADAMBAAIRAxEAPwCwABmX/9k="
)

_MOCK_FRAMES = [
    {
        "thumbnail": _JPEG_B64,
        "video_path": f"/user-data/clip_{i}_0_799_success.avi",
        "frame_number": 200,
    }
    for i in range(19)
]

_MOCK_FS_ROOT = {
    "path": "/user-data",
    "parent": "/",
    "entries": [
        {"name": "vid1.avi", "type": "file", "done": False},
        {"name": "vid2.avi", "type": "file", "done": True},
        {"name": "vid3.avi", "type": "file", "done": False},
        {"name": "subdir", "type": "dir", "has_avi": True},
    ],
}

_MOCK_FS_SUBDIR = {
    "path": "/user-data/subdir",
    "parent": "/user-data",
    "entries": [
        {"name": "vid3.avi", "type": "file", "done": False},
    ],
}

_MOCK_DETECTIONS = [
    {
        "cv2_pos": 20967,
        "frame_number": 20968,
        "similarity": 0.8734,
        "known_match": "MAP2_0_20768_21567_success",
        "source": "sensor+clip",
    },
    {
        "cv2_pos": 51399,
        "frame_number": 51400,
        "similarity": 0.7412,
        "known_match": None,
        "source": "sensor+clip",
    },
]


# ── Route setup ───────────────────────────────────────────────────────────────

def _json(route: Route, body: dict, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def setup_routes(page: Page, *, template_frames=None, init_count=19) -> None:
    """
    Register mocked API routes on the page. Call before page.goto().

    template_frames: initial frame list served by GET /template (default: [])
    init_count: frame count reported by /template/init/status when done
    """
    state = {
        "frames": list(template_frames or []),
    }
    poll = {"calls": 0}

    def on_template_get(route: Route):
        _json(route, {"count": len(state["frames"]), "frames": state["frames"], "has_template": len(state["frames"]) > 0})

    def on_template_add(route: Route):
        state["frames"].append(_MOCK_FRAMES[0])
        _json(route, {"count": len(state["frames"])})

    def on_template_delete(route: Route):
        if state["frames"]:
            state["frames"].pop(0)
        _json(route, {"count": len(state["frames"])})

    def on_template_init(route: Route):
        _json(route, {"status": "started"}, status=202)

    def on_template_init_status(route: Route):
        poll["calls"] += 1
        if poll["calls"] < 2:
            _json(route, {"running": True, "count": 5, "error": None})
        else:
            state["frames"] = list(_MOCK_FRAMES[:init_count])
            _json(route, {"running": False, "count": init_count, "error": None})

    def on_fs_ls(route: Route):
        _json(route, _MOCK_FS_ROOT)

    def on_select_video(route: Route):
        _json(route, {"count": 0, "has_template": False})

    def on_template_clear(route: Route):
        _json(route, {"ok": True})

    def on_scan_start(route: Route):
        _json(route, {"job_id": "mock-job-abc"})

    def on_scan_stream(route: Route):
        event = json.dumps({
            "status": "done",
            "phase": "fine",
            "current": 100,
            "total": 100,
            "detections": _MOCK_DETECTIONS,
            "error": None,
        })
        route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=f"data: {event}\n\n",
        )

    def on_extract(route: Route):
        _json(route, {
            "avi_path": "/user-data/out/clip.avi",
            "csv_path": "/user-data/out/clip.csv",
            "start_frame_number": 20768,
            "end_frame_number": 21567,
        })

    # Order matters: more-specific patterns first
    page.route("**/clip-cutter/template/init/status", on_template_init_status)
    page.route("**/clip-cutter/template/init", on_template_init)
    page.route("**/clip-cutter/template/add", on_template_add)
    page.route(re.compile(r".*/clip-cutter/template/\d+"), on_template_delete)
    page.route("**/clip-cutter/template/clear", on_template_clear)
    page.route("**/clip-cutter/template", on_template_get)
    page.route("**/clip-cutter/fs/ls**", on_fs_ls)
    page.route("**/clip-cutter/select-video", on_select_video)
    page.route("**/clip-cutter/scan/stream*", on_scan_stream)
    page.route("**/clip-cutter/scan", on_scan_start)
    page.route("**/clip-cutter/extract", on_extract)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_page_loads_correct_structure(page: Page):
    """Initial page renders title, sidebar, browser list, disabled scan button."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    expect(page).to_have_title("Clip Cutter")
    expect(page.locator("h1")).to_have_text("Clip Cutter")
    expect(page.locator(".sidebar-title")).to_have_text("Template Bank")
    expect(page.locator("#sidebar-empty-state")).to_be_visible()
    expect(page.locator("#scan-btn")).to_be_disabled()
    expect(page.locator("#status-msg")).to_have_text("Ready")


def test_video_list_populates_on_load(page: Page):
    """Folder browser renders all entries with correct badges."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    rows = page.locator(".browser-row")
    expect(rows).to_have_count(4)

    first = rows.nth(0)
    expect(first.locator(".browser-name")).to_contain_text("vid1.avi")
    expect(first.locator(".badge-pending")).to_be_visible()

    second = rows.nth(1)
    expect(second.locator(".badge-done")).to_be_visible()


def test_done_video_row_cannot_be_selected(page: Page):
    """Clicking a done video row does not enable the scan button."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".browser-row:has(.badge-done)").click()
    expect(page.locator("#scan-btn")).to_be_disabled()


def test_selecting_video_enables_scan_button(page: Page):
    """Clicking a ready video row selects it and enables the scan button."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    first_ready = page.locator(".browser-row:has(.badge-pending)").first
    first_ready.click()

    expect(first_ready).to_have_class(re.compile(r"selected"))
    expect(page.locator("#scan-btn")).to_be_enabled()


def test_only_one_video_selected_at_a_time(page: Page):
    """Selecting a second video deselects the first."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    ready = page.locator(".browser-row:has(.badge-pending)")
    ready.nth(0).click()
    ready.nth(1).click()

    expect(page.locator(".browser-row.selected")).to_have_count(1)
    expect(page.locator("#scan-btn")).to_be_enabled()


def test_template_init_flow(page: Page):
    """
    Clicking Init POSTs to /template/init, polls /status, shows progress
    messages, and fills the sidebar with thumbnails when done.
    """
    setup_routes_with_persistence(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    # Select a video first to activate the Init button
    page.locator(".browser-row:has(.badge-pending)").first.click()
    expect(page.locator("#sidebar-init-btn")).to_be_visible()

    page.locator("#sidebar-init-btn").click()
    expect(page.locator("#status-msg")).to_contain_text("Building template")

    # Wait for polling to complete (up to 12 s; poll interval is 2 s)
    expect(page.locator("#template-footer")).to_have_text(
        "19 frames loaded", timeout=12_000
    )
    expect(page.locator("#status-msg")).to_contain_text("Template initialised: 19")
    expect(page.locator(".thumb")).to_have_count(19)


def test_template_frame_removal(page: Page):
    """Clicking a thumbnail prompts for confirmation then removes the frame."""
    setup_routes(page, template_frames=_MOCK_FRAMES[:3])
    page.goto(f"{BASE_URL}/clip-cutter/")

    # Select a video to load its template into the sidebar
    page.locator(".browser-row:has(.badge-pending)").first.click()

    expect(page.locator(".thumb")).to_have_count(3)
    expect(page.locator("#template-footer")).to_have_text("3 frames loaded")

    page.once("dialog", lambda d: d.accept())
    page.locator(".thumb").first.click()

    expect(page.locator(".thumb")).to_have_count(2)
    expect(page.locator("#template-footer")).to_have_text("2 frames loaded")


def test_template_frame_removal_cancelled(page: Page):
    """Dismissing the confirmation dialog keeps the frame count unchanged."""
    setup_routes(page, template_frames=_MOCK_FRAMES[:3])
    page.goto(f"{BASE_URL}/clip-cutter/")

    # Select a video to load its template into the sidebar
    page.locator(".browser-row:has(.badge-pending)").first.click()

    page.once("dialog", lambda d: d.dismiss())
    page.locator(".thumb").first.click()

    expect(page.locator(".thumb")).to_have_count(3)


def test_scan_flow_shows_detections(page: Page):
    """
    Scanning: progress section appears, results render with correct
    similarity scores, match badges, and clip filenames.
    """
    setup_routes(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()

    expect(page.locator("#results-count")).to_have_text("2 found", timeout=8_000)
    cards = page.locator(".result-card")
    expect(cards).to_have_count(2)

    first = cards.nth(0)
    expect(first.locator(".match-pill")).to_have_class(re.compile(r"match-known"))
    expect(first.locator(".sim-pill")).to_have_text("0.87")
    expect(first.locator(".result-name")).to_contain_text(".avi")

    second = cards.nth(1)
    expect(second.locator(".match-pill")).to_have_class(re.compile(r"match-new"))
    expect(second).to_have_class(re.compile(r"\bnew\b"))


def test_pipeline_strip_all_done_after_scan(page: Page):
    """After scan completes all pipeline steps are marked done."""
    setup_routes(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()

    expect(page.locator("#results-count")).to_have_text("2 found", timeout=8_000)

    for phase in ("coarse", "peak_detection", "fine"):
        step = page.locator(f'.pipeline-step[data-phase="{phase}"]')
        expect(step).to_have_class(re.compile(r"\bdone\b"))


def test_keep_detection_grays_out_card(page: Page):
    """Clicking Keep calls /extract and marks the card as kept."""
    setup_routes(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2, timeout=8_000)

    keep_btn = cards.nth(0).locator("button", has_text="Keep")
    keep_btn.click()

    expect(cards.nth(0)).to_have_class(re.compile(r"kept"))
    expect(keep_btn).to_be_disabled()
    expect(page.locator("#status-msg")).to_contain_text("Clip extracted")


def test_reject_detection_grays_out_card(page: Page):
    """Clicking Reject marks the card as rejected without calling /extract."""
    setup_routes(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2, timeout=8_000)

    reject_btn = cards.nth(1).locator("button", has_text="Reject")
    reject_btn.click()

    expect(cards.nth(1)).to_have_class(re.compile(r"rejected"))
    expect(reject_btn).to_be_disabled()


def test_add_detection_to_template(page: Page):
    """Clicking + Add to template calls /template/add and updates footer count."""
    setup_routes(page, template_frames=_MOCK_FRAMES[:5])
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".browser-row:has(.badge-pending)").first.click()
    expect(page.locator("#template-footer")).to_have_text("5 frames loaded")

    page.locator("#scan-btn").click()

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2, timeout=8_000)

    cards.nth(0).locator("button", has_text="Add to template").click()

    expect(page.locator("#template-footer")).to_have_text("6 frames loaded")


def test_rescan_clears_previous_results(page: Page):
    """Starting a second scan replaces the previous detection cards."""
    setup_routes(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    # Scan button re-enabled after first completes; run again
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)


# ── Persistence mock data ──────────────────────────────────────────────────────

_MOCK_SAVED_DETECTIONS = {
    "video_path": "/user-data/vid1.avi",
    "scan_timestamp": "2026-04-26T12:00:00",
    "template_frame_count": 19,
    "detections": [
        {
            "cv2_pos": 20967,
            "frame_number": 20968,
            "similarity": 0.8734,
            "known_match": "MAP2_0_20768_21567_success",
            "status": "kept",
            "source": "sensor+clip",
        },
        {
            "cv2_pos": 51399,
            "frame_number": 51400,
            "similarity": 0.7412,
            "known_match": None,
            "status": "rejected",
            "source": "sensor+clip",
        },
    ],
}


def setup_routes_with_persistence(
    page: Page,
    *,
    template_frames=None,
    saved_detections=None,
    put_detections_calls=None,
) -> None:
    """Like setup_routes but also mocks /detections, /video-info, /frame."""
    setup_routes(page, template_frames=template_frames)

    def on_detections(route: Route):
        if route.request.method == "PUT":
            if put_detections_calls is not None:
                put_detections_calls.append(json.loads(route.request.post_data))
            _json(route, {"ok": True})
        else:
            if saved_detections is None:
                _json(route, {"error": "not found"}, status=404)
            else:
                _json(route, saved_detections)

    def on_video_info(route: Route):
        _json(route, {"frame_count": 26492, "fps": 30.0})

    def on_frame(route: Route):
        route.fulfill(
            status=200,
            content_type="image/jpeg",
            body=base64.b64decode(_JPEG_B64),
        )

    page.route("**/clip-cutter/detections*", on_detections)
    page.route("**/clip-cutter/video-info*", on_video_info)
    page.route("**/clip-cutter/frame*", on_frame)


def test_saved_detections_load_on_video_select(page: Page):
    """Selecting a video with saved results auto-populates cards without scanning."""
    setup_routes_with_persistence(
        page,
        template_frames=_MOCK_FRAMES,
        saved_detections=_MOCK_SAVED_DETECTIONS,
    )
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".browser-row:has(.badge-pending)").first.click()

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2, timeout=5_000)
    expect(page.locator("#results-count")).to_have_text("2 found")


def test_saved_statuses_restored_on_load(page: Page):
    """Cards restored from saved JSON show kept/rejected classes."""
    setup_routes_with_persistence(
        page,
        template_frames=_MOCK_FRAMES,
        saved_detections=_MOCK_SAVED_DETECTIONS,
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2, timeout=5_000)
    expect(cards.nth(0)).to_have_class(re.compile(r"\bkept\b"))
    expect(cards.nth(1)).to_have_class(re.compile(r"\brejected\b"))


def test_scan_button_still_enabled_with_saved_results(page: Page):
    """Scan button is enabled even when saved results are loaded."""
    setup_routes_with_persistence(
        page,
        template_frames=_MOCK_FRAMES,
        saved_detections=_MOCK_SAVED_DETECTIONS,
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=5_000)
    expect(page.locator("#scan-btn")).to_be_enabled()


def test_reject_persists_via_put_detections(page: Page):
    """Clicking Reject calls PUT /detections with status rejected."""
    put_calls = []
    setup_routes_with_persistence(
        page,
        template_frames=_MOCK_FRAMES,
        saved_detections=None,
        put_detections_calls=put_calls,
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2, timeout=8_000)
    with page.expect_request(
        lambda r: r.method == "PUT"
        and "/clip-cutter/detections" in r.url
        and "rejected" in (r.post_data or "")
    ):
        cards.nth(1).locator("button", has_text="Reject").click()

    assert any(
        any(d.get("status") == "rejected" for d in call.get("detections", []))
        for call in put_calls
    )


def test_rescan_overwrites_saved_results(page: Page):
    """Re-scanning clears previous cards and shows fresh detections."""
    setup_routes_with_persistence(
        page,
        template_frames=_MOCK_FRAMES,
        saved_detections=_MOCK_SAVED_DETECTIONS,
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=5_000)

    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)
    # After rescan neither card should be kept/rejected
    for i in range(2):
        card = page.locator(".result-card").nth(i)
        expect(card).not_to_have_class(re.compile(r"\bkept\b"))
        expect(card).not_to_have_class(re.compile(r"\brejected\b"))


def test_player_placeholder_visible_before_card_click(page: Page):
    """Player placeholder is shown before any detection card is clicked."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    expect(page.locator("#player-placeholder")).to_be_visible()
    expect(page.locator("#player-container")).to_be_hidden()


def test_clicking_card_shows_player(page: Page):
    """Clicking a detection card hides the placeholder and shows the player."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    # Click the card body (non-button part) to trigger the player
    page.locator(".result-card").first.locator(".result-name").click()

    expect(page.locator("#player-container")).to_be_visible(timeout=5_000)
    expect(page.locator("#player-placeholder")).to_be_hidden()


def test_player_next_frame_advances_counter(page: Page):
    """Clicking next-frame button increments the frame counter."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    page.locator(".result-card").first.locator(".result-name").click()
    expect(page.locator("#player-container")).to_be_visible(timeout=5_000)

    frame_text_before = page.locator("#player-frame-num").inner_text()
    page.locator("#player-next").click()
    expect(page.locator("#player-frame-num")).not_to_have_text(frame_text_before, timeout=3_000)


def test_player_keyframe_button_jumps_to_keyframe(page: Page):
    """Key frame button seeks to the detection's frame_number (0-based display)."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    page.locator(".result-card").first.locator(".result-name").click()
    expect(page.locator("#player-container")).to_be_visible(timeout=5_000)

    frame_at_start = page.locator("#player-frame-num").inner_text()
    page.locator("#player-prev").click()
    expect(page.locator("#player-frame-num")).not_to_have_text(frame_at_start, timeout=3_000)

    page.locator("#player-keyframe").click()
    # first detection: frame_number=20968, 0-based=20967
    expect(page.locator("#player-frame-num")).to_have_text("fr 20967", timeout=3_000)


# ── Task 7/8: Settings panel, source badge, scan POST params ──────────────────

def test_settings_panel_collapsed_on_load(page: Page):
    """Settings body #settings-body is hidden when the page first loads."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    expect(page.locator("#settings-body")).to_be_hidden()


def test_settings_panel_toggle(page: Page):
    """Clicking #settings-toggle once opens the settings body; clicking again closes it."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click("#settings-toggle")
    expect(page.locator("#settings-body")).to_be_visible()
    page.click("#settings-toggle")
    expect(page.locator("#settings-body")).to_be_hidden()


def test_settings_clip_tab(page: Page):
    """Clicking the CLIP tab shows #tab-clip and hides #tab-sensor."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click("#settings-toggle")
    page.click(".tab-btn[data-tab='clip']")
    expect(page.locator("#tab-clip")).to_be_visible()
    expect(page.locator("#tab-sensor")).to_be_hidden()


def test_settings_reset(page: Page):
    """After changing inputs, clicking Reset restores defaults."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click("#settings-toggle")
    page.fill("#trigger-value", "99")
    page.fill("#sensor-margin", "50")
    page.click("#settings-reset")
    expect(page.locator("#trigger-value")).to_have_value("14")
    expect(page.locator("#sensor-margin")).to_have_value("25")


def test_threshold_slider_label(page: Page):
    """Moving the threshold slider updates the #threshold-label text."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click("#settings-toggle")
    page.click(".tab-btn[data-tab='clip']")
    page.fill("#scan-threshold", "0.85")
    page.dispatch_event("#scan-threshold", "input")
    expect(page.locator("#threshold-label")).to_have_text("0.85")


def test_scan_post_contains_params(page: Page):
    """Intercepting the scan POST verifies the params object with all 6 keys."""
    captured = {}

    def on_scan(route: Route):
        body = route.request.post_data
        captured["body"] = json.loads(body) if body else {}
        _json(route, {"job_id": "mock-job-abc"})

    setup_routes(page, template_frames=_MOCK_FRAMES)
    # Playwright matches routes LIFO — this handler fires before the one in setup_routes.
    page.route("**/clip-cutter/scan", on_scan)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()

    # Wait for scan to be called (stream will complete)
    expect(page.locator("#results-count")).to_have_text("2 found", timeout=8_000)

    assert "params" in captured["body"], f"params key missing from POST body: {captured['body']}"
    params = captured["body"]["params"]
    expected_keys = {"trigger_value", "sensor_margin", "stride", "threshold", "min_spacing", "fine_window"}
    missing = expected_keys - set(params.keys())
    assert not missing, f"params missing keys: {missing}"


def test_source_badge_sensor_clip(page: Page):
    """Injecting a detection with source='sensor+clip' renders the correct badge."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.wait_for_function("typeof renderDetections === 'function'")
    page.evaluate("""
        renderDetections([{
            video_path: "/fake/video.avi",
            frame_number: 1234,
            similarity: 0.87,
            source: "sensor+clip",
            known_match: null,
            status: "pending"
        }]);
    """)
    badge = page.locator(".source-badge.source-sensor-clip")
    expect(badge).to_be_visible()
    expect(badge).to_have_text("✓ sensor+CLIP")


def test_no_source_badge_when_absent(page: Page):
    """Injecting a detection with no source field renders no source badge."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.wait_for_function("typeof renderDetections === 'function'")
    page.evaluate("""
        renderDetections([{
            video_path: "/fake/video.avi",
            frame_number: 5678,
            similarity: 0.75,
            known_match: null,
            status: "pending"
        }]);
    """)
    expect(page.locator(".source-badge")).to_have_count(0)


# ── Source filter tests ───────────────────────────────────────────────────────

_FILTER_DETECTIONS = [
    {"frame_number": 100, "similarity": 0.90, "source": "sensor+clip",
     "video_path": "/user-data/vid1.avi", "known_match": None, "status": "pending"},
    {"frame_number": 200, "similarity": 0.80, "source": "clip_only",
     "video_path": "/user-data/vid1.avi", "known_match": None, "status": "pending"},
    {"frame_number": 300, "similarity": 0.75, "source": "sensor_only",
     "video_path": "/user-data/vid1.avi", "known_match": None, "status": "pending"},
]


def _inject_filter_detections(page, dets):
    page.wait_for_function("typeof renderDetections === 'function'")
    page.evaluate(f"renderDetections({json.dumps(dets)})")


def test_filter_bar_visible(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    expect(page.locator("#source-filter")).to_be_visible()


def test_filter_default_active_is_sensor_clip(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    active = page.locator(".filter-btn.active")
    expect(active).to_have_attribute("data-filter", "sensor+clip")


def test_filter_default_hides_clip_only_cards(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    _inject_filter_detections(page, _FILTER_DETECTIONS)
    expect(page.locator(".result-card[data-source='sensor+clip']")).to_be_visible()
    expect(page.locator(".result-card[data-source='clip_only']")).to_be_hidden()


def test_filter_all_shows_every_card(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    _inject_filter_detections(page, _FILTER_DETECTIONS)
    page.click(".filter-btn[data-filter='all']")
    expect(page.locator(".result-card[data-source='sensor+clip']")).to_be_visible()
    expect(page.locator(".result-card[data-source='clip_only']")).to_be_visible()
    expect(page.locator(".result-card[data-source='sensor_only']")).to_be_visible()


def test_filter_clip_only_shows_only_clip_cards(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    _inject_filter_detections(page, _FILTER_DETECTIONS)
    page.click(".filter-btn[data-filter='clip_only']")
    expect(page.locator(".result-card[data-source='sensor+clip']")).to_be_hidden()
    expect(page.locator(".result-card[data-source='clip_only']")).to_be_visible()
    expect(page.locator(".result-card[data-source='sensor_only']")).to_be_hidden()


def test_filter_sensor_only_cards_visible_only_in_all(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    _inject_filter_detections(page, _FILTER_DETECTIONS)
    # Default (sensor+clip filter): sensor_only hidden
    expect(page.locator(".result-card[data-source='sensor_only']")).to_be_hidden()
    # clip_only filter: sensor_only still hidden
    page.click(".filter-btn[data-filter='clip_only']")
    expect(page.locator(".result-card[data-source='sensor_only']")).to_be_hidden()
    # All: sensor_only visible
    page.click(".filter-btn[data-filter='all']")
    expect(page.locator(".result-card[data-source='sensor_only']")).to_be_visible()


def test_filter_active_button_updates_on_click(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".filter-btn[data-filter='all']")
    expect(page.locator(".filter-btn[data-filter='all']")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator(".filter-btn[data-filter='sensor\\+clip']")).not_to_have_class(
        re.compile(r"\bactive\b")
    )


# ── Folder browser tests ──────────────────────────────────────────────────────

def test_browser_shows_avi_entries(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    expect(page.locator("#browser-list")).to_be_visible()
    expect(page.locator(".browser-row")).to_have_count(4)


def test_browser_shows_done_badge_for_done_video(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    done_row = page.locator(".browser-row").filter(has_text="vid2.avi")
    expect(done_row.locator(".badge-done")).to_be_visible()


def test_browser_clicking_dir_navigates_into_it(page: Page):
    import json as _json_lib
    call_count = {"n": 0}

    def handle_ls(route):
        call_count["n"] += 1
        body = _MOCK_FS_ROOT if call_count["n"] == 1 else _MOCK_FS_SUBDIR
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json_lib.dumps(body),
        )

    # setup_routes first, then override fs/ls with our handler (LIFO: last registered fires first)
    setup_routes(page)
    page.route("**/clip-cutter/fs/ls**", handle_ls)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".browser-row:has-text('subdir')")
    expect(page.locator("#browser-list")).to_contain_text("vid3.avi")


def test_browser_selecting_video_shows_sidebar_no_template(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".browser-row:has-text('vid1.avi')")
    expect(page.locator("#sidebar-no-template")).to_be_visible()
    expect(page.locator("#sidebar-init-btn")).to_be_visible()


def test_sidebar_empty_state_shown_on_load(page: Page):
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    expect(page.locator("#sidebar-empty-state")).to_be_visible()
    expect(page.locator("#sidebar-init-btn")).to_be_hidden()


def test_clear_modal_requires_delete_word(page: Page):
    # setup_routes first, then override select-video (LIFO: last registered fires first)
    setup_routes(page, template_frames=_MOCK_FRAMES[:2])
    page.route(
        "**/clip-cutter/select-video",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"count": 2, "has_template": true}',
        ),
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".browser-row:has-text('vid1.avi')")
    expect(page.locator("#sidebar-actions")).to_be_visible()
    page.click("#sidebar-clear-btn")
    expect(page.locator("#clear-confirm-modal")).to_have_class(re.compile(r"\bopen\b"))
    expect(page.locator("#clear-confirm-btn")).to_be_disabled()
    page.fill("#clear-confirm-input", "delete")
    expect(page.locator("#clear-confirm-btn")).to_be_enabled()


def test_clear_modal_cancel_closes_modal(page: Page):
    # setup_routes first, then override select-video (LIFO: last registered fires first)
    setup_routes(page, template_frames=_MOCK_FRAMES[:2])
    page.route(
        "**/clip-cutter/select-video",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"count": 2, "has_template": true}',
        ),
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".browser-row:has-text('vid1.avi')")
    page.click("#sidebar-clear-btn")
    page.click("#clear-cancel-btn")
    expect(page.locator("#clear-confirm-modal")).not_to_have_class(re.compile(r"\bopen\b"))

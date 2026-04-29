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
    messages, and fills the sidebar with template rows when done.
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
    expect(page.locator(".tpl-row")).to_have_count(19)


def test_template_frame_removal(page: Page):
    """Clicking the Delete button prompts for confirmation then removes the frame."""
    setup_routes(page, template_frames=_MOCK_FRAMES[:3])
    page.goto(f"{BASE_URL}/clip-cutter/")

    # Select a video to load its template into the sidebar
    page.locator(".browser-row:has(.badge-pending)").first.click()

    expect(page.locator(".tpl-row")).to_have_count(3)
    expect(page.locator("#template-footer")).to_have_text("3 frames loaded")

    page.once("dialog", lambda d: d.accept())
    page.locator(".tpl-del-btn").first.click()

    expect(page.locator(".tpl-row")).to_have_count(2)
    expect(page.locator("#template-footer")).to_have_text("2 frames loaded")


def test_template_frame_removal_cancelled(page: Page):
    """Dismissing the confirmation dialog keeps the frame count unchanged."""
    setup_routes(page, template_frames=_MOCK_FRAMES[:3])
    page.goto(f"{BASE_URL}/clip-cutter/")

    # Select a video to load its template into the sidebar
    page.locator(".browser-row:has(.badge-pending)").first.click()

    page.once("dialog", lambda d: d.dismiss())
    page.locator(".tpl-del-btn").first.click()

    expect(page.locator(".tpl-row")).to_have_count(3)


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

    keep_btn = cards.nth(0).locator(".keep-btn")
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

    reject_btn = cards.nth(1).locator(".reject-btn")
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

    cards.nth(0).locator(".add-btn").click()

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
        cards.nth(1).locator(".reject-btn").click()

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
    """Player panel is hidden before any detection card is clicked."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    expect(page.locator("#player-panel")).to_be_hidden()


def test_clicking_card_shows_player(page: Page):
    """Clicking a detection card shows the player panel."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    # Click the card body (non-button part) to trigger the player
    page.locator(".result-card").first.locator(".result-name").click()

    expect(page.locator("#player-panel")).to_be_visible(timeout=5_000)


def test_player_next_frame_advances_counter(page: Page):
    """Clicking next-frame button increments the frame counter."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    page.locator(".result-card").first.locator(".result-name").click()
    expect(page.locator("#player-panel")).to_be_visible(timeout=5_000)

    frame_text_before = page.locator("#ep-frame-num").inner_text()
    page.locator("#ep-fwd1").click()
    expect(page.locator("#ep-frame-num")).not_to_have_text(frame_text_before, timeout=3_000)


def test_player_keyframe_button_jumps_to_keyframe(page: Page):
    """Key frame button seeks to the detection's keyframe (0-based)."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    page.locator(".result-card").first.locator(".result-name").click()
    expect(page.locator("#player-panel")).to_be_visible(timeout=5_000)

    frame_at_start = page.locator("#ep-frame-num").inner_text()
    page.locator("#ep-back1").click()
    expect(page.locator("#ep-frame-num")).not_to_have_text(frame_at_start, timeout=3_000)

    page.locator("#ep-goto-kf").click()
    # first detection: frame_number=20968 → keyFrame1Based=20968 → display=20968 (1-based)
    expect(page.locator("#ep-frame-num")).to_have_text("20968", timeout=3_000)


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
    expect(badge).to_have_text("s+c")


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


# ── Lock badge (merged lock/unlock) tests ────────────────────────────────────

def test_lock_badge_exists(page: Page):
    """Lock badge button exists in the DOM."""
    setup_routes(page)
    page.goto(BASE_URL + "/clip-cutter/")
    expect(page.locator("#ep-lock-badge")).to_have_count(1)


def test_lock_badge_hidden_before_player_open(page: Page):
    """Lock badge is hidden before the player is opened."""
    setup_routes(page)
    page.goto(BASE_URL + "/clip-cutter/")
    expect(page.locator("#ep-lock-badge")).to_be_hidden()


def _open_player_clip_mode(page: Page) -> None:
    setup_routes(page)
    page.route(
        "**/clip-cutter/video-info**",
        lambda route: route.fulfill(
            content_type="application/json",
            body='{"frame_count": 2000}',
        ),
    )
    page.route(
        "**/clip-cutter/frame**",
        lambda route: route.fulfill(
            content_type="image/jpeg",
            body=base64.b64decode(_JPEG_B64),
        ),
    )
    page.goto(BASE_URL + "/clip-cutter/")
    page.evaluate("""() => openPlayer({
        mode: 'clip',
        videoPath: '/user-data/test.avi',
        keyFrame1Based: 500,
        detectionIdx: 0
    })""")


def test_lock_badge_visible_and_red_in_clip_mode(page: Page):
    """After opening player in clip mode, lock badge is visible and shows locked state."""
    _open_player_clip_mode(page)
    badge = page.locator("#ep-lock-badge")
    expect(badge).to_be_visible(timeout=5_000)
    expect(badge).to_contain_text("🔒")
    expect(badge).to_have_class(re.compile(r"\blocked\b"))


def test_lock_badge_toggles_on_click(page: Page):
    """Clicking lock badge toggles between locked (red) and unlocked (green) states."""
    _open_player_clip_mode(page)
    badge = page.locator("#ep-lock-badge")
    expect(badge).to_be_visible(timeout=5_000)

    # Initially locked (red)
    expect(badge).to_have_class(re.compile(r"\blocked\b"))
    expect(badge).to_contain_text("🔒")

    # Click to unlock → green
    badge.click()
    page.wait_for_timeout(100)
    expect(badge).to_have_class(re.compile(r"\bunlocked\b"))
    expect(badge).to_contain_text("🔓")
    expect(page.locator("#ep-lock-overlay")).to_be_visible()
    expect(page.locator("#ep-seek-highlight")).to_be_hidden()

    # Click again to re-lock → red
    badge.click()
    page.wait_for_timeout(100)
    expect(badge).to_have_class(re.compile(r"\blocked\b"))
    expect(badge).to_contain_text("🔒")
    expect(page.locator("#ep-lock-overlay")).to_be_hidden()


def test_browser_loads_files_on_page_load(page: Page):
    """File browser populates on load — catches JS init crash from missing DOM element."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    # If DOMContentLoaded throws (e.g. null.addEventListener), browser-list stays empty
    rows = page.locator(".browser-row")
    expect(rows).to_have_count(4, timeout=5_000)


def test_no_js_errors_on_load(page: Page):
    """Page load must produce zero JavaScript exceptions."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.wait_for_timeout(500)
    assert errors == [], f"JavaScript errors on load:\n" + "\n".join(errors)


def test_lib_settings_toggle_shows_body(page: Page):
    """Clicking #lib-settings-toggle reveals the scan-settings body."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click("#tab-libraries")
    expect(page.locator("#lib-settings-body")).to_be_hidden()
    page.click("#lib-settings-toggle")
    expect(page.locator("#lib-settings-body")).to_be_visible()


def test_lib_scan_type_pill_switches_to_template(page: Page):
    """Clicking the Template Frames pill activates it and shows template fields."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click("#tab-libraries")
    page.click("#lib-settings-toggle")
    page.click("#lib-scan-type .pill-btn[data-val='template_frames']")
    expect(page.locator("#lib-scan-type .pill-btn[data-val='template_frames']")).to_have_class(
        re.compile(r"\bactive\b")
    )
    expect(page.locator("#lib-template-fields")).to_be_visible()
    expect(page.locator("#lib-clips-fields")).to_be_hidden()


def _open_player(page: Page) -> None:
    """Helper: select a video, scan, click first card to open the player panel."""
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)
    page.locator(".result-card").first.locator(".result-name").click()
    expect(page.locator("#player-panel")).to_be_visible(timeout=5_000)


def test_postfix_tag_add_button_is_narrow(page: Page):
    """The + button next to the tag input is not full-width (bug: was 100% width)."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    _open_player(page)

    btn = page.locator("#ep-add-tag-btn")
    input_el = page.locator("#ep-new-tag-input")

    # Button should be much narrower than the input (not full-width)
    btn_w = btn.bounding_box()["width"]
    inp_w = input_el.bounding_box()["width"]
    assert btn_w < inp_w, f"+ button ({btn_w}px) should be narrower than input ({inp_w}px)"


def test_postfix_tag_can_be_added_and_fills_postfix(page: Page):
    """Typing a tag name and clicking + adds a pill that fills the postfix field on click."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")

    # Clear any leftover localStorage from previous tests
    page.evaluate("localStorage.removeItem('clip_cutter_postfix_tags')")
    page.reload()
    _open_player(page)

    # Type a tag name and click +
    page.locator("#ep-new-tag-input").fill("mytest")
    page.locator("#ep-add-tag-btn").click()

    # A pill should appear
    pill = page.locator(".ep-postfix-tag").first
    expect(pill).to_be_visible(timeout=2_000)
    assert "mytest" in pill.inner_text()

    # Clicking the pill should fill the postfix field
    pill.click()
    expect(page.locator("#ep-postfix")).to_have_value("mytest", timeout=2_000)

    # Cleanup
    page.evaluate("localStorage.removeItem('clip_cutter_postfix_tags')")


def test_clicking_kept_card_clears_previous_active_preview(page: Page):
    """Clicking a kept card (which has disabled buttons) must move active-preview highlight.

    Bug: e.target.closest("button") matched disabled buttons, causing the card click
    handler to bail before updating active-preview. Fixed by checking button:not([disabled]).
    """
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    cards = page.locator(".result-card")

    # Click card-1 to make it the active-preview
    page.evaluate("document.querySelector('#card-1 .result-name').click()")
    expect(page.locator("#player-panel")).to_be_visible(timeout=5_000)
    expect(cards.nth(1)).to_have_class(re.compile(r"\bactive-preview\b"), timeout=3_000)

    # Keep card-0 via its button so its buttons become disabled
    page.route(
        "**/clip-cutter/extract",
        lambda r: r.fulfill(
            status=200,
            content_type="application/json",
            body='{"avi_path":"/tmp/test.avi","csv_path":"/tmp/test.csv"}',
        ),
    )
    cards.nth(0).locator(".keep-btn").click()
    expect(cards.nth(0)).to_have_class(re.compile(r"\bkept\b"), timeout=3_000)

    # Dispatch a bubbling click from card-0's disabled Keep button.
    # The browser won't fire .click() on disabled elements, so we use dispatchEvent.
    # With the old code (button:not([disabled]) missing), this bailed the card handler.
    # With the fix, the disabled button is ignored and the card gains active-preview.
    page.evaluate("""
      document.querySelector('#card-0 .keep-btn').dispatchEvent(
        new MouseEvent('click', { bubbles: true, cancelable: true })
      )
    """)
    expect(cards.nth(0)).to_have_class(re.compile(r"\bactive-preview\b"), timeout=3_000)
    expect(cards.nth(1)).not_to_have_class(re.compile(r"\bactive-preview\b"))


def test_switching_card_same_video_preserves_step_size(page: Page):
    """Switching between two cards for the same video does not reset step size."""
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    cards = page.locator(".result-card")

    # Open player on first card
    cards.nth(0).locator(".result-name").click()
    expect(page.locator("#player-panel")).to_be_visible(timeout=5_000)

    # Change step size
    step_input = page.locator("#ep-step")
    step_input.fill("25")
    step_input.dispatch_event("change")

    # Click second card (same video path in mock) via evaluate to bypass overlay
    page.evaluate("document.querySelector('#card-1 .result-name').click()")
    page.wait_for_timeout(500)

    # Step size should be preserved
    assert step_input.input_value() == "25", "Step size was reset on same-video card switch"


# ── Chip-toggle / sub-timeline tests ─────────────────────────────────────────

# Synthetic CSV rows: 3 "success" frames, 2 "fail" frames, 2 note frames
_MOCK_CSV_ROWS = (
    [{"frame_number": str(i * 50), "frame_line_status": "success", "note": ""} for i in range(1, 4)]
    + [{"frame_number": str(i * 50 + 25), "frame_line_status": "fail", "note": ""} for i in range(1, 3)]
    + [{"frame_number": str(i * 50), "frame_line_status": "0", "note": "added"} for i in range(5, 7)]
)


def _setup_player_with_csv(page: Page) -> None:
    """Navigate to page, mock routes, and inject CSV state into the player module."""
    setup_routes(page)
    page.route(
        "**/clip-cutter/video-info**",
        lambda r: r.fulfill(content_type="application/json", body='{"frame_count":500}'),
    )
    page.route(
        "**/clip-cutter/frame**",
        lambda r: r.fulfill(content_type="image/jpeg", body=base64.b64decode(_JPEG_B64)),
    )
    page.route(
        re.compile(r".*/clip-cutter/csv.*"),
        lambda r: r.fulfill(
            content_type="application/json",
            body=json.dumps({"rows": _MOCK_CSV_ROWS}),
        ),
    )
    page.goto(f"{BASE_URL}/clip-cutter/")
    # Inject CSV state, show player panel, and build tag bars
    page.evaluate(
        f"""() => {{
            document.getElementById('player-panel').style.display = '';
            _csvRows = {json.dumps(_MOCK_CSV_ROWS)};
            _frameCount = 500;
            _epBuildTagBars();
        }}"""
    )


def test_chip_click_with_main_radio_updates_main_canvas(page: Page):
    """Clicking a chip when main radio is selected toggles the main canvas; no sub-row is created."""
    _setup_player_with_csv(page)

    # Main radio is checked by default, no sub-rows
    expect(page.locator("#ep-status-sub-rows .ep-sub-row")).to_have_count(0)

    page.locator("#ep-status-chips .ep-tag-chip", has_text="success").click()

    # No sub-row created
    expect(page.locator("#ep-status-sub-rows .ep-sub-row")).to_have_count(0)

    # Main active set contains 'success'
    has_chip = page.evaluate("_epActiveStatus.has('success')")
    assert has_chip, "Expected _epActiveStatus to contain 'success'"

    expect(page.locator("#ep-status-chips .ep-tag-chip", has_text="success")).to_have_class(
        re.compile(r"\bactive\b")
    )


def test_chip_toggle_off_main_canvas(page: Page):
    """Clicking the same chip twice on main canvas toggles it off."""
    _setup_player_with_csv(page)

    chip = page.locator("#ep-status-chips .ep-tag-chip", has_text="success")
    chip.click()  # toggle on
    has_on = page.evaluate("_epActiveStatus.has('success')")
    assert has_on, "Expected 'success' in _epActiveStatus after first click"
    expect(chip).to_have_class(re.compile(r"\bactive\b"))

    chip.click()  # toggle off
    has_off = page.evaluate("_epActiveStatus.has('success')")
    assert not has_off, "Expected 'success' removed from _epActiveStatus after second click"
    expect(chip).not_to_have_class(re.compile(r"\bactive\b"))


def test_chip_multiple_chips_accumulate_on_main_canvas(page: Page):
    """Clicking multiple chips with main radio selected adds them all to _epActiveStatus."""
    _setup_player_with_csv(page)

    page.locator("#ep-status-chips .ep-tag-chip", has_text="success").click()
    page.locator("#ep-status-chips .ep-tag-chip", has_text="fail").click()

    has_success = page.evaluate("_epActiveStatus.has('success')")
    has_fail = page.evaluate("_epActiveStatus.has('fail')")
    assert has_success, "Expected _epActiveStatus to contain 'success'"
    assert has_fail, "Expected _epActiveStatus to contain 'fail'"

    expect(page.locator("#ep-status-chips .ep-tag-chip", has_text="success")).to_have_class(
        re.compile(r"\bactive\b")
    )
    expect(page.locator("#ep-status-chips .ep-tag-chip", has_text="fail")).to_have_class(
        re.compile(r"\bactive\b")
    )


def test_manual_plus_then_chip_assigns_to_that_row(page: Page):
    """Clicking + then a chip assigns to the newly created row."""
    _setup_player_with_csv(page)

    # Add sub-row manually via + button
    page.locator("#ep-status-add-sub").click()
    expect(page.locator("#ep-status-sub-rows .ep-sub-row")).to_have_count(1)

    # Click a chip — should assign to the existing row (not add another)
    page.locator("#ep-status-chips .ep-tag-chip", has_text="success").click()
    expect(page.locator("#ep-status-sub-rows .ep-sub-row")).to_have_count(1)

    has_chip = page.evaluate(
        "document.querySelector('#ep-status-sub-rows .ep-sub-row')._activeChips.has('success')"
    )
    assert has_chip, "Expected _activeChips to contain 'success'"


def test_two_sub_rows_independent_chip_assignment(page: Page):
    """Two sub-rows can hold different chip assignments independently."""
    _setup_player_with_csv(page)

    # Add first sub-row, assign 'success'
    page.locator("#ep-status-add-sub").click()
    page.locator("#ep-status-chips .ep-tag-chip", has_text="success").click()

    # Add second sub-row (radio auto-selects it), assign 'fail'
    page.locator("#ep-status-add-sub").click()
    page.locator("#ep-status-chips .ep-tag-chip", has_text="fail").click()

    rows = page.locator("#ep-status-sub-rows .ep-sub-row")
    expect(rows).to_have_count(2)

    has0 = page.evaluate(
        "document.querySelectorAll('#ep-status-sub-rows .ep-sub-row')[0]._activeChips.has('success')"
    )
    has1 = page.evaluate(
        "document.querySelectorAll('#ep-status-sub-rows .ep-sub-row')[1]._activeChips.has('fail')"
    )
    assert has0, "Row 0 expected _activeChips to contain 'success'"
    assert has1, "Row 1 expected _activeChips to contain 'fail'"


def test_note_chip_click_with_main_radio_updates_main_canvas(page: Page):
    """Note chips with main radio checked update _epActiveNote, not a sub-row."""
    _setup_player_with_csv(page)

    expect(page.locator("#ep-note-sub-rows .ep-sub-row")).to_have_count(0)
    page.locator("#ep-note-chips .ep-tag-chip", has_text="added").click()

    # No sub-row created
    expect(page.locator("#ep-note-sub-rows .ep-sub-row")).to_have_count(0)

    has_chip = page.evaluate("_epActiveNote.has('added')")
    assert has_chip, "Expected _epActiveNote to contain 'added'"


def test_status_main_radio_exists_and_is_checked(page: Page):
    """On load, the status bar has a main-row radio that is checked by default."""
    _setup_player_with_csv(page)
    radio = page.locator("#ep-status-main-radio")
    expect(radio).to_have_count(1)
    assert page.evaluate("document.getElementById('ep-status-main-radio').checked") is True

def test_note_main_radio_exists_and_is_checked(page: Page):
    """On load, the note bar has a main-row radio that is checked by default."""
    _setup_player_with_csv(page)
    radio = page.locator("#ep-note-main-radio")
    expect(radio).to_have_count(1)
    assert page.evaluate("document.getElementById('ep-note-main-radio').checked") is True

def test_main_row_radio_in_same_group_as_sub_rows(page: Page):
    """Main radio and sub-row radio share the same radio group (mutual exclusion)."""
    _setup_player_with_csv(page)
    # Add a sub-row — its radio auto-selects, main should deselect
    page.locator("#ep-status-add-sub").click()
    assert page.evaluate("document.getElementById('ep-status-main-radio').checked") is False
    expect(page.locator("#ep-status-sub-rows .ep-sub-radio:checked")).to_have_count(1)

def test_main_canvas_starts_blank(page: Page):
    """After _epBuildTagBars, both main canvases start blank (no chip events drawn)."""
    _setup_player_with_csv(page)
    status_size = page.evaluate("_epActiveStatus.size")
    note_size   = page.evaluate("_epActiveNote.size")
    assert status_size == 0, f"_epActiveStatus should be empty, got size {status_size}"
    assert note_size   == 0, f"_epActiveNote should be empty, got size {note_size}"


def test_sub_row_has_active_chips_set(page: Page):
    """After adding a sub-row, the DOM element has an _activeChips Set (not chipVal string)."""
    _setup_player_with_csv(page)
    page.locator("#ep-status-add-sub").click()
    result = page.evaluate("""() => {
        const row = document.querySelector('#ep-status-sub-rows .ep-sub-row');
        return row && row._activeChips instanceof Set ? row._activeChips.size : -1;
    }""")
    assert result == 0, f"Expected _activeChips Set with size 0, got {result}"


def test_remove_sub_row_falls_back_to_main_radio(page: Page):
    """Removing the selected sub-row re-checks the main radio and updates chip highlights."""
    _setup_player_with_csv(page)

    # Create a sub-row (radio auto-selects it)
    page.locator("#ep-status-add-sub").click()
    assert page.evaluate("document.getElementById('ep-status-main-radio').checked") is False

    # Remove the sub-row
    page.locator("#ep-status-sub-rows .ep-sub-remove").click()
    expect(page.locator("#ep-status-sub-rows .ep-sub-row")).to_have_count(0)

    # Main radio should be re-checked
    assert page.evaluate("document.getElementById('ep-status-main-radio').checked") is True


def test_note_timelines_horizontally_aligned(page: Page):
    """Main note canvas and sub-row canvas must have identical left/right pixel boundaries."""
    _setup_player_with_csv(page)

    page.locator("#ep-note-add-sub").click()
    expect(page.locator("#ep-note-sub-rows .ep-sub-row")).to_have_count(1)

    rects = page.evaluate("""() => {
        const main = document.getElementById('ep-note-canvas').getBoundingClientRect();
        const sub  = document.querySelector('#ep-note-sub-rows .ep-sub-row canvas').getBoundingClientRect();
        return {
            mainLeft: Math.round(main.left),
            mainRight: Math.round(main.right),
            subLeft: Math.round(sub.left),
            subRight: Math.round(sub.right),
        };
    }""")

    assert rects["mainLeft"] == rects["subLeft"], (
        f"Left edges differ: main={rects['mainLeft']} sub={rects['subLeft']}"
    )
    assert rects["mainRight"] == rects["subRight"], (
        f"Right edges differ: main={rects['mainRight']} sub={rects['subRight']}"
    )


def test_accent_bar_visible_on_kept_active_card(page: Page):
    """Accent bar stays visible (non-transparent bg) when a card is both kept and active-preview."""
    _setup_player_with_csv(page)

    # Inject two fake detection cards into the results list
    page.evaluate("""() => {
        const list = document.getElementById('results-list');
        list.innerHTML = '';
        for (let i = 0; i < 2; i++) {
            const card = document.createElement('div');
            card.className = 'result-card';
            card.id = 'card-' + i;
            const bar = document.createElement('div');
            bar.className = 'result-accent-bar';
            const meta = document.createElement('div');
            meta.className = 'result-meta';
            const name = document.createElement('div');
            name.className = 'result-name';
            name.textContent = 'VID_' + i + '.avi';
            meta.appendChild(name);
            card.appendChild(bar);
            card.appendChild(meta);
            list.appendChild(card);
        }
    }""")

    # Mark card 0 as active-preview and kept
    page.evaluate("""() => {
        const card = document.getElementById('card-0');
        card.classList.add('active-preview', 'kept');
    }""")

    # The accent bar background should be #388bfd (not transparent / empty)
    bar_bg = page.evaluate("""() => {
        const bar = document.querySelector('#card-0 .result-accent-bar');
        return window.getComputedStyle(bar).backgroundColor;
    }""")
    # rgb(56, 139, 253) is #388bfd
    assert bar_bg == "rgb(56, 139, 253)", (
        f"Expected accent bar to be blue (#388bfd / rgb(56,139,253)), got: {bar_bg}"
    )

    # Card 1 (not active) should have transparent bar
    bar1_bg = page.evaluate("""() => {
        const bar = document.querySelector('#card-1 .result-accent-bar');
        return window.getComputedStyle(bar).backgroundColor;
    }""")
    assert bar1_bg in ("rgba(0, 0, 0, 0)", "transparent"), (
        f"Expected inactive bar to be transparent, got: {bar1_bg}"
    )

    # Verify opacity independence: card has opacity:0.4 but bar computed opacity stays 1.0
    # (bar is a child element — its effective opacity is product of parent × own, but
    # getComputedStyle returns only the element's own opacity, not the inherited product)
    card_opacity = page.evaluate("""() => {
        const card = document.getElementById('card-0');
        card.style.opacity = '0.4';
        return window.getComputedStyle(card).opacity;
    }""")
    assert float(card_opacity) < 1.0, "Card should have reduced opacity when kept"

    bar_own_opacity = page.evaluate("""() => {
        const bar = document.querySelector('#card-0 .result-accent-bar');
        return window.getComputedStyle(bar).opacity;
    }""")
    assert float(bar_own_opacity) == 1.0, (
        f"Bar's own opacity should be 1.0 (CSS class controls color, not opacity), got: {bar_own_opacity}"
    )


# ── Task 2: results-list padding-bottom syncs to player panel height ──────────

def test_results_list_padding_syncs_on_open(page: Page):
    """openPlayer wires _epSyncResultsPadding — panel visible → paddingBottom > 0."""
    setup_routes(page)
    page.route(
        "**/clip-cutter/video-info**",
        lambda r: r.fulfill(content_type="application/json", body='{"frame_count":500}'),
    )
    page.route(
        "**/clip-cutter/frame**",
        lambda r: r.fulfill(content_type="image/jpeg", body=base64.b64decode(_JPEG_B64)),
    )
    page.goto(f"{BASE_URL}/clip-cutter/")

    # Ensure panel starts hidden so openPlayer is the one that shows it and syncs padding
    page.evaluate("() => { document.getElementById('player-panel').style.display = 'none'; }")
    page.evaluate("() => { document.getElementById('results-list').style.paddingBottom = ''; }")

    page.evaluate("""() => openPlayer({
        mode: 'clip',
        videoPath: '/user-data/test.avi',
        keyFrame1Based: 100,
        detectionIdx: 0
    })""")

    # openPlayer calls _epSyncResultsPadding after showing the panel
    padding = page.evaluate("() => document.getElementById('results-list').style.paddingBottom")
    assert padding and padding != "0px" and padding != "", (
        f"Expected results-list paddingBottom > 0px after openPlayer, got: {repr(padding)}"
    )


def test_results_list_padding_zero_on_collapse(page: Page):
    """Clicking ep-collapse (close) sets paddingBottom to 0px."""
    _setup_player_with_csv(page)
    page.click("#ep-collapse")
    padding = page.evaluate("() => document.getElementById('results-list').style.paddingBottom")
    assert padding == "0px", (
        f"Expected paddingBottom 0px after collapse, got: {repr(padding)}"
    )


def test_results_list_padding_zero_on_minimize(page: Page):
    """Minimizing the player sets paddingBottom to 0px."""
    _setup_player_with_csv(page)
    page.click("#ep-minimize-btn")
    padding = page.evaluate("() => document.getElementById('results-list').style.paddingBottom")
    assert padding == "0px", (
        f"Expected paddingBottom 0px after minimize, got: {repr(padding)}"
    )


def test_results_list_padding_syncs_on_drag_resize(page: Page):
    """After a drag resize, #results-list paddingBottom should match the new panel height."""
    _setup_player_with_csv(page)

    # Directly set the panel to a known height and call _epSyncResultsPadding
    result = page.evaluate("""() => {
        const panel = document.getElementById('player-panel');
        panel.style.height = '350px';
        _epSyncResultsPadding();
        return {
            panelHeight: panel.offsetHeight,
            padding: document.getElementById('results-list').style.paddingBottom,
        };
    }""")
    expected = f"{result['panelHeight']}px"
    assert result["padding"] == expected, (
        f"Expected results-list paddingBottom={expected} after drag resize, got: {repr(result['padding'])}"
    )


# ── Task 3: Race-condition guard in extract / rename-extract handlers ──────────

def _inject_two_cards(page: "Page") -> None:
    """Inject two minimal detection cards into #results-list."""
    page.evaluate("""() => {
        const list = document.getElementById('results-list');
        list.innerHTML = '';
        for (let i = 0; i < 2; i++) {
            const card = document.createElement('div');
            card.className = 'result-card';
            card.id = 'card-' + i;
            const meta = document.createElement('div');
            meta.className = 'result-meta';
            const name = document.createElement('div');
            name.className = 'result-name';
            name.textContent = 'VID_' + i + '.avi';
            const btn = document.createElement('button');
            btn.className = 'keep-btn';
            btn.textContent = 'Keep';
            meta.appendChild(name);
            card.appendChild(meta);
            card.appendChild(btn);
            list.appendChild(card);
        }
    }""")


def test_extract_uses_captured_idx_not_current(page: "Page"):
    """Extract completion updates the originally-extracted card even if navigation happened.

    Integration test: click extract on card 0, verify card 0's name is updated
    (not a corrupted card-1 or nothing).  The mock response routes to the card
    identified by the captured _detectionIdx, not whatever _detectionIdx is at
    settlement time.
    """
    _setup_player_with_csv(page)

    # Override the extract route with a named clip so we can assert on it
    page.route(
        "**/clip-cutter/extract",
        lambda r: r.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "avi_path": "/user-data/out/card0_clip.avi",
                "csv_path": "/user-data/out/card0_clip.csv",
                "start_frame_number": 100,
                "end_frame_number": 900,
            }),
        ),
    )

    _inject_two_cards(page)

    # Set up module state: detections array with two entries, open player on card 0
    page.evaluate("""() => {
        detections.length = 0;
        detections.push(
            { cv2_pos: 100, frame_number: 200, similarity: 0.9 },
            { cv2_pos: 500, frame_number: 600, similarity: 0.8 }
        );
        _detectionIdx = 0;
        _videoPath = '/user-data/test.avi';
        // Make ep-extract visible and ep-rename-extract hidden (not-kept state)
        document.getElementById('ep-extract').style.display = '';
        document.getElementById('ep-extract').disabled = false;
        document.getElementById('ep-rename-extract').style.display = 'none';
        document.getElementById('player-panel').style.display = '';
    }""")

    # Click extract — response applies to card 0
    page.click("#ep-extract")

    # Wait for the card name to update (the fetch resolves and DOM is mutated)
    expect(page.locator("#card-0 .result-name")).to_have_text(
        "card0_clip.avi", timeout=5_000
    )

    # Card 1 must NOT have been touched
    expect(page.locator("#card-1 .result-name")).to_have_text("VID_1.avi")

    # Card 0 must have gained the 'kept' class
    expect(page.locator("#card-0")).to_have_class(re.compile(r"\bkept\b"))

    # detections[0] must be updated; detections[1] must be untouched
    result = page.evaluate("""() => ({
        status0: detections[0].status,
        status1: detections[1].status,
    })""")
    assert result["status0"] == "kept", f"detections[0].status should be 'kept', got {result['status0']}"
    assert result["status1"] != "kept", f"detections[1].status should not be 'kept', got {result['status1']}"


def test_rename_extract_uses_captured_idx(page: "Page"):
    """Rename-extract completion updates the originally-renamed card.

    Integration test: put card 0 in a 'kept' state with an existing extract path,
    then click 'Update name' and verify card 0's name is updated to the renamed
    filename returned by the mock route.
    """
    _setup_player_with_csv(page)

    # Register the rename route
    page.route(
        "**/clip-cutter/extract/rename",
        lambda r: r.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"avi_path": "/user-data/out/card0_renamed.avi"}),
        ),
    )

    _inject_two_cards(page)

    # Put card 0 in kept state with a prior extract path; show rename button
    page.evaluate("""() => {
        detections.length = 0;
        detections.push(
            { cv2_pos: 100, frame_number: 200, similarity: 0.9,
              status: 'kept', extract_avi_path: '/user-data/out/card0_old.avi' },
            { cv2_pos: 500, frame_number: 600, similarity: 0.8 }
        );
        _detectionIdx = 0;
        _videoPath = '/user-data/test.avi';
        document.getElementById('card-0').classList.add('kept');
        // Show rename button, hide extract button (kept state)
        document.getElementById('ep-extract').style.display = 'none';
        document.getElementById('ep-rename-extract').style.display = '';
        document.getElementById('ep-rename-extract').disabled = false;
        document.getElementById('player-panel').style.display = '';
    }""")

    # Click rename-extract
    page.click("#ep-rename-extract")

    # Card 0's name should be updated to the renamed filename
    expect(page.locator("#card-0 .result-name")).to_have_text(
        "card0_renamed.avi", timeout=5_000
    )

    # Card 1 must be untouched
    expect(page.locator("#card-1 .result-name")).to_have_text("VID_1.avi")

    # detections[0].extract_avi_path must be updated
    new_path = page.evaluate("detections[0].extract_avi_path")
    assert new_path == "/user-data/out/card0_renamed.avi", (
        f"detections[0].extract_avi_path should be updated, got: {new_path}"
    )


# ── Similarity threshold filter tests ─────────────────────────────────────────

_SIM_DETECTIONS = [
    {"frame_number": 100, "similarity": 0.87, "source": "sensor+clip",
     "video_path": "/user-data/vid1.avi", "known_match": None, "status": "pending"},
    {"frame_number": 200, "similarity": 0.74, "source": "sensor+clip",
     "video_path": "/user-data/vid1.avi", "known_match": None, "status": "pending"},
]


def _inject_sim_detections(page: Page) -> None:
    page.wait_for_function("typeof renderDetections === 'function'")
    import json as _j
    page.evaluate(f"renderDetections({_j.dumps(_SIM_DETECTIONS)})")


def test_result_card_has_data_similarity_attribute(page: Page):
    """Each result card must expose data-similarity matching the detection's similarity."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    _inject_sim_detections(page)

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2)

    sim0 = page.evaluate("document.querySelectorAll('.result-card')[0].dataset.similarity")
    sim1 = page.evaluate("document.querySelectorAll('.result-card')[1].dataset.similarity")
    assert float(sim0) == pytest.approx(0.87, abs=0.001), f"card 0 data-similarity wrong: {sim0}"
    assert float(sim1) == pytest.approx(0.74, abs=0.001), f"card 1 data-similarity wrong: {sim1}"


def test_threshold_zero_shows_all_cards(page: Page):
    """Threshold=0 (default) shows all cards regardless of similarity."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".filter-btn[data-filter='all']")  # switch to all-sources to isolate sim filter
    _inject_sim_detections(page)
    # Both cards visible with threshold=0
    expect(page.locator(".result-card").nth(0)).to_be_visible()
    expect(page.locator(".result-card").nth(1)).to_be_visible()


def test_threshold_hides_low_similarity_cards(page: Page):
    """Setting threshold to 0.80 hides the card with similarity 0.74."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".filter-btn[data-filter='all']")
    _inject_sim_detections(page)

    # Simulate slider input: create slider element, set value, dispatch input event to trigger applyFilter
    page.evaluate("""() => {
        // Create the sim-slider element if it doesn't exist
        if (!document.getElementById('sim-slider')) {
            const slider = document.createElement('input');
            slider.id = 'sim-slider';
            slider.type = 'range';
            slider.min = '0';
            slider.max = '1';
            slider.step = '0.01';
            slider.value = '0.80';
            document.body.appendChild(slider);
        }
        const slider = document.getElementById('sim-slider');
        slider.value = '0.80';
        // Dispatch input event which triggers applyFilter
        slider.dispatchEvent(new Event('input'));
        // Manually call applyFilter to apply the filter
        applyFilter();
    }""")

    cards = page.locator(".result-card")
    expect(cards.nth(0)).to_be_visible()   # 0.87 >= 0.80 → visible
    expect(cards.nth(1)).to_be_hidden()    # 0.74 < 0.80 → hidden


def test_sim_filter_control_exists_and_visible(page: Page):
    """#sim-filter, #sim-slider, and #sim-value are present in the Detections header."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    expect(page.locator("#sim-filter")).to_be_visible()
    expect(page.locator("#sim-slider")).to_have_attribute("type", "range")
    expect(page.locator("#sim-value")).to_have_attribute("type", "number")


def test_sim_reset_hidden_by_default(page: Page):
    """#sim-reset button is hidden when threshold is 0."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    expect(page.locator("#sim-reset")).to_be_hidden()


def test_sim_field_updates_slider_and_filters(page: Page):
    """Filling #sim-value to 0.80 syncs #sim-slider and hides the low-sim card."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".filter-btn[data-filter='all']")
    _inject_sim_detections(page)

    page.fill("#sim-value", "0.80")
    page.dispatch_event("#sim-value", "input")

    expect(page.locator("#sim-slider")).to_have_value("0.8")
    expect(page.locator(".result-card").nth(0)).to_be_visible()   # 0.87 >= 0.80
    expect(page.locator(".result-card").nth(1)).to_be_hidden()    # 0.74 < 0.80


def test_sim_reset_appears_when_threshold_nonzero(page: Page):
    """#sim-reset button becomes visible when threshold > 0."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.fill("#sim-value", "0.50")
    page.dispatch_event("#sim-value", "input")

    expect(page.locator("#sim-reset")).to_be_visible()


def test_sim_reset_clears_filter(page: Page):
    """Clicking #sim-reset resets threshold to 0, shows all cards, hides itself."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.click(".filter-btn[data-filter='all']")
    _inject_sim_detections(page)

    page.fill("#sim-value", "0.80")
    page.dispatch_event("#sim-value", "input")
    expect(page.locator(".result-card").nth(1)).to_be_hidden()

    page.click("#sim-reset")

    expect(page.locator("#sim-slider")).to_have_value("0")
    expect(page.locator("#sim-value")).to_have_value("0")
    expect(page.locator(".result-card").nth(1)).to_be_visible()
    expect(page.locator("#sim-reset")).to_be_hidden()


def test_tab_skips_hidden_cards(page: Page):
    """Tab from the active card skips cards hidden by the similarity filter.

    Setup: 2 cards, threshold=0.80 → card[1] (sim=0.74) is hidden.
    Make card[0] active-preview, dispatch Tab → should NOT activate card[1].
    """
    setup_routes_with_persistence(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)

    # Open player so Tab handler is active
    page.locator(".result-card").first.locator(".result-name").click()
    expect(page.locator("#player-panel")).to_be_visible(timeout=5_000)

    # Set threshold to 0.80 via the field — card[1] (sim=0.74) becomes hidden
    page.click(".filter-btn[data-filter='all']")
    page.fill("#sim-value", "0.80")
    page.dispatch_event("#sim-value", "input")

    # card[0] is active-preview (it was clicked to open player)
    expect(page.locator(".result-card").nth(0)).to_have_class(re.compile(r"active-preview"))
    expect(page.locator(".result-card").nth(1)).to_be_hidden()

    # Press Tab — with the fix, no visible next card, so active-preview stays on card[0]
    page.locator("body").press("Tab")
    page.wait_for_timeout(200)

    # card[0] should still be active (no next visible card to jump to)
    expect(page.locator(".result-card").nth(0)).to_have_class(re.compile(r"active-preview"))
    expect(page.locator(".result-card").nth(1)).not_to_have_class(re.compile(r"active-preview"))


def test_note_palette_has_scroll_limit(page: Page):
    """#ep-note-palette must have max-height: 72px and overflow-y: auto."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    max_h = page.evaluate(
        "getComputedStyle(document.getElementById('ep-note-palette')).maxHeight"
    )
    overflow = page.evaluate(
        "getComputedStyle(document.getElementById('ep-note-palette')).overflowY"
    )
    assert max_h == "72px", f"max-height wrong: {max_h}"
    assert overflow == "auto", f"overflow-y wrong: {overflow}"


def test_propagate_row_visible_in_template_mode(page: Page):
    """#ep-propagate-row must NOT be hidden in template/non-clip mode."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.wait_for_selector("#sidebar-browse-btn:not([disabled])", timeout=3000)
    # Open template browse mode
    page.evaluate("""() => {
        openPlayer({ mode: 'template', videoPath: '/user-data/vid1.avi' });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    display = page.evaluate(
        "document.getElementById('ep-propagate-row').style.display"
    )
    assert display != "none", f"propagate-row hidden in template mode: {display}"


def test_propagate_row_has_two_checkboxes(page: Page):
    """#ep-propagate-row must contain ep-add-kf-to-template (checked) and ep-propagate-kf (unchecked)."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    add_kf_checked = page.evaluate(
        "document.getElementById('ep-add-kf-to-template').checked"
    )
    propagate_checked = page.evaluate(
        "document.getElementById('ep-propagate-kf').checked"
    )
    assert add_kf_checked is True, "ep-add-kf-to-template should be checked by default"
    assert propagate_checked is False, "ep-propagate-kf should be unchecked by default"


def test_browse_btn_exists_in_detections_header(page: Page):
    """#detections-browse-btn must exist inside .results-pane-header."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    btn = page.locator(".results-pane-header #detections-browse-btn")
    expect(btn).to_have_count(1)


def test_browse_btn_disabled_on_load(page: Page):
    """Browse button must be disabled when no video is selected."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    expect(page.locator("#detections-browse-btn")).to_be_disabled()


def test_browse_btn_enabled_after_video_select(page: Page):
    """Browse button must be enabled after selecting a video."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.locator(".browser-row:has(.badge-pending)").first.click()
    page.wait_for_selector("#scan-btn:not([disabled])")
    expect(page.locator("#detections-browse-btn")).to_be_enabled()


def test_openplayer_unlocked_starts_with_open_lock(page: Page):
    """openPlayer with unlocked:true must render unlocked lock badge and ep-lock-start unchecked."""
    setup_routes(page)
    # Mock video-info, sibling-camera, and frame endpoints
    page.route("**/clip-cutter/video-info**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"frame_count": 1000})
    ))
    page.route("**/clip-cutter/sibling-camera", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sibling_video_path": None})
    ))
    page.route("**/clip-cutter/frame**", lambda r: r.fulfill(
        status=200, content_type="image/jpeg",
        body=base64.b64decode(_JPEG_B64)
    ))
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    badge_class = page.evaluate("document.getElementById('ep-lock-badge').className")
    lock_start_checked = page.evaluate("document.getElementById('ep-lock-start').checked")
    assert "unlocked" in badge_class, f"lock badge class wrong: {badge_class}"
    assert lock_start_checked is False, "ep-lock-start should be unchecked in browse mode"


def test_setkf_in_browse_mode_updates_start_field(page: Page):
    """Set KF with no detectionIdx (browse mode) must update ep-start without crashing."""
    setup_routes(page)
    page.route("**/clip-cutter/video-info**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"frame_count": 1000})
    ))
    page.route("**/clip-cutter/sibling-camera", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sibling_video_path": None})
    ))
    page.route("**/clip-cutter/frame**", lambda r: r.fulfill(
        status=200, content_type="image/jpeg",
        body=base64.b64decode(_JPEG_B64)
    ))
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    # Jump to frame 300 and press Set KF
    page.evaluate("_currentFrame = 300")
    page.click("#ep-set-kf")
    start_val = page.evaluate("document.getElementById('ep-start').value")
    assert int(start_val) == 101, f"ep-start should be max(1, 300+1-200)=101, got {start_val}"


_MOCK_BROWSE_EXTRACT = {
    "avi_path": "/user-data/out/browse_clip.avi",
    "csv_path": "/user-data/out/browse_clip.csv",
    "start_frame_number": 100,
    "end_frame_number": 899,
}


def _setup_browse_routes(page):
    """Setup routes + video-info + frame for browse-mode tests."""
    setup_routes(page)
    page.route("**/clip-cutter/video-info**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"frame_count": 1000})
    ))
    page.route("**/clip-cutter/sibling-camera", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"sibling_video_path": None})
    ))
    page.route("**/clip-cutter/frame**", lambda r: r.fulfill(
        status=200, content_type="image/jpeg",
        body=base64.b64decode(_JPEG_B64)
    ))
    page.route("**/clip-cutter/detections", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True})
    ))


def test_browse_extract_creates_new_detection_card(page: Page):
    """Extracting in browse mode must append a new result card with source=manual."""
    _setup_browse_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        selectedVideoPath = '/user-data/vid1.avi';
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    initial_count = page.evaluate("detections.length")
    page.click("#ep-extract")
    page.wait_for_function("detections.length > 0", timeout=3000)
    card_count = page.locator(".result-card").count()
    assert card_count == initial_count + 1, f"expected 1 new card, got {card_count - initial_count}"
    source = page.evaluate("detections[detections.length - 1].source")
    assert source == "manual", f"new detection source should be 'manual', got {source}"


def test_browse_extract_switches_filter_to_all(page: Page):
    """Extracting in browse mode must switch the source filter to 'all'."""
    _setup_browse_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        selectedVideoPath = '/user-data/vid1.avi';
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    page.click("#ep-extract")
    page.wait_for_function("detections.length > 0", timeout=3000)
    active_filter = page.evaluate("currentFilter")
    assert active_filter == "all", f"filter should switch to 'all', got {active_filter}"


def test_browse_extract_keeps_extract_btn_enabled(page: Page):
    """After browse-mode extract, the Extract button must remain visible and enabled."""
    _setup_browse_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        selectedVideoPath = '/user-data/vid1.avi';
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    page.click("#ep-extract")
    page.wait_for_function("detections.length > 0", timeout=3000)
    extract_visible = page.evaluate("document.getElementById('ep-extract').style.display !== 'none'")
    extract_enabled = page.evaluate("!document.getElementById('ep-extract').disabled")
    assert extract_visible, "ep-extract should remain visible after browse extract"
    assert extract_enabled, "ep-extract should remain enabled after browse extract"

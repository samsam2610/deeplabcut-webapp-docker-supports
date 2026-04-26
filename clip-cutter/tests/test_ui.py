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

_MOCK_VIDEOS = [
    {"name": "MAP2_20250515_103618_0.avi", "path": "/user-data/vid1.avi", "done": False},
    {"name": "MAP2_20250516_110432_0.avi", "path": "/user-data/vid2.avi", "done": True},
    {"name": "MAP2_20250517_112331_0.avi", "path": "/user-data/vid3.avi", "done": False},
]

_MOCK_DETECTIONS = [
    {
        "cv2_pos": 20967,
        "frame_number": 20968,
        "similarity": 0.8734,
        "known_match": "MAP2_0_20768_21567_success",
    },
    {
        "cv2_pos": 51399,
        "frame_number": 51400,
        "similarity": 0.7412,
        "known_match": None,
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
        _json(route, {"count": len(state["frames"]), "frames": state["frames"]})

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

    def on_videos(route: Route):
        _json(route, {"videos": _MOCK_VIDEOS})

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
    page.route("**/clip-cutter/template", on_template_get)
    page.route("**/clip-cutter/videos", on_videos)
    page.route("**/clip-cutter/scan/stream*", on_scan_stream)
    page.route("**/clip-cutter/scan", on_scan_start)
    page.route("**/clip-cutter/extract", on_extract)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_page_loads_correct_structure(page: Page):
    """Initial page renders title, sidebar, video list, disabled scan button."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    expect(page).to_have_title("Clip Cutter")
    expect(page.locator("h1")).to_have_text("Clip Cutter")
    expect(page.locator(".sidebar-title")).to_have_text("Template Bank")
    expect(page.locator("#template-footer")).to_have_text("0 frames loaded")
    expect(page.locator("#scan-btn")).to_be_disabled()
    expect(page.locator("#status-msg")).to_have_text("Ready")


def test_video_list_populates_on_load(page: Page):
    """Video list renders all videos with correct badges."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    rows = page.locator(".video-row")
    expect(rows).to_have_count(3)

    first = rows.nth(0)
    expect(first.locator(".video-name")).to_contain_text("MAP2_20250515")
    expect(first.locator(".badge-pending")).to_be_visible()

    second = rows.nth(1)
    expect(second.locator(".badge-done")).to_be_visible()
    expect(second).to_have_class(re.compile(r"done"))


def test_done_video_row_cannot_be_selected(page: Page):
    """Clicking a done video row does not enable the scan button."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".video-row.done").click()
    expect(page.locator("#scan-btn")).to_be_disabled()


def test_selecting_video_enables_scan_button(page: Page):
    """Clicking a ready video row selects it and enables the scan button."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    first_ready = page.locator(".video-row:not(.done)").first
    first_ready.click()

    expect(first_ready).to_have_class(re.compile(r"selected"))
    expect(page.locator("#scan-btn")).to_be_enabled()


def test_only_one_video_selected_at_a_time(page: Page):
    """Selecting a second video deselects the first."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    ready = page.locator(".video-row:not(.done)")
    ready.nth(0).click()
    ready.nth(1).click()

    expect(page.locator(".video-row.selected")).to_have_count(1)
    expect(page.locator("#scan-btn")).to_be_enabled()


def test_template_init_flow(page: Page):
    """
    Clicking Init POSTs to /template/init, polls /status, shows progress
    messages, and fills the sidebar with thumbnails when done.
    """
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")

    expect(page.locator("#template-footer")).to_have_text("0 frames loaded")

    page.locator("button", has_text="Init").click()
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

    page.locator(".video-row:not(.done)").first.click()
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

    page.locator(".video-row:not(.done)").first.click()
    page.locator("#scan-btn").click()

    expect(page.locator("#results-count")).to_have_text("2 found", timeout=8_000)

    for phase in ("coarse", "peak_detection", "fine"):
        step = page.locator(f'.pipeline-step[data-phase="{phase}"]')
        expect(step).to_have_class(re.compile(r"\bdone\b"))


def test_keep_detection_grays_out_card(page: Page):
    """Clicking Keep calls /extract and marks the card as kept."""
    setup_routes(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".video-row:not(.done)").first.click()
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

    page.locator(".video-row:not(.done)").first.click()
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

    expect(page.locator("#template-footer")).to_have_text("5 frames loaded")

    page.locator(".video-row:not(.done)").first.click()
    page.locator("#scan-btn").click()

    cards = page.locator(".result-card")
    expect(cards).to_have_count(2, timeout=8_000)

    cards.nth(0).locator("button", has_text="Add to template").click()

    expect(page.locator("#template-footer")).to_have_text("6 frames loaded")


def test_rescan_clears_previous_results(page: Page):
    """Starting a second scan replaces the previous detection cards."""
    setup_routes(page, template_frames=_MOCK_FRAMES)
    page.goto(f"{BASE_URL}/clip-cutter/")

    page.locator(".video-row:not(.done)").first.click()
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
        },
        {
            "cv2_pos": 51399,
            "frame_number": 51400,
            "similarity": 0.7412,
            "known_match": None,
            "status": "rejected",
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

    page.locator(".video-row:not(.done)").first.click()

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
    page.locator(".video-row:not(.done)").first.click()

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
    page.locator(".video-row:not(.done)").first.click()
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
    page.locator(".video-row:not(.done)").first.click()
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
    page.locator(".video-row:not(.done)").first.click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=5_000)

    page.locator("#scan-btn").click()
    expect(page.locator(".result-card")).to_have_count(2, timeout=8_000)
    # After rescan neither card should be kept/rejected
    for i in range(2):
        card = page.locator(".result-card").nth(i)
        expect(card).not_to_have_class(re.compile(r"\bkept\b"))
        expect(card).not_to_have_class(re.compile(r"\brejected\b"))

"""Live read-only checks for the inline-3D "Analyze for tag" controls.

Reuses the reorg suite's card-open fixture pattern. READ-ONLY: asserts the Lock-tag
checkbox + Analyze-for-tag button are present and disabled by default (no active
note tag, no sibling in this fixture). NEVER triggers analysis. Richer gating +
chip-freeze are covered by unit/static tests (see design spec 2026-07-16).
"""
import pytest
from playwright.sync_api import Page, expect

SESSION = "OM-2_20260424"
PROJECT_PATH_IN_CONTAINER = (
    "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07"
)
BROWSE_VIDEO = f"{PROJECT_PATH_IN_CONTAINER}/videos/{SESSION}.mp4"


@pytest.fixture(autouse=True)
def _open_inline_card(page: Page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-inline-analysis-3d").click()
    page.locator("#inline-analysis-3d-card").wait_for(state="visible")
    page.locator("#ia3d-tab-browse").click()
    page.locator("#ia3d-browse-breadcrumb").fill(BROWSE_VIDEO)
    page.locator("#ia3d-browse-breadcrumb").press("Enter")
    page.locator("#ia3d-player-section").wait_for(state="visible", timeout=15000)
    page.wait_for_function(
        "() => window.__iaViewer && document.querySelector('#ia3d-viewer-mount .vv-tile')"
    )


def test_tag_controls_present(page: Page):
    expect(page.locator("#ia3d-tag-lock")).to_be_visible()
    expect(page.locator("#ia3d-btn-analyze-tag")).to_be_visible()


def test_tag_lock_disabled_without_active_note(page: Page):
    # No companion-CSV note chips in this fixture → zero active note tags → lock off.
    expect(page.locator("#ia3d-tag-lock")).to_be_disabled()


def test_analyze_for_tag_disabled_by_default(page: Page):
    expect(page.locator("#ia3d-btn-analyze-tag")).to_be_disabled()

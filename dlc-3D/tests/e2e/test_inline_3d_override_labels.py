"""Live read-only check for the "override existing labels" checkbox on the
Analyze-for-tag batch: present and unchecked by default. NEVER triggers analysis.
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


def test_override_checkbox_present(page: Page):
    expect(page.locator("#ia3d-override-labels")).to_be_visible()


def test_override_checkbox_unchecked_by_default(page: Page):
    assert page.locator("#ia3d-override-labels").is_checked() is False

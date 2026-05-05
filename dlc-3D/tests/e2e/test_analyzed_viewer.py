"""E2E tests for the dlc-3D analyzed frame/video viewer."""
import pytest

OPEN_BTN_TEXT = "View Analyzed"  # nav button label in base.html


def _open_card(page):
    page.click(f"button:has-text('{OPEN_BTN_TEXT}')")
    page.wait_for_selector("#view-analyzed-3d-card:not(.hidden)", timeout=5000)


def test_card_opens_and_lists_project_content(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    # Project Content tab is the default; list should populate.
    page.wait_for_selector("#va3d-content-list a, #va3d-content-list .explorer-empty",
                           timeout=10000)
    # Must NOT be the "Loading…" placeholder anymore.
    initial_text = page.text_content("#va3d-content-list")
    assert "Loading…" not in initial_text


def test_close_button_hides_card(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    page.click("#btn-close-view-analyzed-3d")
    page.wait_for_selector("#view-analyzed-3d-card.hidden", state="attached", timeout=2000)

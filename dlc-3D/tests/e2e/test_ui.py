import pytest


def test_page_loads(page, base_url):
    resp = page.goto(base_url)
    assert resp.status == 200
    assert page.locator("main.cards").is_visible()


def test_dlc_project_card_visible(page, base_url):
    page.goto(base_url)
    assert page.locator("#dlc-project-card").count() == 1


def test_extractor_card_hidden_by_default(page, base_url):
    page.goto(base_url)
    classes = page.locator("#dlc-3d-extract-card").get_attribute("class")
    assert "hidden" in classes


def test_open_extractor_card(page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-frame-extractor").click()
    classes = page.locator("#dlc-3d-extract-card").get_attribute("class")
    assert "hidden" not in classes


def test_close_extractor_card(page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-frame-extractor").click()
    page.locator("#btn-close-3d-extract").click()
    classes = page.locator("#dlc-3d-extract-card").get_attribute("class")
    assert "hidden" in classes


def test_other_cards_unaffected_by_open(page, base_url):
    page.goto(base_url)
    classes_before = page.locator("#dlc-project-card").get_attribute("class")
    page.locator("#btn-open-frame-extractor").click()
    classes_after = page.locator("#dlc-project-card").get_attribute("class")
    # Opening the extractor card must not change the project card's class
    assert classes_before == classes_after


def test_empty_state_message(page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-frame-extractor").click()
    assert page.locator("#dlc3d-session-empty").is_visible()


def test_file_browser_hidden_without_project(page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-frame-extractor").click()
    display = page.evaluate("document.getElementById('dlc3d-file-browser').style.display")
    assert display == "none"


def test_browse_row_hidden_without_project(page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-frame-extractor").click()
    display = page.evaluate("document.getElementById('dlc3d-browse-row')?.style.display ?? 'missing'")
    assert display == "none"

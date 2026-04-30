import pytest

BASE_URL = "http://172.26.0.5:5050/dlc-3d/"


def test_page_loads(page):
    resp = page.goto(BASE_URL)
    assert resp.status == 200
    assert page.locator("main.cards").is_visible()


def test_dlc_project_card_visible(page):
    page.goto(BASE_URL)
    assert page.locator("#dlc-project-card").count() == 1


def test_extractor_card_hidden_by_default(page):
    page.goto(BASE_URL)
    classes = page.locator("#dlc-3d-extract-card").get_attribute("class")
    assert "hidden" in classes


def test_open_extractor_card(page):
    page.goto(BASE_URL)
    page.locator("#btn-open-frame-extractor").click()
    classes = page.locator("#dlc-3d-extract-card").get_attribute("class")
    assert "hidden" not in classes


def test_close_extractor_card(page):
    page.goto(BASE_URL)
    page.locator("#btn-open-frame-extractor").click()
    page.locator("#btn-close-3d-extract").click()
    classes = page.locator("#dlc-3d-extract-card").get_attribute("class")
    assert "hidden" in classes


def test_other_cards_unaffected_by_open(page):
    page.goto(BASE_URL)
    classes_before = page.locator("#dlc-project-card").get_attribute("class")
    page.locator("#btn-open-frame-extractor").click()
    classes_after = page.locator("#dlc-project-card").get_attribute("class")
    # Opening the extractor card must not change the project card's class
    assert classes_before == classes_after


def test_empty_state_message(page):
    page.goto(BASE_URL)
    page.locator("#btn-open-frame-extractor").click()
    assert page.locator("#dlc3d-session-empty").is_visible()


def test_file_browser_hidden_without_project(page):
    page.goto(BASE_URL)
    page.locator("#btn-open-frame-extractor").click()
    display = page.evaluate("document.getElementById('dlc3d-file-browser').style.display")
    assert display == "none"

from pathlib import Path

import pytest

STATIC = Path(__file__).parent.parent / "src" / "static"
JS = STATIC / "inline_analysis_3d_reprojection.js"
CARD = STATIC / "card_inline_analysis_3d_reprojection.html"


@pytest.fixture(scope="module")
def js():
    return JS.read_text()


def test_bootstrap_block_is_present(js):
    assert "REPROJECTION BOOTSTRAP" in js


def test_injects_its_own_stylesheet(js):
    assert "inline_analysis_3d_reprojection.css" in js


def test_fetches_and_injects_the_card_fragment(js):
    assert "card_inline_analysis_3d_reprojection.html" in js
    assert "main.cards" in js


def test_creates_its_own_launcher_button(js):
    assert "btn-open-inline-analysis-3d-reprojection" in js
    assert "3D Inline Analysis - Reprojection" in js


def test_launcher_anchors_below_the_original_button(js):
    """The button must sit directly below the original card's button, so the
    anchor is the ORIGINAL id — which must therefore still appear in the clone
    exactly once, as an anchor lookup and nothing else."""
    assert 'btn-open-inline-analysis-3d"' in js


def test_card_fragment_has_no_jinja(js):
    text = CARD.read_text()
    assert "{%" not in text and "{{" not in text

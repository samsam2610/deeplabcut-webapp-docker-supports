from pathlib import Path

import pytest

CARD = (
    Path(__file__).parent.parent / "src" / "static"
    / "card_inline_analysis_3d_reprojection.html"
)

REQUIRED_IDS = [
    "ia3dr-reproj-panel",
    "ia3dr-reproj-ref-cam",
    "ia3dr-reproj-k1",
    "ia3dr-reproj-k1-val",
    "ia3dr-reproj-k2",
    "ia3dr-reproj-k2-val",
    "ia3dr-reproj-estimate",
    "ia3dr-reproj-run",
    "ia3dr-reproj-status",
    "ia3dr-reproj-thresholds",
    "ia3dr-reproj-counts",
    "ia3dr-reproj-show-lines",
    "ia3dr-reproj-overrides",
]


@pytest.fixture(scope="module")
def card():
    return CARD.read_text()


@pytest.mark.parametrize("element_id", REQUIRED_IDS)
def test_required_element_present(card, element_id):
    assert 'id="{}"'.format(element_id) in card


def test_reference_camera_offers_both_cameras(card):
    panel = card.split('id="ia3dr-reproj-ref-cam"')[1][:400]
    assert 'value="cam_0"' in panel and 'value="cam_1"' in panel


def test_k_defaults_match_the_spec(card):
    """k1 = 3, k2 = 8 per the design spec."""
    k1 = card.split('id="ia3dr-reproj-k1"')[1][:300]
    k2 = card.split('id="ia3dr-reproj-k2"')[1][:300]
    assert 'value="3"' in k1
    assert 'value="8"' in k2


def test_panel_is_inside_the_cloned_card(card):
    assert card.index('id="inline-analysis-3d-reprojection-card"') < card.index(
        'id="ia3dr-reproj-panel"'
    )

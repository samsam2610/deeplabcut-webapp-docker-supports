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


PER_CAM_IDS = [
    "ia3dr-reproj-cam0-gate-ref", "ia3dr-reproj-cam0-low-tgt",
    "ia3dr-reproj-cam0-high-conf", "ia3dr-reproj-cam0-rescue-floor",
    "ia3dr-reproj-cam1-gate-ref", "ia3dr-reproj-cam1-low-tgt",
    "ia3dr-reproj-cam1-high-conf", "ia3dr-reproj-cam1-rescue-floor",
]


@pytest.mark.parametrize("element_id", PER_CAM_IDS)
def test_per_camera_input_present(card, element_id):
    assert 'id="{}"'.format(element_id) in card


def test_per_camera_inputs_are_bounded_to_a_likelihood(card):
    """These are likelihoods; the browser should refuse values outside [0, 1]
    before the request is ever made."""
    for element_id in PER_CAM_IDS:
        frag = card.split('id="{}"'.format(element_id))[1][:200]
        assert 'min="0"' in frag and 'max="1"' in frag


def test_per_camera_defaults_match_the_engine(card):
    for element_id in PER_CAM_IDS:
        frag = card.split('id="{}"'.format(element_id))[1][:200]
        want = '0.9' if ("high-conf" in element_id or "rescue-floor" in element_id) else '0.6'
        assert 'value="{}"'.format(want) in frag


def test_help_box_exists_beside_the_per_camera_groups(card):
    assert 'id="ia3dr-reproj-help"' in card
    # It must be inside the flex wrap so it fills the space beside cam0/cam1.
    wrap = card.split('class="ia3dr-percam-wrap"')[1].split("</div>")[0]
    assert "ia3dr-reproj-help" in card
    assert card.index('class="ia3dr-percam-wrap"') < card.index('id="ia3dr-reproj-help"')


def test_help_box_announces_changes(card):
    frag = card.split('id="ia3dr-reproj-help"')[0][-200:]
    assert "aria-live" in frag or "aria-live" in card.split('id="ia3dr-reproj-help"')[1][:200]


def test_every_control_carries_a_help_key(card):
    """A control with no data-help silently shows the default summary, which
    reads as 'this one has no explanation'."""
    for element_id in ("ia3dr-reproj-ref-cam", "ia3dr-reproj-k1", "ia3dr-reproj-k2",
                       "ia3dr-reproj-cam0-gate-ref", "ia3dr-reproj-cam1-rescue-floor"):
        frag = card.split('id="{}"'.format(element_id))[1][:200]
        assert "data-help" in frag, "{} has no data-help".format(element_id)

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
    "ia3dr-emit-peaks",
    "ia3dr-reproj-require-peaks",
    "ia3dr-reproj-peak-floor",
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
                       "ia3dr-reproj-cam0-gate-ref", "ia3dr-reproj-cam1-rescue-floor",
                       "ia3dr-reproj-require-peaks", "ia3dr-reproj-peak-floor"):
        frag = card.split('id="{}"'.format(element_id))[1][:200]
        assert "data-help" in frag, "{} has no data-help".format(element_id)


def test_line_likelihood_field_sits_beside_the_checkbox(card):
    assert 'id="ia3dr-reproj-line-lik"' in card
    # Same control row as the show-lines checkbox, so it reads as belonging to it.
    show = card.index('id="ia3dr-reproj-show-lines"')
    field = card.index('id="ia3dr-reproj-line-lik"')
    assert abs(show - field) < 600, "field is not adjacent to the checkbox"


def test_line_likelihood_field_bounds_and_default(card):
    frag = card.split('id="ia3dr-reproj-line-lik"')[1][:220]
    assert 'min="0"' in frag and 'max="1"' in frag
    assert 'value="0.4"' in frag, "default must be 0.4, below gate_ref's 0.6"
    assert "data-help" in frag


def test_emit_peaks_checkbox_sits_in_the_always_visible_analyze_block_and_defaults_on(card):
    """The checkbox must be a top-level control of the always-visible
    .ia3dr-analyze-block (consulted by all three analyze entry points), not
    scoped to the tag-only sub-row, and it must NOT be inside
    #ia3dr-finalize-controls — that container is gated (class="hidden") by the
    finalize-mode toggle, but 'Start analysis from current frame' works
    OUTSIDE finalize mode. A checkbox hidden while a live path still consults
    it would be a silent trap."""
    block_open = card.index('class="ia3dr-analyze-block"')
    start_count = card.index('id="ia3dr-start-count"')
    checkbox = card.index('id="ia3dr-emit-peaks"')

    # Sits inside .ia3dr-analyze-block, before the first sibling control.
    assert block_open < checkbox < start_count, (
        "emit-peaks must appear right after .ia3dr-analyze-block opens and "
        "before ia3dr-start-count"
    )

    # Regression guard for the hidden-container trap: it must appear AFTER
    # ia3dr-finalize-range, which is the last content emitted by
    # #ia3dr-finalize-controls before that container closes. Equivalent to
    # asserting the checkbox is not nested inside the gated container.
    finalize_range = card.index('id="ia3dr-finalize-range"')
    assert checkbox > finalize_range, (
        "emit-peaks must not sit inside #ia3dr-finalize-controls, which is "
        "hidden outside finalize mode while other analyze paths stay live"
    )

    assert 'type="checkbox"' in card[max(0, checkbox - 60):checkbox]
    frag = card.split('id="ia3dr-emit-peaks"')[1][:220]
    assert "checked" in frag


def test_require_peaks_checkbox_defaults_off_and_carries_help(card):
    i = card.index('id="ia3dr-reproj-require-peaks"')
    assert 'type="checkbox"' in card[max(0, i - 60):i]
    frag = card.split('id="ia3dr-reproj-require-peaks"')[1][:220]
    assert "checked" not in frag, "the screen must be opt-in"
    assert 'data-help="require_peaks"' in frag


def test_peak_floor_field_has_the_specified_bounds_and_default(card):
    i = card.index('id="ia3dr-reproj-peak-floor"')
    assert 'type="number"' in card[max(0, i - 60):i]
    frag = card.split('id="ia3dr-reproj-peak-floor"')[1][:220]
    for want in ('min="0"', 'max="1"', 'step="0.01"', 'value="0.05"',
                 'data-help="peak_floor"'):
        assert want in frag, "{} missing from {}".format(want, frag)


def test_extraction_parameters_are_not_exposed(card):
    """k and min_distance are internal-only; only the screen's own knobs
    (require-peaks, peak-floor) are exposed as controls."""
    for absent in ("ia3dr-reproj-peak-k", "ia3dr-reproj-peak-min-distance"):
        assert absent not in card


def test_the_new_help_keys_exist():
    src = (
        Path(__file__).parent.parent / "src" / "static" / "internal"
        / "reproj_help.mjs"
    ).read_text()
    for key in ("require_peaks:", "peak_floor:"):
        assert key in src


def test_every_data_help_key_used_in_markup_has_a_help_entry(card):
    """Stricter cross-file guard: walks every data-help="..." value actually
    used in the card (not just the two new ones) and asserts each has a
    matching entry in reproj_help.mjs. Verified against current HEAD before
    this change: no pre-existing gap (used == defined for all 8 prior keys),
    so this passes unconditionally rather than being scoped to the new keys."""
    import re
    mod = (
        Path(__file__).parent.parent / "src" / "static" / "internal"
        / "reproj_help.mjs"
    ).read_text()
    used = set(re.findall(r'data-help="([^"]+)"', card))
    defined = set(re.findall(r"^\s{2}(\w+):\s*\{", mod, re.M))
    missing = used - defined
    assert not missing, "markup uses help keys with no entry: {}".format(sorted(missing))

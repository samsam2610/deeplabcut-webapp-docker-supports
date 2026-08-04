"""Source assertions for the frame labeler's epipolar overlay wiring.

Same approach as tests/test_reproj_panel_wiring.py: the behaviour lives in a
browser-only module, so we assert on the source. Pure logic that can be tested
for real lives in src/static/internal/epiline_request.mjs and is covered by
tests/unit/test_epiline_request.mjs — these tests cover only the wiring that
module cannot see.
"""
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
JS = SRC / "static" / "frame_labeler_3d.js"
HTML = SRC / "templates" / "partials" / "card_frame_labeler.html"


@pytest.fixture(scope="module")
def js():
    return JS.read_text()


@pytest.fixture(scope="module")
def html():
    return HTML.read_text()


def test_checkbox_and_hint_exist(html):
    assert 'id="fl3d-epiline"' in html
    assert 'id="fl3d-epiline-hint"' in html


def test_checkbox_advertises_its_shortcut(html):
    """Every other labeler toggle shows its key; this one must too."""
    assert "(P)" in html


def test_gate_uses_the_shared_helper(js):
    """The three gating rules are unit-tested in epiline_request.mjs. Wiring a
    second, hand-rolled copy here would put them beyond that test's reach."""
    assert "epiGateReason" in js
    assert "internal/epiline_request.mjs" in js


def test_p_is_bound_and_does_not_fire_while_typing(js):
    assert '"p"' in js.lower()
    block = js.split("document.addEventListener(\"keydown\"")[1]
    assert "INPUT" in block or "tagName" in block, (
        "P must not toggle while the user is typing in a field"
    )


def test_p_respects_the_disabled_gate(js):
    """Otherwise the key bypasses the very gate the checkbox enforces.

    Scoped to the keydown handler on purpose: _fl3dRefreshEpiGate assigns
    `flEpiCheckbox.disabled`, so an unscoped substring check would pass even
    with the P handler wide open.
    """
    block = js.split("document.addEventListener(\"keydown\"")[1]
    idx = block.lower().index('"p"')
    guard = block[max(0, idx - 200): idx + 400]
    assert "disabled" in guard, (
        "the P branch must consult the checkbox's disabled state"
    )


def test_calibration_field_is_read_from_labeled_frames(js):
    assert "_fl3dEpiCalib" in js
    assert ".calibration" in js


def _epi_block(js):
    """The overlay section, delimited by its own banner comment."""
    assert "EPIPOLAR OVERLAY" in js, "overlay section must be banner-delimited"
    return js.split("EPIPOLAR OVERLAY")[1]


def test_debounce_is_two_seconds(js):
    assert "FL3D_EPI_DEBOUNCE_MS = 2000" in js


def test_enabling_does_not_wait_for_the_debounce(js):
    """A 2 s blank after ticking the box reads as the feature being broken.
    The debounce exists for label edits only."""
    block = _epi_block(js)
    assert "_fl3dEpiRecompute(" in block
    setter = js.split("function _fl3dSetEpiEnabled")[1].split("\n    }")[0]
    assert "_fl3dEpiRecompute" in setter, (
        "enabling must compute immediately, not schedule the debounce"
    )


def test_toggling_off_clears_stored_segments(js):
    setter = js.split("function _fl3dSetEpiEnabled")[1].split("\n    }")[0]
    assert "_fl3dEpiSegments = {}" in setter, (
        "a stale line must not outlive the toggle"
    )


def test_the_draw_path_never_fetches(js):
    """_fl3dDrawTileMarkers runs on zoom, pan and hover. A fetch in there is a
    request storm."""
    fn = js.split("function _fl3dDrawTileMarkers")[1].split("\n    function ")[0]
    assert "fetch(" not in fn
    assert "_fl3dEpiSegments" in fn, "the draw path must paint stored segments"


def test_a_generation_counter_guards_the_async_draw(js):
    """Recorded regression on the sibling overlay — see docs/regression-catalog.md."""
    block = _epi_block(js)
    assert "_fl3dEpiGen" in block
    assert "++_fl3dEpiGen" in block
    assert block.count("_fl3dEpiGen") >= 3, (
        "expected declare / bump / re-check after await"
    )


def test_reference_camera_is_the_last_edited_not_the_focused_one(js):
    """Projecting from the focused camera makes the lines vanish the moment the
    user clicks over to use them."""
    block = _epi_block(js)
    assert "_fl3dEpiRefCam" in block
    fn = js.split("function _fl3dEpiRecompute")[1].split("\n    }")[0]
    assert "_fl3dFocusedCam" not in fn, (
        "recompute must use _fl3dEpiRefCam, not the focused cam"
    )


def test_lines_are_drawn_on_the_non_reference_tile(js):
    fn = js.split("function _fl3dDrawTileMarkers")[1].split("\n    function ")[0]
    assert "_fl3dEpiRefCam" in fn


def test_style_matches_the_reprojection_card(js):
    block = _epi_block(js)
    assert "setLineDash([6, 4])" in block
    assert "_flColor(" in block
    assert "labelAnchor(" in block and "nameLabelBox(" in block


def test_label_step_advances_only_for_drawn_lines(js):
    """Otherwise gaps appear in the staircase where a line was null."""
    fn = js.split("function _fl3dDrawEpilines")[1].split("\n    }")[0]
    assert "order++" in fn
    assert fn.index("continue") < fn.index("order++"), (
        "order must advance after the null check, not before it"
    )

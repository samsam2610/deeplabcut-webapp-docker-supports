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

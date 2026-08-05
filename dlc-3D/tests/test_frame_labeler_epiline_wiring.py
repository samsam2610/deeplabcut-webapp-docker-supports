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
    setter = js.split("function _fl3dSetEpiEnabled")[1].split("\n    }")[0]
    assert "_fl3dEpiRecompute()" in setter, (
        "enabling must call recompute directly"
    )
    assert "setTimeout" not in setter and "FL3D_EPI_DEBOUNCE_MS" not in setter, (
        "enabling must compute immediately, not schedule the debounce"
    )


def test_toggling_off_clears_stored_segments(js):
    setter = js.split("function _fl3dSetEpiEnabled")[1].split("\n    }")[0]
    assert "} else {" in setter, "expected an explicit disable branch"
    disable_branch = setter.split("} else {")[1]
    assert "_fl3dEpiSegments = {}" in disable_branch, (
        "a stale line must not outlive the toggle"
    )


def test_the_draw_path_never_fetches(js):
    """_fl3dDrawTileMarkers runs on zoom, pan and hover. A fetch anywhere in
    that path is a request storm.

    _fl3dDrawTileMarkers calls _fl3dDrawEpilines(tile) on every repaint, so
    the draw path is the UNION of both function bodies, not just the caller's.
    A fetch injected inside _fl3dDrawEpilines alone must fail this test too —
    checking only _fl3dDrawTileMarkers's own body would miss it.
    """
    tile_markers_fn = js.split("function _fl3dDrawTileMarkers")[1].split("\n    function ")[0]
    epilines_fn      = js.split("function _fl3dDrawEpilines")[1].split("\n    function ")[0]
    assert "fetch(" not in tile_markers_fn
    assert "fetch(" not in epilines_fn
    assert "_fl3dDrawEpilines(tile)" in tile_markers_fn, (
        "the draw path must paint stored segments"
    )


def test_a_generation_counter_guards_the_async_draw(js):
    """Recorded regression on the sibling overlay — see docs/regression-catalog.md.

    Positional, not just a count: every `await` must be immediately followed
    (before the next statement) by a `_fl3dEpiGen` recheck, so a response
    that lands after the user moved on is discarded before its data is used.
    """
    block = _epi_block(js)
    assert "_fl3dEpiGen" in block
    assert "++_fl3dEpiGen" in block
    fn = js.split("function _fl3dEpiRecompute")[1].split("\n    }")[0]
    awaits = fn.split("await")[1:]
    assert len(awaits) >= 2, "expected two awaits: the fetch and the .json() parse"
    for i, chunk in enumerate(awaits):
        after_await_stmt = chunk[chunk.index(";") + 1:]
        next_stmt = after_await_stmt.split(";")[0]
        assert "_fl3dEpiGen" in next_stmt, (
            f"await #{i + 1} in _fl3dEpiRecompute must be followed immediately "
            "by a _fl3dEpiGen recheck, before the response is used"
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
    assert "!== _fl3dEpiRefCam" in fn, (
        "lines must be drawn on the tile that is NOT the reference"
    )


def test_style_matches_the_reprojection_card(js):
    block = _epi_block(js)
    assert "setLineDash([6, 4])" in block
    assert "_flColor(" in block
    assert "labelAnchor(" in block and "nameLabelBox(" in block
    # Scoped to _fl3dDrawEpilines itself: `ctx.lineWidth = 1.2` appears
    # elsewhere in the file (the marker outline), so an unscoped substring
    # check is satisfied even if the epiline width were changed to e.g. 7.
    fn = js.split("function _fl3dDrawEpilines")[1].split("\n    }")[0]
    assert "lineWidth = 1" in fn
    assert "lineWidth = 1.2" not in fn, (
        "must pin the epiline's own lineWidth, not a value inherited from "
        "the marker-drawing style"
    )


def test_label_step_advances_only_for_drawn_lines(js):
    """Otherwise gaps appear in the staircase where a line was null."""
    fn = js.split("function _fl3dDrawEpilines")[1].split("\n    }")[0]
    assert "order++" in fn
    assert fn.index("continue") < fn.index("order++"), (
        "order must advance after the null check, not before it"
    )


# ── C2: every label-mutation site must note an epipolar edit ──────────────
#
# Proven during final review: deleting every _fl3dEpiNoteEdit(...) call from
# frame_labeler_3d.js left every test above green. The feature's headline
# behaviour — "recomputed 2s after the labels stop changing" — had zero
# coverage, which is exactly what let the sibling tile's click/right-click
# handlers ship without ever calling it (C1).
#
# These tests are positional: each slices out the exact handler or function
# body (the same technique test_a_generation_counter_guards_the_async_draw
# uses) and asserts, within THAT block, both the state write and the
# _fl3dEpiNoteEdit(...) call are present, in that order. A substring count
# across the whole file would not catch a call sitting in the wrong handler
# — which is exactly the shape C1 was.

def _block(js, start_marker, end_marker):
    """Text between start_marker (exclusive) and the next end_marker."""
    return js.split(start_marker, 1)[1].split(end_marker, 1)[0]


def test_primary_canvas_click_notes_the_edit(js):
    block = _block(js, 'flCanvas.addEventListener("click", e => {', "\n    });")
    assert "_flLabels[fname][_flSelectedBp] = [cx, cy]" in block
    assert "_fl3dEpiNoteEdit(" in block
    assert (block.index("_flLabels[fname][_flSelectedBp] = [cx, cy]")
            < block.index("_fl3dEpiNoteEdit(")), (
        "the edit must be noted after the label is written"
    )


def test_sibling_tile_click_notes_the_edit(js):
    """C1: in sync mode the sibling tile's canvas gets its OWN click handler,
    built inside _fl3dRenderTile — the only place a point is placed on the
    second camera. It must note the edit against the tile's OWN cam
    (+tile.dataset.cam) so the reference flips to whichever tile was
    actually clicked, not whatever _fl3dFocusedCam happened to hold."""
    block = _block(js, 'canvas.addEventListener("click", (e) => {', "\n        });")
    assert "_flLabels[fname][_flSelectedBp] = [cx, cy]" in block
    assert "_fl3dEpiNoteEdit(+tile.dataset.cam)" in block
    assert (block.index("_flLabels[fname][_flSelectedBp] = [cx, cy]")
            < block.index("_fl3dEpiNoteEdit(+tile.dataset.cam)")), (
        "the edit must be noted after the label is written"
    )


def test_sibling_tile_rightclick_notes_the_edit(js):
    """C1: same gap as the sibling click handler, on the delete side — right-
    click on the sibling tile is the only way to remove a point on the
    second camera in sync mode."""
    block = _block(js, 'canvas.addEventListener("contextmenu", (e) => {', "\n        });")
    assert "_flLabels[fname][_flSelectedBp] = null" in block
    assert "_fl3dEpiNoteEdit(+tile.dataset.cam)" in block
    assert (block.index("_flLabels[fname][_flSelectedBp] = null")
            < block.index("_fl3dEpiNoteEdit(+tile.dataset.cam)")), (
        "the edit must be noted after the label is cleared"
    )


def test_remove_bp_label_notes_the_edit(js):
    block = _block(js, "function _flRemoveBpLabel(bp) {", "\n    }")
    assert "_flLabels[fname][bp] = null" in block
    assert "_fl3dEpiNoteEdit(" in block
    assert (block.index("_flLabels[fname][bp] = null")
            < block.index("_fl3dEpiNoteEdit(")), (
        "the edit must be noted after the label is cleared"
    )


def test_toggle_visibility_notes_the_edit(js):
    """Hiding/showing a bodypart changes what collectRefPoints sends as the
    reference camera's points (hidden bodyparts are excluded), so it counts
    as a label mutation even though it writes _flHidden, not _flLabels."""
    block = _block(js, "function _flToggleVisibility(bp) {", "\n    }")
    assert "_flHidden[fname][bp] = !_flHidden[fname][bp]" in block
    assert "_fl3dEpiNoteEdit(" in block
    assert (block.index("_flHidden[fname][bp] = !_flHidden[fname][bp]")
            < block.index("_fl3dEpiNoteEdit(")), (
        "the edit must be noted after visibility is toggled"
    )


def test_wasd_nudge_notes_the_edit(js):
    block = _block(
        js,
        "if (_wasdKeys.includes(e.key) && _wasdGate && _flSelectedBp && _flVideoStem) {",
        "\n      }",
    )
    assert "_flLabels[fname][_flSelectedBp] = [x, y]" in block
    assert "_fl3dEpiNoteEdit(" in block
    assert (block.index("_flLabels[fname][_flSelectedBp] = [x, y]")
            < block.index("_fl3dEpiNoteEdit(")), (
        "the edit must be noted after the nudged position is written"
    )


def test_delete_key_notes_the_edit_via_remove_bp_label(js):
    """The Delete-key branch delegates to _flRemoveBpLabel (separately
    verified above to note the edit) rather than noting it a second time —
    see M9. A second direct call here would be the redundant-call regression
    M9 fixed, so this pins the delegation instead of duplicating the note."""
    block = _block(
        js,
        'if (e.key === "Delete" && _flCursorInCanvas && _flSelectedBp && _flVideoStem) {',
        "\n      }",
    )
    assert "_flRemoveBpLabel(_flSelectedBp)" in block
    assert "_fl3dEpiNoteEdit(" not in block, (
        "must not note the edit a second time — _flRemoveBpLabel already does"
    )


def test_clear_frame_notes_the_edit(js):
    """C1: _flClearFrame deletes every label on the frame. Without noting the
    edit, the reference camera's lines outlive a 'clear frame'."""
    block = _block(js, "function _flClearFrame() {", "\n    }")
    assert "delete _flLabels[fname]" in block
    assert "_fl3dEpiNoteEdit(" in block
    assert (block.index("delete _flLabels[fname]")
            < block.index("_fl3dEpiNoteEdit(")), (
        "the edit must be noted after the frame's labels are cleared"
    )


# ── Freeze-to-this-camera (PP) ──────────────────────────────────────────────
# Freezing pins the REFERENCE CAMERA, not the geometry: the lines still
# recompute on every label edit and every frame change, so they always describe
# the frame on screen. Without it, placing the first matching point flips the
# reference to that camera and the guidance vanishes exactly when it is being
# used.

def test_freeze_checkbox_exists_and_starts_disabled_and_unchecked(html):
    assert 'id="fl3d-epiline-freeze"' in html
    box = html.split('id="fl3d-epiline-freeze"')[1].split(">")[0]
    assert "disabled" in box, "must start disabled — nothing to freeze yet"
    assert "checked" not in box, "must start unchecked"


def test_freeze_advertises_its_shortcut(html):
    assert "(PP)" in html


def test_freeze_is_gated_on_the_overlay_being_on(js):
    """Freezing with no lines on screen is meaningless, and a freeze that
    outlived the overlay would silently pin the reference for the next run."""
    fn = js.split("function _fl3dRefreshFreezeGate")[1].split("\n    }")[0]
    assert "flEpiFreeze.disabled = !_fl3dEpiOn" in fn
    assert "_fl3dSetEpiFrozen(false)" in fn, (
        "turning the overlay off must release the freeze"
    )


def test_note_edit_does_not_move_the_reference_while_frozen(js):
    """The whole feature: an edit on the target camera must not steal the
    reference and send the lines to the other tile."""
    fn = js.split("function _fl3dEpiNoteEdit")[1].split("\n    }")[0]
    assert "!_fl3dEpiFrozen" in fn, "frozen edits must not reassign the reference"
    assert "_fl3dEpiSchedule()" in fn, (
        "a frozen edit must STILL recompute — edits on the reference camera "
        "move its own lines"
    )


def test_frame_change_keeps_the_reference_while_frozen_but_still_recomputes(js):
    """Freeze pins the camera across frames; it must not pin the geometry, or
    the lines would describe a frame that is no longer on screen."""
    body = js.split("function _flShowFrame")[1]
    seg = body.split("_fl3dEpiRecompute()")[0]
    assert "if (!_fl3dEpiFrozen) _fl3dEpiRefCam = _fl3dFocusedCam" in seg, (
        "a frame change must not reset the reference while frozen"
    )
    assert "_fl3dEpiSegments = {}" in seg, (
        "the previous frame's lines must still be cleared — freezing the "
        "camera must never freeze stale geometry onto a new frame"
    )


def test_double_p_toggles_freeze_and_undoes_the_first_press(js):
    """The single toggle fires immediately, so the second press has to revert
    it or PP would leave the overlay in the wrong state."""
    block = js.split("document.addEventListener(\"keydown\"")[1]
    idx = block.lower().index('"p"')
    guard = block[max(0, idx - 400): idx + 900]
    assert "classifyPPress" in guard, "PP must use the unit-tested classifier"
    assert "_fl3dSetEpiFrozen" in guard, "double-tap must toggle the freeze"
    assert "revert" in guard, "the double must undo the single that already fired"


def test_freeze_uses_the_shared_classifier_not_a_hand_rolled_timer(js):
    """The timing rules are unit-tested in epiline_request.mjs; a second copy
    here would put them beyond that test's reach."""
    assert "classifyPPress" in js
    assert "internal/epiline_request.mjs" in js


def test_init_time_gate_state_is_declared_before_the_init_call(js):
    """Temporal-dead-zone guard. This shipped broken once (2026-08-05).

    `_fl3dRefreshEpiGate()` is invoked once during module init. It reaches
    `_fl3dRefreshFreezeGate`, which reads `_fl3dEpiFrozen`. `let` bindings are
    NOT hoisted — reading one before its declaration executes throws
    ReferenceError, which aborts the whole `initFl3d` IIFE and leaves the
    labeler dead: the folder dropdown populates, then selecting one shows no
    frame at all.

    Declaring the freeze state down in the EPIPOLAR OVERLAY section put it ~500
    lines AFTER the init call. `node --check` cannot see this (it is a runtime
    error, not a syntax one) and no existing test executed the module, so it
    reached production. Assert the ordering directly.
    """
    lines = js.splitlines()

    def line_of(needle):
        for i, line in enumerate(lines):
            if needle in line:
                return i
        raise AssertionError(f"not found: {needle}")

    init_call = line_of("    _fl3dRefreshEpiGate();")
    for decl in ("let _fl3dEpiFrozen", "let _fl3dLastPPress",
                 "let _fl3dEpiOn", "let _fl3dEpiCalib"):
        assert line_of(decl) < init_call, (
            f"`{decl}` is declared at line {line_of(decl) + 1}, after the "
            f"init-time _fl3dRefreshEpiGate() call at line {init_call + 1}. "
            "That is a temporal dead zone: init throws ReferenceError and the "
            "frame labeler stops rendering frames entirely."
        )

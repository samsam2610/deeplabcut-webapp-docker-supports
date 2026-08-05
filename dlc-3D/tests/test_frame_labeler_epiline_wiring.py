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


def test_gate_uses_the_shared_helper(js):
    """The three gating rules are unit-tested in epiline_request.mjs. Wiring a
    second, hand-rolled copy here would put them beyond that test's reach."""
    assert "epiGateReason" in js
    assert "internal/epiline_request.mjs" in js


def test_calibration_field_is_read_from_labeled_frames(js):
    assert "_fl3dEpiCalib" in js
    assert ".calibration" in js


def _epi_block(js):
    """The overlay section, delimited by its own banner comment."""
    assert "EPIPOLAR OVERLAY" in js, "overlay section must be banner-delimited"
    return js.split("EPIPOLAR OVERLAY")[1]


def test_debounce_is_two_seconds(js):
    assert "FL3D_EPI_DEBOUNCE_MS = 2000" in js


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
    fn = js.split("function _fl3dEpiRecomputeOne")[1].split("\n    }")[0]
    awaits = fn.split("await")[1:]
    assert len(awaits) >= 2, "expected two awaits: the fetch and the .json() parse"
    for i, chunk in enumerate(awaits):
        after_await_stmt = chunk[chunk.index(";") + 1:]
        next_stmt = after_await_stmt.split(";")[0]
        assert "_fl3dEpiGen" in next_stmt, (
            f"await #{i + 1} in _fl3dEpiRecompute must be followed immediately "
            "by a _fl3dEpiGen recheck, before the response is used"
        )


def test_style_matches_the_reprojection_card(js):
    block = _epi_block(js)
    assert "setLineDash([6, 4])" in block
    assert "_flColor(" in block
    assert "labelAnchor(" in block and "nameLabelBox(" in block
    # Scoped to _fl3dDrawEpilines itself: `ctx.lineWidth = 1.2` appears
    # elsewhere in the file (the marker outline), so an unscoped substring
    # check is satisfied even if the epiline width were changed to e.g. 7.
    # The stroke itself lives in _fl3dDrawOneEpiline since the selected-line
    # highlight was added; _fl3dDrawEpilines is now just collect-and-order.
    fn = js.split("function _fl3dDrawOneEpiline")[1].split("\n    }")[0]
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
    assert "_fl3dEpiNoteEdit()" in block
    assert (block.index("_flLabels[fname][_flSelectedBp] = [cx, cy]")
            < block.index("_fl3dEpiNoteEdit()")), (
        "the edit must be noted after the label is written"
    )


def test_sibling_tile_rightclick_notes_the_edit(js):
    """C1: same gap as the sibling click handler, on the delete side — right-
    click on the sibling tile is the only way to remove a point on the
    second camera in sync mode."""
    block = _block(js, 'canvas.addEventListener("contextmenu", (e) => {', "\n        });")
    assert "_flLabels[fname][_flSelectedBp] = null" in block
    assert "_fl3dEpiNoteEdit()" in block
    assert (block.index("_flLabels[fname][_flSelectedBp] = null")
            < block.index("_fl3dEpiNoteEdit()")), (
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


# ── Selected-marker emphasis ────────────────────────────────────────────────

def test_the_selected_bodypart_line_is_emphasised(js):
    """Selecting a bodypart must make ITS line stand out — that line is the
    one the user is about to click along."""
    fn = js.split("function _fl3dDrawOneEpiline")[1].split("\n    }")[0]
    assert "selected" in fn, "the draw must know which line is selected"
    assert "lineWidth = 2.5" in fn, "the selected line must be thicker than 1"
    # Scoped to the STROKE, before `strokeStyle = color`. The same white is
    # reused on the selected label's outline further down, so an unscoped
    # check passes with the line's casing deleted — verified by deleting it.
    stroke = fn.split("ctx.strokeStyle = color")[0]
    assert 'rgba(255,255,255,0.85)' in stroke, (
        "the selected line needs the same white casing the selected MARKER "
        "uses, so emphasis reads identically for a point and its line, and "
        "survives both light and dark video"
    )
    assert "lineWidth = 5" in stroke, "the casing must be wider than the stroke"


def test_the_selected_line_is_drawn_last(js):
    """Painting it in bodypart order lets a later line cross over the very one
    being aimed at."""
    fn = js.split("function _fl3dDrawEpilines")[1].split("\n    }")[0]
    assert "filter" in fn and "isSel" in fn, (
        "expected a two-pass draw putting the selected line on top"
    )
    assert fn.index("!isSel(d)") < fn.index("...drawable.filter(isSel)"), (
        "non-selected lines must be drawn before the selected one"
    )


def test_the_label_staircase_still_follows_bodypart_order(js):
    """Reordering the DRAW must not reorder the labels, or they shuffle
    position whenever the selection changes."""
    fn = js.split("function _fl3dDrawEpilines")[1].split("\n    }")[0]
    collect = fn.split("const isSel")[0]
    assert "order++" in collect, (
        "the staircase order must be assigned in the collection pass, in "
        "bodypart order — not in the reordered draw pass"
    )
    assert collect.index("continue") < collect.index("order++")


def test_auto_advance_is_judged_on_the_frame_just_labelled(js):
    """Both click handlers must pass the frame they wrote to.

    Falling back to the focused tile stalled the advance in sync mode: the
    canvas click fires in the target phase, the row handler moves focus only
    afterwards on the bubble, so clicking the non-focused camera judged the
    advance against the other one. With cam0 complete, nothing was missing
    there and the selection never moved -- the exact workflow the epipolar
    lines encourage. See tests/unit/test_auto_advance.mjs for the rule itself.
    """
    calls = [l.strip() for l in js.splitlines() if "_flAutoAdvanceBp(" in l
             and "function _flAutoAdvanceBp" not in l]
    assert len(calls) == 2, f"expected both click handlers to call it, got {calls}"
    for c in calls:
        assert "_flAutoAdvanceBp(fname" in c, (
            f"{c!r} passes no frame, so it falls back to the focused tile "
            "and stalls in sync mode"
        )


# ── Per-tile toggles ────────────────────────────────────────────────────────
# Each camera tile owns a checkbox. Ticking it shows, on THAT tile, the lines
# projected from the OTHER camera. That makes the reference explicit, which is
# what let the old global toggle, the "freeze" flag and the P/PP shortcuts all
# be deleted.

def test_both_tile_headers_carry_a_disabled_checkbox(html, js):
    """Primary comes from the template, siblings are built in JS. Both, or the
    control silently exists on only one camera."""
    assert 'class="fl3d-tile-epi-cb" disabled' in html, "primary tile header"
    assert 'class="fl3d-tile-epi-cb" disabled' in js, "sibling tile header"


def test_the_removed_controls_are_gone(html, js):
    """The global toggle, the freeze box and the shortcuts were replaced, not
    supplemented — leaving either would give two ways to mean the same thing."""
    for gone in ('id="fl3d-epiline"', 'id="fl3d-epiline-freeze"'):
        assert gone not in html, f"{gone} should have been removed"
    for gone in ("_fl3dEpiOn", "_fl3dEpiFrozen", "_fl3dSetEpiFrozen",
                 "classifyPPress", "_fl3dLastPPress", "_fl3dEpiRefCam"):
        assert gone not in js, f"{gone} survives the per-tile redesign"


def test_no_p_shortcut_remains(js):
    block = js.split("document.addEventListener(\"keydown\"")[1]
    assert 'e.key === "p"' not in block and 'e.key === "P"' not in block, (
        "the P/PP shortcuts were removed by request"
    )


def test_a_tile_projects_from_the_other_camera(js):
    """The defining behaviour: cam1's box shows lines computed FROM cam0."""
    fn = js.split("function _fl3dEpiSourceFor")[1].split("\n    }")[0]
    assert "!== cam" in fn, "the source must be the tile that is NOT this one"
    one = js.split("function _fl3dEpiRecomputeOne")[1].split("\n    }")[0]
    assert "_fl3dEpiSourceFor(cam)" in one
    assert "ref_cam=${src}&tgt_cam=${cam}" in one, (
        "the request must project FROM the other camera ONTO this tile"
    )


def test_state_is_keyed_by_camera_not_by_tile_element(js):
    """_fl3dSyncRenderRow rebuilds the tiles every frame change; a choice
    stored on the element would be lost on the next frame."""
    # Declared with the other early state, not inside the overlay section —
    # the init-time gate reads them, so they must precede it (see the TDZ
    # guard below). Assert on the whole file, not the section.
    assert "_fl3dEpiShow     = new Map()" in js
    assert "_fl3dEpiSegments = new Map()" in js


def test_tiles_are_rewired_after_every_row_render(js):
    """Rebuilt tiles come back with fresh, unbound, unchecked boxes."""
    fn = js.split("function _fl3dSyncRenderRow")[1].split("\n    function ")[0]
    assert "_fl3dRefreshEpiGate()" in fn, (
        "without this the checkboxes go dead and lose their state on the "
        "next frame — the 'state cleared, not re-established' trap"
    )


def test_wiring_restores_stored_state_and_binds_once(js):
    fn = js.split("function _fl3dWireTileEpi")[1].split("\n    }")[0]
    assert "cb.checked = !!_fl3dEpiShow.get(cam)" in fn, "must restore the choice"
    assert "_fl3dEpiBound" in fn, (
        "the change listener must be bound once, not stacked on every re-wire"
    )
    assert fn.index("_fl3dEpiBound") < fn.index("addEventListener"), (
        "the guard must come before the bind, or it never prevents anything"
    )


def test_each_tile_draws_only_its_own_segments(js):
    fn = js.split("function _fl3dDrawEpilines")[1].split("\n    /**")[0]
    assert "_fl3dEpiShow.get(cam)" in fn, "a tile with its box off must draw nothing"
    assert "_fl3dEpiSegments.get(cam)" in fn, (
        "each tile draws the lines computed for IT, not a shared set"
    )


def test_no_init_time_read_hits_a_temporal_dead_zone(js):
    """Generic TDZ guard. This exact failure has shipped TWICE (2026-08-05).

    `_fl3dRefreshEpiGate()` is invoked once during module init, and reaches
    module state through `_fl3dWireTileEpi`. `let` and `const` are both
    hoisted-but-uninitialised, so reading one before its declaration executes
    throws ReferenceError — which aborts the whole `initFl3d` IIFE and leaves
    the labeler dead: the folder dropdown still populates (server-rendered),
    then selecting one renders no frame at all.

    Deliberately generic rather than a fixed list of names: the first version
    of this test enumerated the state of the day, so when the overlay was
    rewritten the test looked design-specific, was deleted with the rest of
    that design, and the bug came straight back. Anything the init-time gate
    path touches is covered automatically.
    """
    lines = js.splitlines()
    init_call = next(i for i, l in enumerate(lines)
                     if l.strip() == "_fl3dRefreshEpiGate();")

    # Names the init-time gate path can read, gathered from the functions it
    # actually calls rather than hardcoded.
    reached = ["_fl3dRefreshEpiGate", "_fl3dWireTileEpi", "_fl3dEpiGateReason",
               "_fl3dSetEpiShown", "_fl3dEpiTiles"]
    bodies = "".join(js.split(f"function {fn}")[1].split("\n    }")[0]
                     for fn in reached if f"function {fn}" in js)

    import re
    for i, line in enumerate(lines):
        m = re.match(r"\s*(?:let|const)\s+(_fl3d\w+|_fl\w+)\s*=", line)
        if not m or i < init_call:
            continue
        name = m.group(1)
        assert name not in bodies, (
            f"`{name}` is declared at line {i + 1}, AFTER the init-time "
            f"_fl3dRefreshEpiGate() call at line {init_call + 1}, and is read "
            "on that call path. That is a temporal dead zone: init throws "
            "ReferenceError and the frame labeler stops rendering frames."
        )

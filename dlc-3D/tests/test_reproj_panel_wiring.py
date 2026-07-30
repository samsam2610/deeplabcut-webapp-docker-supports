import re
from pathlib import Path

import pytest

JS = (
    Path(__file__).parent.parent / "src" / "static"
    / "inline_analysis_3d_reprojection.js"
)


@pytest.fixture(scope="module")
def js():
    return JS.read_text()


def test_panel_block_present(js):
    assert "REPROJECTION PANEL" in js


def test_placeholder_wire_panel_is_gone(js):
    assert "function _reprojWirePanel() {}" not in js


def test_calls_the_three_engine_endpoints(js):
    assert "/dlc-3d/reproject/thresholds" in js
    assert "/dlc-3d/reproject/run" in js
    assert "/dlc-3d/reproject/epiline" in js


def test_sends_both_h5_paths_and_the_trusted_camera(js):
    block = js.split("REPROJECTION PANEL")[1]
    for field in ("ref_h5", "tgt_h5", "calibration", "ref_cam", "tgt_cam"):
        assert field in block, "run payload missing {}".format(field)


def test_sends_k1_and_k2(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "k1" in block and "k2" in block


def test_renders_threshold_source_so_uncalibrated_bodyparts_are_visible(js):
    """A bodypart whose thresholds fell back to pooled/default must be visibly
    marked — its verdicts are not trustworthy on their own."""
    block = js.split("REPROJECTION PANEL")[1]
    assert "threshold_source" in block


def test_run_button_is_disabled_while_running(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "disabled" in block


def test_overrides_are_sent_when_set(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "overrides" in block


def test_overlay_block_present(js):
    assert "EPIPOLAR OVERLAY" in js


def test_overlay_placeholder_is_gone(js):
    assert "function _reprojWireEpipolarOverlay() {}" not in js


def test_overlay_subscribes_to_the_drawtile_hook(js):
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert '"drawTile"' in block


def test_overlay_scales_from_video_to_canvas_coordinates(js):
    """The canvas is not the image's natural size, so raw pixel coordinates
    would land in the wrong place."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "scaleFor" in block
    assert "naturalWidth" in block


def test_overlay_imports_the_shared_scaling_helpers(js):
    assert "internal/marker_overlay.mjs" in js
    assert "scaleFor" in js
    assert "videoToCanvas" in js


def test_overlay_only_draws_on_the_judged_camera(js):
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "tile.cam" in block


def test_overlay_is_gated_by_the_checkbox(js):
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "showLines" in block


def test_overlay_caches_per_frame_requests(js):
    """One request per (frame, bodypart) — the hook fires on every seek."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "cache" in block.lower()


def test_overlay_guards_against_stale_frame_draws(js):
    """drawTile is async and awaits a fetch per bodypart. A seek that lands
    while a fetch is in flight must not let the resumed continuation paint an
    epipolar line onto a canvas already repainted for a newer frame."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "_reprojDrawGen" in block, "no generation counter guarding the draw"
    # The counter must be bumped per invocation and re-checked after the await.
    assert "++_reprojDrawGen" in block, "generation counter never incremented"
    assert block.count("_reprojDrawGen") >= 3, (
        "expected declare/bump/compare — the guard must be re-checked after await"
    )


def test_overlay_is_wired_where_the_viewer_actually_exists(js):
    """The drawTile subscription must be made inside _ensureViewer, after the
    viewer and its feature modules exist.

    Regression (2026-07-30): the overlay was wired only from the bootstrap path,
    which runs at DOMContentLoaded while _viewer is still null — it is created
    lazily by _ensureViewer when a video is opened. The
    `if (_reprojOverlayBound || !_viewer) return;` guard therefore fired on every
    call and nothing ever re-invoked it, so no drawTile subscriber was ever
    registered and "Show epipolar lines" did nothing at all.
    """
    body = js.split("function _ensureViewer()")[1].split("\n  return _viewer;")[0]
    assert "_reprojWireEpipolarOverlay()" in body, (
        "overlay must be wired inside _ensureViewer, where _viewer exists"
    )


def test_overlay_wiring_runs_after_the_feature_modules(js):
    """Our subscriber must be registered AFTER markerEditor's, because
    markerEditor clears the canvas in its own drawTile handler. Subscribing
    first means our line is erased before it is ever seen."""
    body = js.split("function _ensureViewer()")[1].split("\n  return _viewer;")[0]
    assert body.index("_viewer.use(_markerEditor)") < body.index(
        "_reprojWireEpipolarOverlay()"
    ), "overlay subscribed before markerEditor — its clearRect would erase the line"


def test_overlay_toggle_forces_a_real_repaint(js):
    """VideoViewer exposes no redraw()/refresh()/repaint(). The toggle handler
    must not depend on one: `_viewer?.redraw?.()` silently no-ops, so ticking the
    box would draw nothing until the user happened to seek.

    Comment lines are stripped first — the invariant is about executable code,
    and the surrounding comments legitimately mention redraw() to explain why it
    is not used.
    """
    block = js.split("EPIPOLAR OVERLAY")[1]
    code = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )
    assert not re.search(r"\.\s*redraw", code), (
        "toggle calls a VideoViewer redraw method that does not exist"
    )
    assert "seek(" in code, "toggle must force a repaint via the viewer's seek path"


def test_overlay_rebinds_after_viewer_teardown_and_reopen(js):
    """The Back button (_iaBack) nulls _viewer; reopening builds a NEW one via
    _ensureViewer. A bare boolean "already bound" flag would block rebinding, so
    the epipolar overlay would silently stop working after the first
    open -> Back -> reopen cycle.

    This is the "state cleared, not re-established" trap already recorded in
    docs/regression-catalog.md. The guard must therefore track WHICH viewer
    instance it bound to, not merely that it bound once.
    """
    block = js.split("EPIPOLAR OVERLAY")[1]
    code = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )
    assert re.search(r"_reprojOverlayBoundTo\s*===\s*_viewer", code), (
        "overlay guard must compare against the current viewer instance so a "
        "recreated viewer is rebound"
    )
    assert not re.search(r"\b_reprojOverlayBound\b\s*(\|\||\)|=\s*true)", code), (
        "bare boolean bound-flag survives; it blocks rebinding after teardown"
    )
    # Cache keys are `frame|bodypart` with no session identity, so binding to a
    # new viewer must drop entries from the previously-open session.
    bind = code.split("_reprojOverlayBoundTo = _viewer;")[1][:400]
    assert "_reprojLineCache.clear()" in bind, (
        "stale epipolar lines from the previous session would be served"
    )


def test_run_payload_sends_all_four_per_camera(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "_reprojPerCam" in block
    for field in ("gate_ref", "low_tgt", "high_conf", "rescue_floor"):
        assert field in block


def test_estimate_sends_high_conf_but_not_the_other_three(js):
    """Only high_conf feeds auto_threshold. Sending gate_ref / low_tgt /
    rescue_floor to the thresholds endpoint would imply an effect they do not
    have — they are consumed by classify and apply_verdicts, neither of which
    runs during an estimate."""
    fn = js.split("async function _reprojEstimate")[1].split("\nasync function")[0]
    assert "high_conf" in fn
    for field in ("gate_ref", "low_tgt", "rescue_floor"):
        assert field not in fn, "{} must not be sent to /reproject/thresholds".format(field)


def test_params_are_persisted_per_project(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "reproj_params" in block
    assert "/dlc/project/ui-setting" in block


def test_persistence_save_is_debounced(js):
    """Matches the existing pose3d_view_prefs_reproj flow — a change on every
    keystroke must not become a POST on every keystroke."""
    fn = js.split("function _reprojSaveParams")[1].split("\nfunction ")[0]
    assert "setTimeout" in fn and "clearTimeout" in fn


def test_overrides_are_not_filtered_at_load_time(js):
    """At card-open the real bodypart list is unknown, and after Back → open
    another project it holds the PREVIOUS project's list. Filtering there
    silently drops the new project's legitimate overrides, changing which camera
    is trusted with no visible error. Keeping an unknown key is harmless — the
    engine only reads overrides for bodyparts present in the h5.
    """
    fn = js.split("async function _reprojLoadParams")[1].split("\nasync function")[0]
    # Strip comments to avoid false positives (comments legitimately mention why
    # the list is NOT used).
    code = "\n".join(line for line in fn.splitlines() if not line.lstrip().startswith("//"))
    assert "known.size === 0 || known.has(bp)" not in code and "known.has(bp)" not in code, (
        "load must not filter against a list it cannot yet trust"
    )


def test_overrides_are_pruned_once_the_bodypart_list_is_known(js):
    """The prune belongs where the authoritative list arrives."""
    fn = js.split("function _reprojRenderOverrides")[1].split("\nfunction ")[0]
    assert "delete _reprojOverrides" in fn, "no prune where the list is known"
    assert "_reprojKnownBodyparts" in fn


def test_known_bodyparts_reset_on_teardown(js):
    """_iaBack tears the card down; a stale list surviving it would be filtered
    against on the next project."""
    fn = js.split("function _iaBack")[1].split("\nfunction ")[0]
    assert "_reprojKnownBodyparts = []" in fn


def test_persistence_loads_from_ensure_viewer(js):
    """Asserting the function merely EXISTS would pass even if it were never
    called. Pin the actual call site: _ensureViewer runs once per card open,
    after a project is selected — unlike the bootstrap, which runs at
    DOMContentLoaded before any project exists."""
    fn = js.split("function _ensureViewer()")[1].split("\n  return _viewer;")[0]
    assert "_reprojLoadParams()" in fn


def test_line_colour_comes_from_the_bodypart_chip(js):
    """The chip already carries labelerColor(idx) as --bp-color, so reading it
    keeps lines and markers in lockstep without duplicating palette logic or
    editing the shared viewer library."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "_reprojBodypartColor" in block
    assert "--bp-color" in block


def test_chip_queries_are_scoped_to_this_card(js):
    """CROSS-CARD GUARD. `.vv-bp-chip` is built by the shared markerEditor, so
    both cards' chips are in the same document. A document-wide query would
    silently read the OTHER card's colours and visibility, and would only
    misbehave when both cards are open."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    code = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )
    assert "ia3dr-bp-chips" in code, "chip lookups must be rooted at #ia3dr-bp-chips"
    assert 'document.querySelector(".vv-bp-chip' not in code, (
        "document-wide chip query would match the original card's chips"
    )


def test_hidden_bodyparts_get_no_line(js):
    """markerEditor marks hidden chips with .vis-hidden, which also covers
    per-frame hiding. Hiding a marker but keeping its line would be
    contradictory."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "vis-hidden" in block
    assert "_reprojIsBodypartHidden" in block


def test_labels_use_the_shared_geometry_and_label_box(js):
    """Reimplementing either would let the epipolar labels drift from the marker
    name labels."""
    assert "internal/epiline_label.mjs" in js
    assert "labelAnchor" in js
    assert "nameLabelBox" in js


def test_label_order_counts_only_visible_bodyparts(js):
    """order is the index among VISIBLE bodyparts so the staircase compacts when
    parts are hidden, instead of leaving gaps where hidden ones would have sat."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "visible" in block.lower()


def test_help_keys_in_markup_all_exist_in_the_help_module():
    """CROSS-FILE GUARD. When someone adds a parameter and forgets its help
    text, this fails — instead of a user meeting a blank box."""
    import re
    from pathlib import Path
    static = Path(__file__).parent.parent / "src" / "static"
    card = (static / "card_inline_analysis_3d_reprojection.html").read_text()
    mod = (static / "internal" / "reproj_help.mjs").read_text()

    used = set(re.findall(r'data-help="([^"]+)"', card))
    assert used, "no data-help attributes found at all"
    defined = set(re.findall(r"^\s{2}(\w+):\s*\{", mod, re.M))
    missing = used - defined
    assert not missing, "markup uses help keys with no entry: {}".format(sorted(missing))


def test_help_listener_covers_focus_not_just_hover(js):
    """Focus is the only route for keyboard users, and tabbing through the
    inputs should teach the same things as mousing over them."""
    block = js.split("REPROJECTION PANEL")[1]
    assert "focusin" in block and "mouseover" in block
    assert "_reprojWireHelp" in block


def test_help_restores_the_default_on_leave(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "HELP_DEFAULT" in block
    assert "focusout" in block or "mouseout" in block


def test_every_internal_helper_used_is_actually_imported(js):
    """Guard against the exact failure this test was born from: a helper was
    USED in the overlay while its import line was never added. `node --check`
    parses that happily — an undefined identifier is valid syntax — and it only
    explodes at runtime as a ReferenceError, silently killing the epipolar
    lines.

    For every name exported by a ./internal/*.mjs module, if this file calls it
    as a bare identifier, an import for that name must exist.
    """
    import re
    from pathlib import Path

    internal = Path(__file__).parent.parent / "src" / "static" / "internal"
    imported = set()
    for names in re.findall(
        r'^import\s*\{([^}]+)\}\s*from\s*"\./internal/[\w.]+";', js, re.M
    ):
        imported.update(n.strip() for n in names.split(","))

    # Strip comments so a name mentioned only in prose is not counted as a use.
    code = "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))

    missing = []
    for mod in sorted(internal.glob("*.mjs")):
        for name in re.findall(r"export\s+(?:const|function|let)\s+(\w+)", mod.read_text()):
            used = re.search(r"(?<![\w.])" + re.escape(name) + r"\s*\(", code)
            if used and name not in imported:
                missing.append("{} (from {})".format(name, mod.name))
    assert not missing, "used without an import: {}".format(missing)


def test_bodypart_source_is_the_chips_not_a_run(js):
    """REGRESSION. The overlay previously read markerEditor.posedBodyparts (not
    in that module's public API, so always undefined) and then the audit summary
    (populated only by a Run, in memory only). With markers on screen but no Run
    in the current page session the list was empty and no line was ever drawn —
    and a page reload put it back into that state."""
    fn = js.split("function _reprojActiveBodyparts")[1].split("\nfunction ")[0]
    code = "\n".join(l for l in fn.splitlines() if not l.lstrip().startswith("//"))
    assert "activeBodyparts(" in code, "must delegate to the tested pure resolver"
    assert "ia3dr-bp-chips" in code, "chips are the source that needs no Run"
    assert "posedBodyparts" not in code, "that method does not exist"


def test_draw_loop_consults_the_pure_filter(js):
    block = js.split("EPIPOLAR OVERLAY")[1]
    assert "shouldDrawLine" in block


def test_fetch_keeps_the_likelihood_the_endpoint_already_sends(js):
    """The endpoint has always returned it; the frontend used to throw it away."""
    fn = js.split("async function _reprojFetchSegment")[1].split("\nasync function")[0]
    assert "likelihood" in fn


def test_label_order_counts_only_lines_actually_drawn(js):
    """REGRESSION: with lines now filtered by likelihood too, using the loop
    index as `order` would leave gaps in the label staircase wherever a line was
    filtered out."""
    block = js.split("EPIPOLAR OVERLAY")[1]
    code = "\n".join(l for l in block.splitlines() if not l.lstrip().startswith("//"))
    assert "order++" in code, "order must increment on a successful draw"
    assert "order < visible.length" not in code, (
        "order is still the loop index, so filtered lines leave gaps"
    )


def test_display_threshold_is_client_side_only(js):
    """It gates drawing, not judgement, so it must never reach the engine."""
    block = js.split("REPROJECTION PANEL")[1]
    assert "line_lik" not in block.split("_reprojPayload")[1][:900], (
        "the display threshold must not be sent in a request payload"
    )

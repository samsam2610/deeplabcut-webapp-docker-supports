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


# ── Peak-screen wiring (Task 8) ──────────────────────────────────────────────
# The main webapp's inline-analysis routes carry no /dlc-3d prefix; dlc-3D's own
# /reproject routes do. See dlc/inline_analysis.py and dlc_3d_bp/routes.py.

def test_analyze_for_tag_posts_to_the_peaks_endpoint(js):
    assert "/dlc/project/inline-analysis/peaks" in js
    assert "/dlc/project/inline-analysis/peaks/status" in js


def test_peaks_payload_carries_h5_paths_parallel_to_video_paths(js):
    """The endpoint 400s without h5_paths of the same length/order as
    video_paths (see dlc/inline_analysis.py:peaks_submit()). Assert the
    actual construction — mapping over videoPaths, one h5 per video, built
    from <stem> + scorer + '.h5' — not just that both key strings appear
    somewhere in the function (a truncated or scorer-less list would still
    satisfy that)."""
    fn = js.split("async function _reprojEmitPeaks")[1].split("\nasync function")[0]
    assert fn, "could not locate _reprojEmitPeaks"
    assert "videoPaths.map(" in fn, (
        "h5_paths must be derived by mapping videoPaths 1:1, not built "
        "separately or truncated"
    )
    assert "+ scorer +" in fn, (
        "each h5 path must be built from <stem> + scorer + '.h5' — a path "
        "missing the scorer writes the sidecar where nothing will find it"
    )
    assert "h5_paths: h5Paths" in fn, (
        "the full mapped array must be sent, not a slice of it"
    )


def test_the_peaks_pass_skips_rather_than_guesses_when_scorer_is_unknown(js):
    """A wrong h5 path writes the sidecar where nothing will ever find it — skip
    with a status message instead of guessing."""
    fn = js.split("async function _reprojEmitPeaks")[1].split("\nasync function")[0]
    assert "scorer" in fn
    assert "if (!scorer)" in fn or "!scorer" in fn


def test_peaks_poller_reuses_the_active_polls_set(js):
    """Must mirror _pollReq's setInterval + _activePolls bookkeeping, not a
    parallel ad hoc timer that _stopAllPolls can't see."""
    assert "function _pollPeaksReq" in js
    fn = js.split("function _pollPeaksReq")[1].split("\nfunction ")[0]
    assert fn, "could not locate _pollPeaksReq"
    assert "_activePolls.add" in fn and "_activePolls.delete" in fn


def test_the_peaks_pass_is_gated_on_the_checkbox(js):
    fn = js.split("async function _onAnalyzeTagClick")[1].split(
        "\nasync function _onTriangulateTagClick"
    )[0]
    assert fn, "could not locate _onAnalyzeTagClick"
    assert "ia3dr-emit-peaks" in fn, (
        "the peaks pass must be guarded by the emit-peaks checkbox"
    )


def test_the_peaks_pass_runs_after_the_analysis_polls_resolve(js):
    fn = js.split("async function _onAnalyzeTagClick")[1].split(
        "\nasync function _onTriangulateTagClick"
    )[0]
    assert fn.index("_pollReq") < fn.index("_reprojEmitPeaks"), (
        "peaks must be emitted only after both cameras finish"
    )


# ── Peak-screen wiring for the other two analyze entry points ───────────────
# The checkbox moved out of the tag-only row into the always-visible
# .ia3dr-analyze-block precisely because "Start analysis from current frame"
# and "Start analysis for range" also need to consult it — previously only
# _onAnalyzeTagClick did.

def _fn_body(js, name, next_name):
    fn = js.split("async function {}".format(name))[1].split(
        "\n{}".format(next_name)
    )[0]
    assert fn, "could not locate {}".format(name)
    return fn


def test_start_from_current_frame_is_gated_on_the_checkbox_and_calls_emit_peaks(js):
    fn = _fn_body(js, "_onAnalyzeClick", "async function _onAnalyzeRangeConfinedClick")
    assert "ia3dr-emit-peaks" in fn, (
        "_onAnalyzeClick must consult the emit-peaks checkbox"
    )
    assert "_reprojEmitPeaks(" in fn, (
        "_onAnalyzeClick must call _reprojEmitPeaks"
    )
    assert fn.index("_pollReq") < fn.index("_reprojEmitPeaks"), (
        "peaks must be emitted only after both cameras finish"
    )
    assert "[{ start: startFrame, n: nFrames }]" in fn, (
        "the single-range list must actually carry the run's start/n, not "
        "an empty or hardcoded range"
    )


def test_start_for_range_is_gated_on_the_checkbox_and_calls_emit_peaks(js):
    fn = _fn_body(js, "_onAnalyzeRangeConfinedClick", "function _framesForActiveNoteTags")
    assert "ia3dr-emit-peaks" in fn, (
        "_onAnalyzeRangeConfinedClick must consult the emit-peaks checkbox"
    )
    assert "_reprojEmitPeaks(" in fn, (
        "_onAnalyzeRangeConfinedClick must call _reprojEmitPeaks"
    )
    assert fn.index("_pollReq") < fn.index("_reprojEmitPeaks"), (
        "peaks must be emitted only after both cameras finish"
    )
    assert "[{ start: startFrame, n: nFrames }]" in fn, (
        "the single-range list must actually carry the locked range's "
        "start/n, not an empty or hardcoded range"
    )


def test_the_run_payload_carries_the_screen_parameters(js):
    fn = js.split("function _reprojPayload")[1].split("\nfunction ")[0]
    assert fn, "could not locate _reprojPayload"
    assert "require_peaks" in fn and "peak_score_floor" in fn


def test_estimate_does_not_send_the_screen_parameters(js):
    """Neither parameter affects auto_threshold — sending them to
    /reproject/thresholds would imply an effect they do not have there."""
    fn = js.split("async function _reprojEstimate")[1].split("\nasync function")[0]
    for field in ("require_peaks", "peak_score_floor"):
        assert field not in fn, "{} must not be sent to /reproject/thresholds".format(field)


def test_the_screen_params_round_trip_through_reproj_params(js):
    save = js[
        js.index("function _reprojSaveParams"):
        js.index("async function _reprojLoadParams")
    ]
    assert save, "could not locate _reprojSaveParams"
    assert "emit_peaks" in save and "require_peaks" in save and "peak_floor" in save

    load = js[
        js.index("async function _reprojLoadParams"):
        js.index("function _reprojRenderThresholds")
    ]
    assert load, "could not locate _reprojLoadParams"
    assert "emit_peaks" in load and "require_peaks" in load and "peak_floor" in load
    assert 'typeof prefs.emit_peaks === "boolean"' in load, (
        "a params blob written before this feature must not force the checkbox"
    )
    assert 'typeof prefs.require_peaks === "boolean"' in load, (
        "a params blob written before this feature must not force the checkbox"
    )


def test_new_controls_are_registered_for_persistence(js):
    """Edits to the three new controls must persist like every other param."""
    fn = js.split("function _reprojWirePanel")[1].split("EPIPOLAR OVERLAY")[0]
    assert fn, "could not locate _reprojWirePanel"
    for accessor in ("_reprojEl.requirePeaks()", "_reprojEl.peakFloor()", "_reprojEl.emitPeaks()"):
        assert accessor in fn, "{} not wired into the change-listener loop".format(accessor)


def test_the_require_peaks_checkbox_is_gated_on_sidecar_presence(js):
    """Assert the actual disabled/checked assignments the response drives, not
    just that the substring "disabled" appears somewhere nearby — the catch
    branch's unconditional `box.disabled = true` would already satisfy a bare
    "disabled in window" check even if the success branch never greyed the
    box out at all."""
    assert "/dlc-3d/reproject/peaks-status" in js
    fn = js.split("async function _reprojRefreshPeaksAvailability")[1].split(
        "\nasync function"
    )[0]
    assert fn, "could not locate _reprojRefreshPeaksAvailability"
    assert "box.disabled = !any" in fn, (
        "disabled must be DERIVED from sidecar presence, not a constant"
    )
    assert "if (!any) box.checked = false" in fn, (
        "require-peaks must be force-UNCHECKED when no sidecar covers the pair"
    )


def test_availability_refresh_uses_reprojpair_not_missing_accessors(js):
    """_reprojEl.refH5()/.tgtH5() do not exist; the h5 pair must come from the
    same _reprojPair() source /reproject/run uses."""
    assert "_reprojEl.refH5" not in js
    assert "_reprojEl.tgtH5" not in js
    fn = js.split("async function _reprojRefreshPeaksAvailability")[1].split(
        "\nasync function"
    )[0]
    assert fn, "could not locate _reprojRefreshPeaksAvailability"
    assert "_reprojPair(" in fn


def test_availability_refresh_actually_fetches_and_assigns_disabled(js):
    """Guards against a trivially-short-circuited body: the fetch to
    peaks-status and the disabled assignment derived from its response must
    both be present, and the fetch must happen BEFORE the assignment it
    supposedly drives."""
    fn = js.split("async function _reprojRefreshPeaksAvailability")[1].split(
        "\nasync function"
    )[0]
    assert fn, "could not locate _reprojRefreshPeaksAvailability"
    assert "fetch(`/dlc-3d/reproject/peaks-status" in fn
    assert fn.index("fetch(`/dlc-3d/reproject/peaks-status") < fn.index(
        "box.disabled = !any"
    ), "box.disabled must be derived from the fetch response, not assigned before it"


def test_availability_refresh_is_not_gutted_by_an_early_return(js):
    """REGRESSION GUARD. An unconditional `return;` inserted ahead of the
    fetch would leave every string above present as unreachable dead code —
    none of the substring-presence tests could see it. Strip the two
    legitimate guarded returns (missing box element; no pair loaded yet) and
    require nothing to be left over."""
    fn = js.split("async function _reprojRefreshPeaksAvailability")[1].split(
        "\nasync function"
    )[0]
    assert fn, "could not locate _reprojRefreshPeaksAvailability"
    stripped = fn.replace("if (!box) return;", "")
    stripped = re.sub(r"if \(!pair\) \{[^}]*return;\s*\}", "", stripped, flags=re.S)
    assert "return;" not in stripped, (
        "an extra unconditional return would gut the function while its fetch "
        "+ assignment logic stays present but unreachable"
    )


def test_availability_refresh_is_called_once_the_pair_resolves(js):
    """A correct, never-invoked function would pass every test above.
    _applyOverlayPrimary is where ref/tgt h5 actually become known — the same
    place /reproject/run's own pair comes from — so the refresh must be
    called from there. Regression shape: the epipolar overlay has twice
    shipped correctly-written-but-never-subscribed."""
    fn = js.split("async function _applyOverlayPrimary")[1].split("\nasync function")[0]
    assert fn, "could not locate _applyOverlayPrimary"
    assert "_reprojRefreshPeaksAvailability()" in fn


def test_the_audit_surfaces_the_screen_coverage(js):
    fn = js.split("async function _reprojRun")[1].split("\nfunction _reprojRenderHelp")[0]
    assert fn, "could not locate _reprojRun"
    assert "peak_screen" in fn
    assert "_reprojEl.status()" in fn


def test_peak_screen_coverage_line_is_null_guarded(js):
    """summary.peak_screen is null when the screen did not run (no
    require_peaks / no peaks sidecar) — the coverage line must not assume it
    is always an object."""
    fn = js.split("async function _reprojRun")[1].split("\nfunction _reprojRenderHelp")[0]
    assert fn, "could not locate _reprojRun"
    assert "const scr = data.peak_screen;" in fn
    assert "if (scr)" in fn, "the coverage line must be guarded on peak_screen truthiness"


def test_reprojecting_a_reprojected_layer_surfaces_a_note(js):
    """The backend redirects an already-reprojected selection to its source
    layer (see reprojection.py's _normalize_reproject_input) and replaces the
    existing output — it does not reproject the layer the user actually
    selected. The card must say so, comparing the requested vs. actually-read
    paths from the response's config."""
    fn = js.split("async function _reprojRun")[1].split("\nfunction _reprojRenderHelp")[0]
    assert fn, "could not locate _reprojRun"
    assert "cfg.ref_h5_requested !== cfg.ref_h5" in fn
    assert "cfg.tgt_h5_requested !== cfg.tgt_h5" in fn
    assert "_reprojEl.status()" in fn


# ── Pinnable snapshot picker ─────────────────────────────────────────────────

def test_pin_toggle_enforces_single_selection(js):
    """Checking one row must uncheck every other row — radio behaviour with
    checkbox styling."""
    fn = js.split("function _ia3drOnPinToggle")[1].split("\nfunction ")[0]
    assert fn, "could not locate _ia3drOnPinToggle"
    assert "b.checked = false" in fn, (
        "no code path unchecks the other rows — single-selection is not enforced"
    )


def test_checking_a_row_writes_the_dropdown_value(js):
    """The dropdown's value is what every analysis request actually sends, so
    checking a pin row must set it — not just persist the pin."""
    fn = js.split("function _ia3drOnPinToggle")[1].split("\nfunction ")[0]
    assert fn, "could not locate _ia3drOnPinToggle"
    assert "snapSel.value = changedCb.value" in fn, (
        "checking a row does not sync the dropdown's value"
    )


def test_pin_round_trips_through_the_ui_setting_key(js):
    assert 'const IA3DR_PINNED_SNAPSHOT_KEY = "pinned_snapshot";' in js
    save_fn = js.split("function _ia3drSavePinnedSnapshot")[1].split("\nfunction ")[0]
    assert save_fn, "could not locate _ia3drSavePinnedSnapshot"
    assert "/dlc/project/ui-setting" in save_fn
    assert "IA3DR_PINNED_SNAPSHOT_KEY" in save_fn

    apply_fn = js.split("async function _ia3drApplyPinnedSnapshot")[1].split(
        "\nasync function"
    )[0]
    assert apply_fn, "could not locate _ia3drApplyPinnedSnapshot"
    assert "/dlc/project/ui-setting?key=" in apply_fn
    assert "IA3DR_PINNED_SNAPSHOT_KEY" in apply_fn


def test_unchecking_the_pinned_row_clears_the_pin_without_touching_the_dropdown(js):
    fn = js.split("function _ia3drOnPinToggle")[1].split("\nfunction ")[0]
    assert fn, "could not locate _ia3drOnPinToggle"
    else_branch = fn.split("} else {")[1] if "} else {" in fn else ""
    assert else_branch, "no unchecked branch in _ia3drOnPinToggle"
    assert '_ia3drSavePinnedSnapshot("")' in else_branch, (
        "unchecking the pinned row must clear the persisted pin"
    )
    assert "snapSel" not in else_branch, (
        "unchecking must leave the dropdown alone"
    )


def test_missing_pinned_snapshot_does_not_silently_change_the_dropdown(js):
    """If the persisted pin no longer matches any snapshot in the current
    list, the dropdown must be left at its normal default and a note shown —
    never a silent fallback to a different model."""
    fn = js.split("async function _ia3drApplyPinnedSnapshot")[1].split(
        "\nasync function"
    )[0]
    assert fn, "could not locate _ia3drApplyPinnedSnapshot"
    no_match_branch = fn.split("if (!match) {")[1].split("\n  }")[0]
    assert "snapSel" not in no_match_branch, (
        "the dropdown must not be touched when the pinned snapshot is missing"
    )
    assert "lastRun" in no_match_branch, (
        "a note must be surfaced in the existing status area"
    )
    assert fn.index("if (!match) {") < fn.index("snapSel.value = match.value"), (
        "the dropdown must only be set in the found-a-match path"
    )


def test_snapshot_refresh_applies_the_pin(js):
    """Pin re-application must happen on every snapshot-list (re)build — card
    open, the refresh button, and a shuffle change all funnel through
    _loadSnapshots."""
    fn = js.split("async function _loadSnapshots")[1].split("\nasync function")[0]
    assert fn, "could not locate _loadSnapshots"
    assert "_ia3drRenderPinList(items)" in fn
    assert "_ia3drApplyPinnedSnapshot(items)" in fn


def test_peak_score_floor_preserves_an_explicit_zero(js):
    """0 is a legitimate 'no score requirement' setting (the backend
    range-checks 0..1 and accepts it) — same reasoning the spec gives for
    line_lik's "0 genuinely means show everything". `|| 0.05` would silently
    turn a typed 0 into the default; a Number.isFinite check must be used
    instead so only a blank/unparseable field falls back."""
    fn = js.split("function _reprojPayload")[1].split("\nfunction ")[0]
    assert fn, "could not locate _reprojPayload"
    assert "Number.isFinite(v) ? v : 0.05" in fn
    assert "peakFloor()?.value) || 0.05" not in fn, (
        "|| 0.05 turns an explicitly-typed 0 into the default"
    )

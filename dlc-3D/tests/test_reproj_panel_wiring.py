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

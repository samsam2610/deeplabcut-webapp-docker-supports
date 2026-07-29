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

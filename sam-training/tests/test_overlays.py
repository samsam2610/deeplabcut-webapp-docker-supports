import numpy as np
import pytest

from src import overlays


def test_box_layer_converts_yyxx_to_xywh():
    # Boxes are (y0, y1, x0, x1) everywhere in this module but the canvas wants
    # x/y/w/h -- a swap here would draw every ROI in the wrong place.
    l = overlays.box_layer("pellet", (330, 390, 355, 445), "#fff")
    assert (l["x"], l["y"], l["w"], l["h"]) == (355, 330, 90, 60)


def test_mask_round_trips():
    mask = np.zeros((20, 30), dtype=bool)
    mask[5:12, 8:22] = True
    out = overlays.decode_mask(overlays.encode_mask(mask))
    assert np.array_equal(out, mask)


def test_mask_round_trips_when_the_first_pixel_is_set():
    # The RLE always starts with a False run; a mask starting True must get a
    # leading zero or every subsequent run flips polarity.
    mask = np.ones((4, 4), dtype=bool)
    out = overlays.decode_mask(overlays.encode_mask(mask))
    assert np.array_equal(out, mask)


def test_empty_mask_round_trips():
    mask = np.zeros((6, 6), dtype=bool)
    assert np.array_equal(overlays.decode_mask(overlays.encode_mask(mask)), mask)


def test_mask_rle_is_much_smaller_than_the_raw_mask():
    mask = np.zeros((600, 800), dtype=bool)
    mask[300:380, 350:450] = True                # a paw-sized blob
    assert len(overlays.encode_mask(mask)["rle"]) < 400


def test_downsample_keeps_short_dropouts():
    # A stride sample happily steps over a brief dropout; the timeline exists
    # precisely to show those, so the bucket minimum is load-bearing.
    frames = np.arange(20000)
    scores = np.full(20000, 0.9, dtype=float)
    scores[12345:12352] = 0.1
    out = overlays.downsample_trace(frames, scores, max_points=500)
    assert min(out["scores"]) < 0.2


def test_downsample_passes_short_traces_through():
    frames = np.arange(10)
    scores = np.linspace(0, 1, 10)
    out = overlays.downsample_trace(frames, scores, max_points=500)
    assert out["frames"] == list(range(10))


def test_scalar_layer_shape():
    l = overlays.scalar_layer("ncc", 0.812, 0.0, 1.0, "pellet NCC")
    assert l["kind"] == "scalar" and l["range"] == [0.0, 1.0]
    assert l["value"] == pytest.approx(0.812)

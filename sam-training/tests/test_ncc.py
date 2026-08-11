"""NCC behaviour on synthetic frames.

The point of these is the illumination-invariance claim: the white reload vane
swings the frame mean from ~40 to ~142, and every absolute-brightness test tried
against the real footage failed. If NCC ever stops being invariant to that, the
whole stage-1 design is void, so it is asserted here rather than assumed.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from src import ncc


PEDESTAL_BOX = (30, 60, 40, 70)
SEARCH_BOX = (10, 90, 20, 100)


def scene(pellet=True, brightness=40, size=(120, 140)):
    """Dark frame, black post, optional bright pellet on top."""
    img = np.full(size, brightness, dtype=np.uint8)
    img[60:100, 50:60] = 10                      # the post
    if pellet:
        img[38:52, 46:64] = 235                  # the pellet
    return img


def test_template_matches_itself_in_a_wider_search_box():
    frame = scene(pellet=True)
    template = ncc.crop(frame, PEDESTAL_BOX)
    score, _ = ncc.match(frame, template, SEARCH_BOX)
    assert score > 0.99


def test_present_scores_far_above_absent():
    template = ncc.crop(scene(pellet=True), PEDESTAL_BOX)
    present, _ = ncc.match(scene(pellet=True), template, SEARCH_BOX)
    absent, _ = ncc.match(scene(pellet=False), template, SEARCH_BOX)
    assert present - absent > 0.3


def test_score_survives_the_reload_vane_flooding_the_frame():
    # This is the measured failure mode of every brightness threshold tried:
    # frame mean 40 -> 142. NCC must barely notice.
    template = ncc.crop(scene(pellet=True, brightness=40), PEDESTAL_BOX)
    dark, _ = ncc.match(scene(pellet=True, brightness=40), template, SEARCH_BOX)
    flooded, _ = ncc.match(scene(pellet=True, brightness=142), template, SEARCH_BOX)
    assert abs(dark - flooded) < 0.05


def test_match_reports_full_frame_coordinates():
    frame = scene(pellet=True)
    template = ncc.crop(frame, PEDESTAL_BOX)
    _, (x, y) = ncc.match(frame, template, SEARCH_BOX)
    assert (x, y) == (PEDESTAL_BOX[2], PEDESTAL_BOX[0])


def test_template_larger_than_the_search_box_scores_sentinel():
    frame = scene()
    template = ncc.crop(frame, (0, 100, 0, 120))
    score, _ = ncc.match(frame, template, (40, 50, 40, 50))
    assert score == -1.0


def test_to_gray_passes_through_single_channel():
    g = scene()
    assert ncc.to_gray(g) is g


def test_to_gray_converts_colour():
    colour = np.zeros((10, 10, 3), dtype=np.uint8)
    assert ncc.to_gray(colour).shape == (10, 10)

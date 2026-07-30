import numpy as np
import pytest

from dlc_3d_bp import peak_screen as ps
from dlc_3d_bp.peak_verdict import peak_verdict, RESCUE, AMBIGUOUS, NO_EVIDENCE, CORRECTED

UNJUDGED, REJECT, RESCUE_REJECTED, CONFIRM = 0, 1, 3, 4
T_OK, FLOOR = 5.0, 0.05


def _one(code, dists, scores, covered=True):
    """Screen a single cell and return its resulting code."""
    new, _ = ps.screen_rescues(
        np.array([code], np.uint8),
        np.array([dists], float),
        np.array([scores], float),
        np.array([covered], bool),
        t_ok=T_OK, score_floor=FLOOR,
    )
    return int(new[0])


def test_keeps_rescue_when_only_the_argmax_is_on_the_line():
    assert _one(RESCUE, [1.0, 40.0, 40.0], [0.4, 0.4, 0.4]) == RESCUE


def test_refuses_with_no_evidence_when_no_peak_is_on_the_line():
    assert _one(RESCUE, [40.0, 40.0, 40.0], [0.4, 0.4, 0.4]) == NO_EVIDENCE


def test_refuses_as_ambiguous_when_two_peaks_are_on_the_line():
    assert _one(RESCUE, [1.0, 2.0, 40.0], [0.4, 0.4, 0.4]) == AMBIGUOUS


def test_refuses_as_corrected_when_a_different_peak_is_the_one_on_the_line():
    assert _one(RESCUE, [40.0, 1.0, 40.0], [0.4, 0.4, 0.4]) == CORRECTED


def test_a_peak_below_the_score_floor_does_not_qualify():
    # On the line, but the detector barely responded there.
    assert _one(RESCUE, [1.0, 40.0, 40.0], [0.01, 0.0, 0.0]) == NO_EVIDENCE


def test_nan_padded_peaks_never_qualify():
    assert _one(RESCUE, [np.nan, np.nan, np.nan], [0.0, 0.0, 0.0]) == NO_EVIDENCE


@pytest.mark.parametrize("code", [UNJUDGED, REJECT, RESCUE_REJECTED, CONFIRM, AMBIGUOUS])
def test_non_rescue_verdicts_are_passed_through_untouched(code):
    # Peaks say "no evidence", but the screen has no authority over these.
    assert _one(code, [40.0, 40.0, 40.0], [0.4, 0.4, 0.4]) == code


def test_an_uncovered_frame_keeps_its_geometry_verdict():
    assert _one(RESCUE, [np.nan] * 3, [0.0] * 3, covered=False) == RESCUE


def test_stats_count_every_outcome():
    codes = np.array([RESCUE, RESCUE, RESCUE, RESCUE, CONFIRM], np.uint8)
    d = np.array([
        [1.0, 40.0, 40.0],    # keep
        [40.0, 40.0, 40.0],   # no evidence
        [1.0, 2.0, 40.0],     # ambiguous
        [40.0, 1.0, 40.0],    # corrected
        [40.0, 40.0, 40.0],   # CONFIRM, untouched
    ])
    s = np.full((5, 3), 0.4)
    covered = np.array([True, True, True, False, True])
    new, stats = ps.screen_rescues(codes, d, s, covered, T_OK, FLOOR)
    assert stats["rescues"] == 4
    assert stats["covered"] == 3
    assert stats["kept"] == 1
    assert stats["no_evidence"] == 1
    assert stats["ambiguous"] == 1
    assert stats["corrected"] == 0      # that frame was uncovered
    assert stats["refused"] == 2
    assert int(new[3]) == RESCUE        # uncovered, untouched
    assert int(new[4]) == CONFIRM


def test_input_codes_are_not_mutated():
    codes = np.array([RESCUE], np.uint8)
    ps.screen_rescues(codes, np.array([[40.0]]), np.array([[0.4]]),
                      np.array([True]), T_OK, FLOOR)
    assert int(codes[0]) == RESCUE


def test_empty_input_is_handled():
    new, stats = ps.screen_rescues(
        np.zeros(0, np.uint8), np.zeros((0, 3)), np.zeros((0, 3)),
        np.zeros(0, bool), T_OK, FLOOR)
    assert new.shape == (0,)
    assert stats["rescues"] == 0


def test_agrees_with_the_scalar_reference_implementation():
    """The vectorised screen must match peak_verdict.peak_verdict exactly.

    Two implementations of one rule drift. This is the test that catches it.
    """
    rng = np.random.default_rng(20260730)
    n, k = 500, 4
    d = rng.uniform(0, 12, size=(n, k))
    d[rng.random((n, k)) < 0.2] = np.nan
    s = rng.uniform(0, 0.5, size=(n, k))
    codes = np.full(n, RESCUE, np.uint8)
    new, _ = ps.screen_rescues(codes, d, s, np.ones(n, bool), T_OK, FLOOR)
    for i in range(n):
        want, _ = peak_verdict(d[i], s[i], T_OK, FLOOR)
        assert int(new[i]) == want, f"row {i}: {d[i]} {s[i]}"

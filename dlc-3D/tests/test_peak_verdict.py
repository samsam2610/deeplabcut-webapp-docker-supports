import numpy as np

from dlc_3d_bp.peak_verdict import CORRECTED, NO_EVIDENCE, peak_verdict

# Existing verdict codes, re-declared here so this test does not depend on
# epipolar_core (which pulls in cv2).
RESCUE = 2
AMBIGUOUS = 5


def test_no_peak_near_the_line_is_no_evidence():
    """The occlusion answer: the image supports nothing on this line."""
    d = np.array([40.0, 55.0, np.nan, np.nan, np.nan])
    s = np.array([0.8, 0.5, 0.0, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (NO_EVIDENCE, None)


def test_only_the_argmax_qualifies_is_a_rescue():
    d = np.array([1.2, 40.0, np.nan, np.nan, np.nan])
    s = np.array([0.7, 0.6, 0.0, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (RESCUE, 0)


def test_a_different_peak_qualifies_is_a_correction():
    """DLC's argmax is off the line but a secondary detection sits on it."""
    d = np.array([38.0, 1.1, np.nan, np.nan, np.nan])
    s = np.array([0.30, 0.22, 0.0, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (CORRECTED, 1)


def test_two_qualifying_peaks_is_ambiguous():
    """The adjacent-digit case: if two candidates both satisfy the line, the
    geometry has discriminated nothing."""
    d = np.array([1.0, 2.0, np.nan, np.nan, np.nan])
    s = np.array([0.5, 0.45, 0.0, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (AMBIGUOUS, None)


def test_a_peak_below_the_score_floor_does_not_qualify():
    """A near-zero-score peak is noise, not evidence, however well it lines up."""
    d = np.array([0.5, 40.0, np.nan, np.nan, np.nan])
    s = np.array([0.02, 0.6, 0.0, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (NO_EVIDENCE, None)


def test_padding_never_qualifies():
    """NaN-distance / zero-score padding must not be mistaken for a candidate."""
    d = np.full(5, np.nan)
    s = np.zeros(5)
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.0) == (NO_EVIDENCE, None)


def test_correction_prefers_the_highest_scoring_qualifier_when_alone():
    d = np.array([30.0, 1.0, 31.0, np.nan, np.nan])
    s = np.array([0.9, 0.4, 0.3, 0.0, 0.0])
    assert peak_verdict(d, s, t_ok=5.0, score_floor=0.1) == (CORRECTED, 1)

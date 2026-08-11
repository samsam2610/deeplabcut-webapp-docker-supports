import numpy as np

from src import intervals
from src.notes import Trial


def test_debounce_suppresses_a_short_flip():
    # A 3-sample occlusion inside a long armed stretch must not split it.
    seq = [True] * 30 + [False] * 3 + [True] * 30
    out = intervals.debounce(seq, min_run=10)
    assert all(out)


def test_debounce_accepts_a_sustained_flip():
    seq = [True] * 30 + [False] * 30
    out = intervals.debounce(seq, min_run=10)
    assert out[0] is True and out[-1] is False


def test_debounce_dates_the_flip_to_where_the_run_started():
    # The state changed when the run began, not once it was confirmed --
    # otherwise every edge is reported min_run samples too late.
    seq = [True] * 20 + [False] * 20
    out = intervals.debounce(seq, min_run=5)
    assert out[19] is True
    assert out[20] is False


def test_present_intervals_from_a_clean_trace():
    frames = np.arange(0, 100)
    scores = np.where((frames >= 20) & (frames < 60), 0.85, 0.35)
    ivs = intervals.present_intervals(frames, scores, min_run=3)
    assert len(ivs) == 1
    assert ivs[0].start == 20 and ivs[0].end == 59


def test_present_intervals_respects_stride():
    frames = np.arange(0, 500, 5)
    scores = np.where((frames >= 100) & (frames < 300), 0.9, 0.3)
    ivs = intervals.present_intervals(frames, scores, min_run=3)
    assert len(ivs) == 1
    assert ivs[0].start == 100 and ivs[0].end == 295


def test_length_mismatch_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        intervals.present_intervals([1, 2, 3], [0.9, 0.9])


def test_window_closes_at_the_marker_and_opens_at_the_interval():
    ivs = [intervals.Interval(1000, 1800)]
    trials = [Trial(outcome_frame=1700, outcome="s", onset_frame=1400)]
    wins = intervals.build_windows(trials, ivs)
    assert len(wins) == 1
    assert wins[0].start == 1000
    assert wins[0].end == 1700
    assert wins[0].onset_frame == 1400


def test_window_uses_the_interval_that_ended_just_before_the_marker():
    # The pellet routinely leaves the pedestal a beat before the human keys the
    # outcome, so the marker falls outside the interval.
    ivs = [intervals.Interval(1000, 1650)]
    trials = [Trial(outcome_frame=1700, outcome="f")]
    wins = intervals.build_windows(trials, ivs)
    assert len(wins) == 1 and wins[0].start == 1000


def test_max_lookback_stops_a_window_running_into_the_previous_trial():
    ivs = [intervals.Interval(0, 5000)]
    trials = [Trial(outcome_frame=4000, outcome="s")]
    wins = intervals.build_windows(trials, ivs, max_lookback=1200)
    assert wins[0].start == 2800


def test_trial_with_no_usable_interval_yields_no_window():
    # No window means no candidate -- silently better than guessing.
    ivs = [intervals.Interval(0, 100)]
    trials = [Trial(outcome_frame=9000, outcome="s")]
    assert intervals.build_windows(trials, ivs, max_lookback=1200) == []


def test_too_short_a_window_is_dropped():
    ivs = [intervals.Interval(990, 1000)]
    trials = [Trial(outcome_frame=1000, outcome="s")]
    assert intervals.build_windows(trials, ivs, min_length=30) == []


def test_orphan_trials_get_windows_too():
    # Orphans are the point: they are the 198 trials with no onset tag.
    ivs = [intervals.Interval(1000, 1800)]
    trials = [Trial(outcome_frame=1700, outcome="f")]
    wins = intervals.build_windows(trials, ivs)
    assert len(wins) == 1 and wins[0].onset_frame is None
    assert wins[0].outcome == "f"

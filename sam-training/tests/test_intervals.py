import numpy as np

from src import intervals, notes
from src.notes import Trial


def test_lookback_covers_everything_the_pairing_rule_admits():
    """A trial the pairer accepts must always be searchable.

    If MAX_LOOKBACK drops below MAX_TRIAL_FRAMES, some paired trials get a
    window that cannot reach their onset — and stage 1 is the recall gate, so
    that loss is unrecoverable downstream.
    """
    assert intervals.MAX_LOOKBACK >= notes.MAX_TRIAL_FRAMES


def test_onset_at_the_maximum_admissible_gap_is_still_a_candidate():
    gap = notes.MAX_TRIAL_FRAMES - 1
    marker = 50_000
    onset = marker - gap
    ivs = [intervals.Interval(onset - 100, marker)]
    trials = [Trial(outcome_frame=marker, outcome="s", onset_frame=onset)]
    win = intervals.build_windows(trials, ivs)[0]
    assert win.is_candidate(onset)


def test_debounce_default_does_not_erode_a_short_armed_stretch():
    """min_run was 20 samples (100 frames at stride 5) and erased real armed
    stretches, costing 12 of 82 onsets on the worst-case session."""
    frames = np.arange(0, 400, 5)
    scores = np.where((frames >= 100) & (frames < 160), 0.8, 0.3)
    ivs = intervals.present_intervals(frames, scores)
    assert len(ivs) == 1 and ivs[0].start == 100


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


def test_window_closes_at_the_marker_and_opens_a_lookback_before():
    ivs = [intervals.Interval(1000, 1800)]
    trials = [Trial(outcome_frame=1700, outcome="s", onset_frame=1400)]
    wins = intervals.build_windows(trials, ivs, max_lookback=1200)
    assert len(wins) == 1
    assert wins[0].start == 500
    assert wins[0].end == 1700
    assert wins[0].onset_frame == 1400


def test_armed_intervals_are_clipped_to_the_span():
    ivs = [intervals.Interval(0, 5000)]
    trials = [Trial(outcome_frame=1700, outcome="s")]
    win = intervals.build_windows(trials, ivs, max_lookback=1200)[0]
    assert win.armed == (intervals.Interval(500, 1700),)


def test_both_armed_stretches_are_kept():
    # THE bug the first acceptance run caught: on a success the pellet is taken,
    # its interval ends, then the vane reloads and a second interval opens
    # before the marker. Choosing either one alone drops the onset.
    reach = intervals.Interval(1000, 1420)      # onset lives in here
    reload_ = intervals.Interval(1500, 1800)
    trials = [Trial(outcome_frame=1700, outcome="s", onset_frame=1400)]
    win = intervals.build_windows(trials, [reach, reload_], max_lookback=1200)[0]
    assert len(win.armed) == 2
    assert win.is_candidate(1400)


def test_onset_after_the_pellet_is_taken_is_not_a_candidate():
    # The mask must still exclude frames where the pellet has gone: that is
    # the user's criterion #2 and the whole reason for the sweep.
    ivs = [intervals.Interval(1000, 1420), intervals.Interval(1500, 1800)]
    trials = [Trial(outcome_frame=1700, outcome="s")]
    win = intervals.build_windows(trials, ivs, max_lookback=1200)[0]
    assert not win.is_candidate(1450)


def test_max_lookback_stops_a_window_running_into_the_previous_trial():
    ivs = [intervals.Interval(0, 5000)]
    trials = [Trial(outcome_frame=4000, outcome="s")]
    wins = intervals.build_windows(trials, ivs, max_lookback=1200)
    assert wins[0].start == 2800


def test_window_never_starts_before_the_video():
    ivs = [intervals.Interval(0, 5000)]
    trials = [Trial(outcome_frame=300, outcome="s")]
    assert intervals.build_windows(trials, ivs, max_lookback=1200)[0].start == 0


def test_trial_with_no_armed_frames_yields_no_window():
    # No candidates means no proposal -- better than guessing.
    ivs = [intervals.Interval(0, 100)]
    trials = [Trial(outcome_frame=9000, outcome="s")]
    assert intervals.build_windows(trials, ivs, max_lookback=1200) == []


def test_too_few_armed_frames_is_dropped():
    ivs = [intervals.Interval(990, 1000)]
    trials = [Trial(outcome_frame=1000, outcome="s")]
    assert intervals.build_windows(trials, ivs, min_candidates=30) == []


def test_candidate_frames_are_ascending_and_masked():
    ivs = [intervals.Interval(1000, 1002), intervals.Interval(1500, 1501)]
    trials = [Trial(outcome_frame=1700, outcome="s")]
    win = intervals.build_windows(trials, ivs, max_lookback=1200,
                                  min_candidates=1)[0]
    assert win.candidate_frames() == [1000, 1001, 1002, 1500, 1501]


def test_orphan_trials_get_windows_too():
    # Orphans are the point: they are the 198 trials with no onset tag.
    ivs = [intervals.Interval(1000, 1800)]
    trials = [Trial(outcome_frame=1700, outcome="f")]
    wins = intervals.build_windows(trials, ivs)
    assert len(wins) == 1 and wins[0].onset_frame is None
    assert wins[0].outcome == "f"

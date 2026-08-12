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


def test_interval_bounds_are_plain_ints_not_numpy():
    """Sweeps come back as int64 arrays and numpy scalars are not JSON
    serialisable — this cost a 500 on /api/windows."""
    import json
    frames = np.arange(0, 100, dtype=np.int64)
    scores = np.where(frames >= 20, 0.9, 0.3)
    iv = intervals.present_intervals(frames, scores, min_run=3)[0]
    assert type(iv.start) is int and type(iv.end) is int
    json.dumps({"start": iv.start, "end": iv.end})     # must not raise


def test_window_serialises_to_json():
    frames = np.arange(0, 4000, 5, dtype=np.int64)
    scores = np.where((frames >= 1000) & (frames < 2000), 0.9, 0.3)
    ivs = intervals.present_intervals(frames, scores)
    trials = [Trial(outcome_frame=1900, outcome="s", onset_frame=1500)]
    w = intervals.build_windows(trials, ivs)[0]
    import json
    json.dumps({"start": w.start, "end": w.end, "n": w.n_candidates,
                "armed": [{"start": a.start, "end": a.end} for a in w.armed]})


# ── mask-based intervals (the two-camera detector) ──────────────────────────

def test_intervals_from_mask_matches_the_score_path():
    frames = np.arange(0, 300, 5)
    scores = np.where((frames >= 50) & (frames < 200), 0.9, 0.2)
    by_score = intervals.present_intervals(frames, scores)
    by_mask = intervals.intervals_from_mask(frames, scores > 0.5)
    assert by_score == by_mask


def test_intervals_from_mask_debounces():
    frames = np.arange(0, 400, 5)
    mask = (frames >= 100) & (frames < 300)
    mask[(frames >= 190) & (frames < 200)] = False     # 2-sample dropout
    ivs = intervals.intervals_from_mask(frames, mask)
    assert len(ivs) == 1


def test_intervals_from_mask_rejects_mismatched_lengths():
    import pytest
    with pytest.raises(ValueError):
        intervals.intervals_from_mask([1, 2, 3], [True, False])


def test_intervals_from_mask_handles_empty():
    assert intervals.intervals_from_mask([], []) == []


# ── trial boundaries ────────────────────────────────────────────────────────
#
# A window closes at its outcome marker and must not reach back past the
# PREVIOUS one. It did, on 92.8% of trials, and the consequence was silent: on
# banh-mi-1 Jul 7, 40% of all candidate frames sat on the far side of a nearer
# marker and would be labelled from the wrong outcome. That is how trial #11 —
# a failed reach with an `f` at 27536 — came out as start-success-candidate
# from the `s` at 28915.

def _long_armed(a, b, step=5):
    """An armed interval dense enough to clear min_candidates."""
    return intervals.Interval(a, b)


def test_window_never_opens_at_or_before_the_previous_marker():
    trials = [Trial(outcome_frame=10_000, outcome="f"),
              Trial(outcome_frame=11_000, outcome="s")]
    ivs = [_long_armed(7_000, 11_000)]
    wins = intervals.build_windows(trials, ivs)
    second = [w for w in wins if w.end == 11_000][0]
    assert second.start == 10_001
    assert all(a.start > 10_000 for a in second.armed)


def test_the_marker_that_closes_a_window_is_the_next_one_after_every_frame():
    """The invariant, stated directly: for any candidate, the window's own
    marker is the first marker that follows it."""
    markers = [5_000, 6_400, 7_100, 9_000]
    trials = [Trial(outcome_frame=m, outcome="s") for m in markers]
    ivs = [_long_armed(1_000, 9_000)]
    for w in intervals.build_windows(trials, ivs):
        nearer = [m for m in markers if w.start <= m < w.end]
        assert not nearer, f"window {w.start}-{w.end} swallows {nearer}"


def test_guard_reaches_exactly_that_far_past_the_previous_marker():
    trials = [Trial(outcome_frame=10_000, outcome="f"),
              Trial(outcome_frame=11_000, outcome="s")]
    ivs = [_long_armed(7_000, 11_000)]
    wins = intervals.build_windows(trials, ivs, guard=300)
    second = [w for w in wins if w.end == 11_000][0]
    assert second.start == 9_701


def test_guard_cannot_reach_further_back_than_the_lookback():
    trials = [Trial(outcome_frame=10_000, outcome="f"),
              Trial(outcome_frame=11_000, outcome="s")]
    ivs = [_long_armed(1_000, 11_000)]
    wins = intervals.build_windows(trials, ivs, max_lookback=500, guard=100_000)
    second = [w for w in wins if w.end == 11_000][0]
    assert second.start == 10_500


def test_the_first_trial_keeps_its_whole_lookback():
    trials = [Trial(outcome_frame=5_000, outcome="s")]
    ivs = [_long_armed(1_000, 5_000)]
    win = intervals.build_windows(trials, ivs, max_lookback=3_000)[0]
    assert win.start == 2_000


def test_a_window_clipped_to_nothing_is_dropped_not_emitted_empty():
    # Two markers 3 frames apart: the second window has no room for candidates.
    trials = [Trial(outcome_frame=10_000, outcome="f"),
              Trial(outcome_frame=10_003, outcome="s")]
    ivs = [_long_armed(7_000, 10_003)]
    wins = intervals.build_windows(trials, ivs)
    assert [w.end for w in wins] == [10_000]


def test_clipping_does_not_depend_on_the_order_trials_arrive_in():
    ordered = [Trial(outcome_frame=10_000, outcome="f"),
               Trial(outcome_frame=11_000, outcome="s")]
    ivs = [_long_armed(7_000, 11_000)]
    a = intervals.build_windows(ordered, ivs)
    b = intervals.build_windows(list(reversed(ordered)), ivs)
    assert [(w.start, w.end) for w in a] == [(w.start, w.end) for w in b]


def test_trial_11_regression_banh_mi_jul_7():
    """The reported case, with its real frame numbers.

    Window [25915, 28915] closes on `s` at 28915 while `f` sits at 27536. Its
    armed stretches at 26030-27370 are the FAILED reach; labelling them from
    the later `s` is the bug.
    """
    trials = [Trial(outcome_frame=27_536, outcome="f"),
              Trial(outcome_frame=28_915, outcome="s")]
    armed = [intervals.Interval(26_030, 26_055), intervals.Interval(26_465, 26_580),
             intervals.Interval(26_875, 27_250), intervals.Interval(27_325, 27_370),
             intervals.Interval(27_420, 27_625), intervals.Interval(27_775, 27_820),
             intervals.Interval(28_365, 28_595), intervals.Interval(28_865, 28_915)]
    win = [w for w in intervals.build_windows(trials, armed) if w.end == 28_915][0]
    assert win.start == 27_537
    assert min(win.candidate_frames()) > 27_536
    # and the failed reach still belongs to the `f` trial
    fwin = [w for w in intervals.build_windows(trials, armed) if w.end == 27_536][0]
    assert fwin.is_candidate(26_900)


def test_a_paired_onset_behind_an_intervening_marker_needs_a_guard():
    """1.24% of paired trials (16/1304) have their onset before the previous
    marker — the human keyed it late. Documented, not silently lost."""
    trials = [Trial(outcome_frame=10_000, outcome="f"),
              Trial(outcome_frame=11_000, outcome="s", onset_frame=9_800)]
    ivs = [_long_armed(9_000, 11_000)]
    strict = [w for w in intervals.build_windows(trials, ivs) if w.end == 11_000][0]
    assert not strict.is_candidate(9_800)
    loose = [w for w in intervals.build_windows(trials, ivs, guard=500)
             if w.end == 11_000][0]
    assert loose.is_candidate(9_800)

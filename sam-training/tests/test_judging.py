"""The five parameters that decide what counts as a candidate.

They were compiled-in constants tuned once against one session. Exposing them
is only safe if the clamp is identical on both sides — a panel that shows a
value the backend silently replaces is worse than no field at all.
"""
import json

import pytest

from src import intervals, judging


def test_defaults_match_the_tuned_constants():
    """The panel mirrors these in trial_judge.mjs and asserts the same numbers,
    so retuning one side fails on the other."""
    j = judging.Judge()
    assert j.threshold == judging.MATCH_THRESHOLD
    assert j.min_run == intervals.MIN_RUN_SAMPLES
    assert j.lookback == intervals.MAX_LOOKBACK
    assert j.guard == intervals.TRIAL_GUARD


def test_round_trips_through_json(tmp_path):
    j = judging.Judge(threshold=0.62, min_run=9, lookback=2200,
                      min_candidates=50, guard=250)
    judging.save(tmp_path, j)
    assert judging.load(tmp_path) == j


def test_load_without_a_file_gives_the_defaults(tmp_path):
    assert judging.load(tmp_path) == judging.Judge()


def test_a_corrupt_file_falls_back_to_defaults_rather_than_crashing(tmp_path):
    (tmp_path / judging.FILENAME).write_text("{not json")
    assert judging.load(tmp_path) == judging.Judge()


def test_an_unknown_key_is_ignored_not_fatal(tmp_path):
    (tmp_path / judging.FILENAME).write_text(json.dumps({"threshold": 0.6,
                                                         "wat": 1}))
    assert judging.load(tmp_path).threshold == 0.6


@pytest.mark.parametrize("field,given,expected", [
    ("threshold", -1.0, 0.0),
    ("threshold", 4.0, 1.0),
    ("min_run", 0, 1),          # 0 would divide the trace into noise
    ("min_run", -5, 1),
    ("lookback", 0, 1),         # a zero-length window can hold no candidate
    ("min_candidates", -3, 0),  # 0 is meaningful: keep every window
    ("guard", -10, 0),          # negative would push the window forward
])
def test_out_of_range_values_clamp(field, given, expected):
    j = judging.from_dict({field: given})
    assert getattr(j, field) == expected


def test_a_blank_field_keeps_the_default_rather_than_becoming_zero():
    j = judging.from_dict({"threshold": "", "min_run": None})
    assert j.threshold == judging.Judge().threshold
    assert j.min_run == judging.Judge().min_run


def test_a_non_numeric_value_keeps_the_default():
    assert judging.from_dict({"lookback": "soon"}).lookback == \
        judging.Judge().lookback


def test_numeric_strings_are_accepted_because_the_panel_sends_them():
    j = judging.from_dict({"threshold": "0.62", "min_run": "9"})
    assert (j.threshold, j.min_run) == (0.62, 9)


def test_guard_is_capped_at_the_lookback():
    """Reaching further back than the window opens is not a state the panel
    should be able to describe."""
    j = judging.from_dict({"lookback": 1000, "guard": 5000})
    assert j.guard == 1000


def test_to_dict_is_json_serialisable():
    json.dumps(judging.Judge().to_dict())        # must not raise


def test_the_judge_drives_build_windows():
    """The parameters must actually reach the window builder — a field that
    saves but changes nothing is the worst outcome here."""
    from src.notes import Trial
    trials = [Trial(outcome_frame=10_000, outcome="f"),
              Trial(outcome_frame=11_000, outcome="s")]
    ivs = [intervals.Interval(7_000, 11_000)]
    strict = judging.build(trials, ivs, judging.Judge())
    loose = judging.build(trials, ivs, judging.Judge(guard=400))
    assert [w for w in strict if w.end == 11_000][0].start == 10_001
    assert [w for w in loose if w.end == 11_000][0].start == 9_601


def test_the_judge_drives_the_present_threshold():
    import numpy as np
    frames = np.arange(0, 400, 5)
    scores = np.where((frames >= 100) & (frames < 300), 0.60, 0.20)
    assert judging.armed(frames, scores, judging.Judge(threshold=0.50))
    assert not judging.armed(frames, scores, judging.Judge(threshold=0.70))


# ── the panel mirrors this clamp; they must not drift ───────────────────────

def test_a_fractional_integer_field_truncates_rather_than_resetting():
    """`int("6.7")` raises, which would silently restore the default. The
    panel's mirror truncates, so this must too."""
    assert judging.from_dict({"min_run": "6.7"}).min_run == 6
    assert judging.from_dict({"min_run": 6.7}).min_run == 6
    assert judging.from_dict({"lookback": 2999.5}).lookback == 2999


def test_clamping_is_idempotent():
    once = judging.from_dict({"threshold": 9, "guard": -4})
    assert judging.from_dict(once.to_dict()) == once


# ── the two-camera decision ─────────────────────────────────────────────────
#
# `threshold` and `max_3d_dist` lived on PelletModel and were edited in the
# pellet section while the Judge owned every other candidate parameter. Two
# places deciding one thing is the divergence this module exists to end.

def test_the_judge_carries_the_3d_gate():
    assert judging.Judge().max_3d_dist == judging.MAX_3D_DIST


def test_max_3d_dist_clamps_and_round_trips(tmp_path):
    assert judging.from_dict({"max_3d_dist": -1}).max_3d_dist == 0.0
    j = judging.Judge(max_3d_dist=1.5)
    judging.save(tmp_path, j)
    assert judging.load(tmp_path).max_3d_dist == 1.5


def test_a_judge_file_from_before_the_3d_gate_still_loads(tmp_path):
    """Existing sam_training_judge.json has no max_3d_dist. Refusing to load it
    would blank every other tuned value."""
    import json
    (tmp_path / judging.FILENAME).write_text(json.dumps(
        {"threshold": 0.62, "min_run": 9, "lookback": 2200,
         "min_candidates": 50, "guard": 0}))
    j = judging.load(tmp_path)
    assert j.threshold == 0.62 and j.max_3d_dist == judging.MAX_3D_DIST


def test_armed_pair_needs_both_cameras_and_the_3d_gate():
    import numpy as np
    frames = np.arange(0, 100, 5)
    n = len(frames)
    ones = np.ones(n)
    j = judging.Judge(threshold=0.55, max_3d_dist=2.0, min_run=1)
    # both cameras high and close in 3D -> armed
    assert judging.armed_pair(frames, ones * 0.9, ones * 0.9, ones * 0.5, j)
    # cam1 fails -> nothing
    assert not judging.armed_pair(frames, ones * 0.9, ones * 0.2, ones * 0.5, j)
    # both cameras high but the 3D point is wrong -> nothing.
    # This is the case the gate earns its keep on: the reported frame 27591
    # scored 0.55/0.67 with a 3D distance of 8.29.
    assert not judging.armed_pair(frames, ones * 0.9, ones * 0.9, ones * 8.29, j)


def test_a_nan_distance_is_never_armed():
    """NaN means the cameras never agreed, so triangulation was skipped.
    `nan <= max` is False in numpy but a hand-rolled comparison could invert."""
    import numpy as np
    frames = np.arange(0, 50, 5)
    n = len(frames)
    j = judging.Judge(threshold=0.55, max_3d_dist=2.0, min_run=1)
    assert not judging.armed_pair(frames, np.ones(n) * 0.9, np.ones(n) * 0.9,
                                  np.full(n, np.nan), j)


def test_retuning_the_gate_changes_the_mask_without_a_resweep():
    """The point of judging at judge time: the stored sweep is raw scores, so
    a new gate is applied to it instantly."""
    import numpy as np
    frames = np.arange(0, 100, 5)
    n = len(frames)
    s = np.ones(n) * 0.9
    d = np.ones(n) * 3.0
    tight = judging.Judge(threshold=0.55, max_3d_dist=2.0, min_run=1)
    loose = judging.Judge(threshold=0.55, max_3d_dist=4.0, min_run=1)
    assert not judging.armed_pair(frames, s, s, d, tight)
    assert judging.armed_pair(frames, s, s, d, loose)


# ── the paw's epipolar gate ─────────────────────────────────────────────────

def test_the_judge_carries_the_epipolar_tolerance():
    assert judging.Judge().max_epi_px == judging.MAX_EPI_PX


def test_the_default_is_the_measured_one():
    """20 px, measured on the REAL quantity: SAM mask centroids on 55 frames
    where both views verifiably picked the correct paw, under that session's own
    calibration (p95 17.80, so 20 keeps 98.2%).

    Two stand-ins got this wrong first — Left-Paw (a randomly placed decoy) and
    the digit-joint centroid (anatomically corresponding, but a mask includes
    the forearm and each view sees a different amount of it). Both were dwarfed
    by using another session's calibration, which alone costs ~27 px."""
    assert judging.MAX_EPI_PX == 20.0


def test_epi_px_clamps_and_round_trips(tmp_path):
    assert judging.from_dict({"max_epi_px": -4}).max_epi_px == 0.0
    judging.save(tmp_path, judging.Judge(max_epi_px=12.5))
    assert judging.load(tmp_path).max_epi_px == 12.5


def test_epi_px_is_not_truncated_to_an_integer():
    assert judging.from_dict({"max_epi_px": "12.5"}).max_epi_px == 12.5


def test_a_judge_file_from_before_the_paw_gate_still_loads(tmp_path):
    import json
    (tmp_path / judging.FILENAME).write_text(json.dumps({"threshold": 0.62}))
    j = judging.load(tmp_path)
    assert j.threshold == 0.62 and j.max_epi_px == judging.MAX_EPI_PX


def test_paw_pair_accepts_an_aligned_pair_and_rejects_a_skewed_one():
    j = judging.Judge(max_epi_px=15.0)
    assert judging.paw_pair_ok(3.5, j) is True
    assert judging.paw_pair_ok(40.0, j) is False


def test_a_missing_paw_is_never_accepted():
    """None means SAM found no reaching paw in one view. There is no
    correspondence to check, so it cannot pass — and `None <= 15` would raise."""
    assert judging.paw_pair_ok(None, judging.Judge()) is False


def test_a_nan_residual_is_never_accepted():
    import math
    assert judging.paw_pair_ok(math.nan, judging.Judge()) is False


# ── choosing the cam1 paw, rather than testing it ───────────────────────────
#
# The gate picked each camera's paw independently (nearest that camera's pellet)
# and then measured agreement. At the ONSET — the frame the whole tool exists to
# find — the emerging paw is small and cam1's nearest-to-pellet instance is a
# different paw entirely, so the residual came out at ~189 px and the best
# candidate was thrown away. Measured on banh-mi-1 Jul 7 trial 8: 113 of 121
# candidates rejected, including the 2D winner (fused similarity 0.8626, the
# highest in the window).
#
# The correct cam1 instance was in SAM's output the whole time, at rank 2 or 3.
# Constraining the choice to cam0's epipolar line finds it: 189.0 -> 5.7 px.

def test_the_instance_nearest_the_epipolar_line_wins():
    assert judging.pick_by_epiline([176.6, 40.2, 5.7], judging.Judge()) == 2


def test_it_is_the_line_that_decides_not_the_order():
    assert judging.pick_by_epiline([3.1, 88.0, 120.0], judging.Judge()) == 0


def test_nothing_near_the_line_is_a_real_rejection():
    """No instance near the line means cam1 genuinely does not see this paw.
    THAT is evidence of a mismatch; "the nearest-to-pellet instance disagreed"
    never was."""
    assert judging.pick_by_epiline([88.0, 120.0, 300.0], judging.Judge()) is None


def test_no_instances_at_all_is_a_rejection():
    assert judging.pick_by_epiline([], judging.Judge()) is None


def test_the_tolerance_is_the_judge_field():
    tight = judging.Judge(max_epi_px=5.0)
    assert judging.pick_by_epiline([5.7], tight) is None
    assert judging.pick_by_epiline([5.7], judging.Judge(max_epi_px=20.0)) == 0


def test_a_nan_residual_is_not_selectable():
    import math
    assert judging.pick_by_epiline([math.nan], judging.Judge()) is None
    assert judging.pick_by_epiline([math.nan, 4.0], judging.Judge()) == 1


def test_exactly_at_the_tolerance_is_kept():
    assert judging.pick_by_epiline([20.0], judging.Judge(max_epi_px=20.0)) == 0

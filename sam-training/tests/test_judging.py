"""The five parameters that decide what counts as a candidate.

They were compiled-in constants tuned once against one session. Exposing them
is only safe if the clamp is identical on both sides — a panel that shows a
value the backend silently replaces is worse than no field at all.
"""
import json

import pytest

from src import intervals, judging


def test_defaults_match_the_tuned_constants():
    """The default judge must be a no-op against the shipped behaviour,
    otherwise adding the field quietly retunes the pipeline."""
    j = judging.Judge()
    assert j.threshold == intervals.PRESENT_THRESHOLD
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

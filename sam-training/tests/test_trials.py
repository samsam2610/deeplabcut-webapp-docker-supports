"""Per-trial scoring results, so a batch is resumable and reviewable.

Keyed on the MARKER, not the window span. The span moves whenever `lookback` or
`past prev marker` changes, so keying on it would orphan every stored result the
moment a judging parameter was touched.
"""
from src import judging, trials


def _row(marker=24454, **kw):
    d = dict(marker=marker, window_start=22923, outcome="f", mode="3d",
             pick=24045, score=0.8626, n_candidates=121, n_kept=32,
             prompt="right paw", judge_sig="a91c4f",
             scored_at="2026-08-12T15:40:11")
    d.update(kw)
    return trials.Row(**d)


def test_round_trips(tmp_path):
    dest = tmp_path / "v_trials.csv"
    trials.merge("/v/v.avi", [_row()], dest=dest)
    got = trials.read("/v/v.avi", dest)
    assert len(got) == 1
    assert int(got[0]["pick"]) == 24045
    assert got[0]["outcome"] == "f"


def test_the_sidecar_sits_beside_the_video():
    assert trials.path_for("/d/banh_cam0.avi").name == "banh_cam0_trials.csv"


def test_rescoring_a_trial_replaces_its_row(tmp_path):
    dest = tmp_path / "v_trials.csv"
    trials.merge("/v/v.avi", [_row(pick=24045)], dest=dest)
    trials.merge("/v/v.avi", [_row(pick=24050, mode="2d")], dest=dest)
    got = trials.read("/v/v.avi", dest)
    assert len(got) == 1
    assert int(got[0]["pick"]) == 24050 and got[0]["mode"] == "2d"


def test_other_trials_survive_a_rescore(tmp_path):
    dest = tmp_path / "v_trials.csv"
    trials.merge("/v/v.avi", [_row(marker=100), _row(marker=200)], dest=dest)
    trials.merge("/v/v.avi", [_row(marker=100, pick=999)], dest=dest)
    by = {int(r["marker"]): r for r in trials.read("/v/v.avi", dest)}
    assert set(by) == {100, 200}
    assert int(by[100]["pick"]) == 999


def test_a_result_survives_a_change_to_lookback(tmp_path):
    """The whole reason for keying on the marker: the window START moves when
    lookback or the guard changes, and keying on the span would orphan every
    stored result."""
    dest = tmp_path / "v_trials.csv"
    trials.merge("/v/v.avi", [_row(window_start=21454)], dest=dest)
    trials.merge("/v/v.avi", [_row(window_start=23000, pick=24046)], dest=dest)
    got = trials.read("/v/v.avi", dest)
    assert len(got) == 1, "same trial, moved window — one row, not two"
    assert int(got[0]["pick"]) == 24046


def test_rows_come_back_in_marker_order(tmp_path):
    dest = tmp_path / "v_trials.csv"
    trials.merge("/v/v.avi", [_row(marker=300), _row(marker=100),
                              _row(marker=200)], dest=dest)
    assert [int(r["marker"]) for r in trials.read("/v/v.avi", dest)] == [100, 200, 300]


def test_reading_a_missing_file_is_empty(tmp_path):
    assert trials.read("/v/nope.avi", tmp_path / "nope_trials.csv") == []


def test_a_corrupt_file_does_not_lose_the_new_rows(tmp_path):
    dest = tmp_path / "v_trials.csv"
    dest.write_text("garbage\n\x00")
    trials.merge("/v/v.avi", [_row()], dest=dest)
    assert len(trials.read("/v/v.avi", dest)) == 1


def test_markers_already_scored(tmp_path):
    dest = tmp_path / "v_trials.csv"
    trials.merge("/v/v.avi", [_row(marker=100), _row(marker=200)], dest=dest)
    assert trials.scored_markers("/v/v.avi", dest) == {100, 200}


def test_scored_markers_of_a_missing_file_is_empty(tmp_path):
    assert trials.scored_markers("/v/v.avi", tmp_path / "no_trials.csv") == set()


# ── judge signature ─────────────────────────────────────────────────────────

def test_the_signature_changes_with_the_judging_parameters():
    """It invalidates nothing. It makes a result scored under a different gate
    VISIBLE, so it can be spotted rather than silently trusted."""
    a = judging.signature(judging.Judge())
    b = judging.signature(judging.Judge(max_epi_px=30.0))
    assert a != b


def test_the_signature_is_stable_for_the_same_parameters():
    assert judging.signature(judging.Judge()) == judging.signature(judging.Judge())


def test_the_signature_is_short_enough_to_read_in_a_csv():
    assert len(judging.signature(judging.Judge())) <= 12


# ── the frames a stored result surfaced ─────────────────────────────────────
#
# Reported after the first batch: browsing to another trial did not update the
# candidate thumbnails. Two causes; this is the storage half. A stored row held
# only the pick, so a browsed trial had nothing to render even in principle —
# the top frames existed only in the live response of the run that produced them.

def test_the_top_frames_round_trip(tmp_path):
    dest = tmp_path / "v_trials.csv"
    trials.merge("/v/v.avi", [_row(top=[24045, 24046, 24044])], dest=dest)
    got = trials.read("/v/v.avi", dest)[0]
    assert trials.parse_top(got["top"]) == [24045, 24046, 24044]


def test_the_stored_order_is_the_ranking(tmp_path):
    """Column i of the thumbnail strip is the i-th best candidate; sorting the
    frames would silently re-rank them."""
    dest = tmp_path / "v_trials.csv"
    trials.merge("/v/v.avi", [_row(top=[24046, 24041, 24045])], dest=dest)
    got = trials.read("/v/v.avi", dest)[0]
    assert trials.parse_top(got["top"]) == [24046, 24041, 24045]


def test_a_row_without_top_frames_parses_to_empty(tmp_path):
    dest = tmp_path / "v_trials.csv"
    trials.merge("/v/v.avi", [_row()], dest=dest)
    assert trials.parse_top(trials.read("/v/v.avi", dest)[0]["top"]) == []


def test_parse_top_tolerates_junk():
    assert trials.parse_top("") == []
    assert trials.parse_top(None) == []
    assert trials.parse_top("12 x 14") == [12, 14]


def test_top_does_not_collide_with_the_csv_separator(tmp_path):
    """Space-separated inside one cell — a comma would need quoting and the
    file is read by eye as often as by code."""
    dest = tmp_path / "v_trials.csv"
    trials.merge("/v/v.avi", [_row(top=[1, 2, 3])], dest=dest)
    assert "," not in dest.read_text().splitlines()[1].split(",")[-2]

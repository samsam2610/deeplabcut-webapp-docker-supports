import csv
from pathlib import Path

import pytest

from src import notes


def write_csv(tmp_path, rows, stem="vid") -> Path:
    """Companion CSV in the real format: 1-based frame_number, note column."""
    video = tmp_path / f"{stem}.avi"
    video.write_bytes(b"")
    with open(tmp_path / f"{stem}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["timestamp", "frame_number",
                                           "frame_line_status", "note"])
        w.writeheader()
        for frame, note in rows:
            w.writerow({"timestamp": f"{frame / 200:.3f}", "frame_number": frame,
                        "frame_line_status": "10", "note": note})
    return video


def test_reads_only_rows_carrying_a_note(tmp_path):
    video = write_csv(tmp_path, [(1, ""), (10, "start-success"), (20, ""), (30, "s")])
    assert notes.read_notes(video) == [(10, "start-success"), (30, "s")]


def test_missing_csv_is_not_an_error(tmp_path):
    # cam1's companion is empty by convention; that is normal, not a failure.
    assert notes.read_notes(tmp_path / "absent.avi") == []


def test_row_with_note_but_no_frame_number_is_dropped(tmp_path):
    video = tmp_path / "v.avi"
    video.write_bytes(b"")
    (tmp_path / "v.csv").write_text(
        "timestamp,frame_number,frame_line_status,note\n0.0,,10,start-success\n")
    # Defaulting to 0 would invent a trial at the start of the video.
    assert notes.read_notes(video) == []


def test_candidate_notes_are_not_mistaken_for_human_tags(tmp_path):
    video = write_csv(tmp_path, [(10, "start-success"),
                                 (50, "start-success-candidate")])
    rows = notes.read_notes(video)
    assert notes.onsets(rows) == [(10, "start-success")]


def test_pairs_onset_with_matching_outcome():
    rows = [(100, "start-success"), (470, "s")]
    trials = notes.pair_trials(rows)
    assert len(trials) == 1
    assert trials[0].onset_frame == 100
    assert trials[0].outcome == "s"
    assert not trials[0].is_orphan


def test_outcome_without_an_onset_is_an_orphan():
    # This is the tool's actual workload: 198 of these in the target videos.
    trials = notes.pair_trials([(470, "f")])
    assert len(trials) == 1
    assert trials[0].is_orphan
    assert trials[0].outcome_frame == 470


def test_orphans_and_paired_trials_come_back_in_frame_order():
    rows = [(100, "start-success"), (470, "s"), (900, "f"), (1500, "start-failure"),
            (1900, "f")]
    trials = notes.pair_trials(rows)
    assert [t.outcome_frame for t in trials] == [470, 900, 1900]
    assert [t.is_orphan for t in trials] == [False, True, False]


def test_a_marker_is_never_claimed_by_two_onsets():
    rows = [(100, "start-success"), (200, "start-success"), (470, "s")]
    trials = notes.pair_trials(rows)
    claimed = [t for t in trials if not t.is_orphan]
    assert len(claimed) == 1


def test_outcome_beyond_max_gap_is_not_paired():
    rows = [(100, "start-success"), (100 + notes.MAX_TRIAL_FRAMES + 1, "s")]
    trials = notes.pair_trials(rows)
    assert all(t.is_orphan for t in trials)


def test_mismatched_marker_does_not_let_an_onset_steal_the_next_trial():
    # start-success at 100 whose own 's' is missing must NOT reach past the
    # intervening 'f' and claim the next trial's marker.
    rows = [(100, "start-success"), (400, "f"), (800, "s")]
    trials = notes.pair_trials(rows)
    assert all(t.is_orphan for t in trials)


@pytest.mark.parametrize("outcome,expected", [
    ("s", "start-success-candidate"),
    ("f", "start-failure-candidate"),
])
def test_candidate_note_is_derived_from_the_marker(outcome, expected):
    # The label is read off the human marker, never predicted.
    trial = notes.Trial(outcome_frame=500, outcome=outcome)
    assert trial.candidate_note == expected


# ── what the sidecar and the timeline must show ─────────────────────────────

def test_human_marks_include_the_outcome_markers():
    """On a tag-pending video the s/f markers are the ONLY human information.

    The sidecar recorded `onsets()` alone, so banh-mi-1 Jul 7 — 131 markers,
    zero start tags — produced a timeline with no human line anywhere, and the
    `f` sitting inside a mislabelled success window was invisible.
    """
    rows = [(100, "s"), (250, "start-failure"), (400, "f"), (500, "junk")]
    marks = notes.human_marks(rows)
    assert marks == [(100, "s"), (250, "start-failure"), (400, "f")]


def test_human_marks_exclude_our_own_proposals():
    rows = [(100, "start-success-candidate"), (200, "f")]
    assert notes.human_marks(rows) == [(200, "f")]


def test_human_marks_are_sorted_by_frame():
    rows = [(400, "f"), (100, "s"), (250, "start-failure")]
    assert [f for f, _ in notes.human_marks(rows)] == [100, 250, 400]


def test_human_marks_of_an_empty_companion_is_empty():
    assert notes.human_marks([]) == []


# ── tag state per trial, for the dropdown ───────────────────────────────────
#
# Derived from the companion CSV rather than stored, so it reflects a hand-edit
# made in the main webapp instead of going stale against our own bookkeeping.

def test_a_window_with_a_human_tag_reports_it():
    rows = [(24041, "start-failure"), (24454, "f")]
    st = notes.tag_state(rows, 22923, 24454)
    assert st == {"kind": "human", "note": "start-failure", "frame": 24041}


def test_a_window_with_only_our_candidate_reports_candidate():
    rows = [(24045, "start-failure-candidate"), (24454, "f")]
    st = notes.tag_state(rows, 22923, 24454)
    assert st == {"kind": "candidate", "note": "start-failure-candidate",
                  "frame": 24045}


def test_a_human_tag_outranks_a_candidate_in_the_same_window():
    rows = [(24045, "start-failure-candidate"), (24041, "start-failure")]
    assert notes.tag_state(rows, 22923, 24454)["kind"] == "human"


def test_an_untagged_window_reports_none():
    rows = [(24454, "f")]
    assert notes.tag_state(rows, 22923, 24454) is None


def test_the_outcome_marker_itself_is_not_a_tag():
    """`f` closes the window; it is the outcome, not an onset tag."""
    assert notes.tag_state([(24454, "f")], 22923, 24454) is None


def test_a_tag_outside_the_window_is_not_counted():
    rows = [(20000, "start-failure")]
    assert notes.tag_state(rows, 22923, 24454) is None


def test_the_window_bounds_are_inclusive():
    assert notes.tag_state([(22923, "start-success")], 22923, 24454) is not None
    assert notes.tag_state([(24454, "start-success")], 22923, 24454) is not None

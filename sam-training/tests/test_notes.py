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

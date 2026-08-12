import csv

import numpy as np

from src import intervals, onset_csv
from src.notes import Trial


def test_sidecar_name_sits_next_to_the_video():
    p = onset_csv.path_for("/videos/banh-mi-1_cam0_2026.avi")
    assert p.name == "banh-mi-1_cam0_2026_onset.csv"
    assert str(p.parent) == "/videos"


def test_sidecar_never_collides_with_the_companion_csv():
    # The companion is <stem>.csv and IS the experimental record; the sidecar
    # must never resolve to it.
    video = "/videos/v.avi"
    assert onset_csv.path_for(video).name != "v.csv"


def test_sweep_frames_are_written_one_based():
    # Sweeps index frames 0-based; the companion CSV is 1-based and the sidecar
    # must match the companion so the two can be read side by side.
    b = onset_csv.Build()
    b.add_sweep([0, 5], [0.9, 0.2], threshold=0.5)
    rows = b.to_rows()
    assert [int(r["frame_number"]) for r in rows] == [1, 6]
    assert rows[0]["pellet_present"] == 1
    assert rows[1]["pellet_present"] == 0


def test_signals_from_different_stages_merge_on_one_row():
    b = onset_csv.Build()
    b.add_sweep([10], [0.8], threshold=0.5)
    b.add_scores([10], [0.77])
    b.add_masks([{"frame": 10, "score": 0.91}])
    b.add_note(11, "start-success-candidate")
    row = b.to_rows()[0]
    assert row["frame_number"] == 11
    assert row["pellet_ncc"] == "0.8000"
    assert row["dino_sim"] == "0.7700"
    assert row["sam_score"] == "0.910"
    assert row["note"] == "start-success-candidate"


def test_timestamp_follows_fps():
    b = onset_csv.Build(fps=200.0)
    b.add_sweep([199], [0.5], threshold=0.9)
    assert b.to_rows()[0]["timestamp"] == "1.0000"


def test_windows_only_mark_frames_that_already_have_rows():
    # Marking every armed frame would multiply the file with nothing new to say
    # about frames the sweep never scored.
    b = onset_csv.Build()
    b.add_sweep([100, 105], [0.9, 0.9], threshold=0.5)
    w = intervals.build_windows(
        [Trial(outcome_frame=300, outcome="s")],
        [intervals.Interval(0, 300)], min_candidates=1)
    b.add_windows(w)
    assert len(b.to_rows()) == 2
    assert all(r["armed"] == 1 for r in b.to_rows())


def test_sensor_edges_create_rows_even_without_a_sweep_sample():
    b = onset_csv.Build()
    b.add_sensor_edges([42])
    row = b.to_rows()[0]
    assert row["frame_number"] == 42 and row["sensor_edge"] == 1


def test_round_trip_through_disk(tmp_path):
    video = tmp_path / "v.avi"
    video.write_bytes(b"")
    b = onset_csv.Build()
    b.add_sweep([0, 5, 10], [0.9, 0.3, 0.85], threshold=0.5)
    b.add_note(6, "start-failure-candidate")
    out = onset_csv.write(video, b)
    assert out.is_file()
    rows = onset_csv.read(video)
    assert len(rows) == 3
    assert rows[1]["note"] == "start-failure-candidate"
    assert list(rows[0].keys()) == onset_csv.COLUMNS


def test_write_is_atomic_and_leaves_no_temp(tmp_path):
    video = tmp_path / "v.avi"
    video.write_bytes(b"")
    b = onset_csv.Build()
    b.add_sweep([0], [0.5], threshold=0.4)
    onset_csv.write(video, b)
    assert not list(tmp_path.glob("*.tmp"))


def test_reading_a_missing_sidecar_is_empty_not_an_error(tmp_path):
    assert onset_csv.read(tmp_path / "absent.avi") == []


def test_summarise_counts_each_signal(tmp_path):
    b = onset_csv.Build()
    b.add_sweep([0, 5, 10], [0.9, 0.2, 0.9], threshold=0.5)
    b.add_sensor_edges([3])
    b.add_scores([10], [0.7])
    b.add_masks([{"frame": 10, "score": 0.8}])
    b.add_note(11, "start-success-candidate")
    s = onset_csv.summarise(b.to_rows())
    assert s["rows"] == 4 and s["sensor_edges"] == 1
    assert s["scored"] == 1 and s["masked"] == 1 and s["notes"] == 1


def test_status_column_is_copied_from_the_companion():
    # frame_line_status carries the hardware reach sensor; losing it would hide
    # the single best bracketing signal in the whole pipeline.
    b = onset_csv.Build()
    b.add_sweep([0], [0.9], threshold=0.5)
    b.add_status([(1, 14)])
    assert b.to_rows()[0]["frame_line_status"] == "14"


def test_status_reaches_rows_created_by_notes_and_edges():
    """add_status only fills existing rows, so it must run after every other
    stage — otherwise the tagged rows, where the sensor column matters most,
    come out blank."""
    b = onset_csv.Build()
    b.add_sweep([0], [0.9], threshold=0.5)     # creates frame 1
    b.add_note(500, "start-success")           # off the stride grid
    b.add_sensor_edges([700])
    b.add_status([(1, 10), (500, 14), (700, 14)])
    got = {int(r["frame_number"]): r["frame_line_status"] for r in b.to_rows()}
    assert got == {1: "10", 500: "14", 700: "14"}


# ── marks: the box and pellet labels live in the sidecar ────────────────────

def test_mark_columns_exist():
    for col in ("mark_kind", "mark_cam", "mark_x", "mark_y"):
        assert col in onset_csv.COLUMNS


def test_box_mark_round_trips(tmp_path):
    video = tmp_path / "v.avi"; video.write_bytes(b"")
    b = onset_csv.Build()
    b.add_mark(120, "box", "cam0", 411.5, 402.25)
    onset_csv.write(video, b)
    rows = onset_csv.read(video)
    assert len(rows) == 1
    r = rows[0]
    assert r["mark_kind"] == "box" and r["mark_cam"] == "cam0"
    assert float(r["mark_x"]) == 411.5 and float(r["mark_y"]) == 402.25
    assert int(r["frame_number"]) == 120


def test_marks_read_back_as_structs(tmp_path):
    video = tmp_path / "v.avi"; video.write_bytes(b"")
    b = onset_csv.Build()
    b.add_mark(100, "box", "cam0", 411, 402)
    b.add_mark(100, "pellet", "cam0", 411, 402)
    b.add_mark(250, "pellet", "cam0", 415, 403)
    onset_csv.write(video, b)
    marks = onset_csv.read_marks(video)
    assert len(marks) == 3
    assert sum(1 for m in marks if m["kind"] == "box") == 1
    assert {m["frame"] for m in marks} == {100, 250}


def test_box_centre_for_camera(tmp_path):
    video = tmp_path / "v.avi"; video.write_bytes(b"")
    b = onset_csv.Build()
    b.add_mark(100, "box", "cam0", 411, 402)
    onset_csv.write(video, b)
    marks = onset_csv.read_marks(video)
    assert onset_csv.box_centre(marks, "cam0") == (411.0, 402.0)
    # the other camera is unplaced -- None, never a guess
    assert onset_csv.box_centre(marks, "cam1") is None


def test_a_box_and_a_pellet_on_one_frame_stay_separate_rows(tmp_path):
    # They describe the same point but mean different things; collapsing them
    # would lose the pellet from the template pool.
    video = tmp_path / "v.avi"; video.write_bytes(b"")
    b = onset_csv.Build()
    b.add_mark(100, "box", "cam0", 411, 402)
    b.add_mark(100, "pellet", "cam0", 411, 402)
    assert len(onset_csv.read_marks_from_rows(b.to_rows())) == 2


def test_marks_do_not_disturb_the_sweep_columns(tmp_path):
    video = tmp_path / "v.avi"; video.write_bytes(b"")
    b = onset_csv.Build()
    b.add_sweep([0, 5], [0.9, 0.2], threshold=0.5)
    b.add_mark(100, "box", "cam1", 590, 450)
    rows = b.to_rows()
    swept = [r for r in rows if r["pellet_ncc"] != ""]
    assert len(swept) == 2
    assert all(r["mark_kind"] == "" for r in swept)


def test_row_from_csv_round_trips_a_swept_row(tmp_path):
    video = tmp_path / "v.avi"; video.write_bytes(b"")
    b = onset_csv.Build()
    b.add_sweep([0], [0.87], threshold=0.5)
    b.add_sensor_edges([1])
    b.add_note(1, "start-success")
    onset_csv.write(video, b)
    back = onset_csv.Build()
    for r in onset_csv.read(video):
        back.rows[int(float(r["frame_number"]))] = onset_csv.row_from_csv(r)
    out = back.to_rows()[0]
    assert out["pellet_ncc"] == "0.8700" and out["sensor_edge"] == 1
    assert out["note"] == "start-success"


def test_saving_marks_preserves_the_sweep(tmp_path):
    """A placement must not wipe the trace, the edges or the tags."""
    video = tmp_path / "v.avi"; video.write_bytes(b"")
    b = onset_csv.Build()
    b.add_sweep([0, 5], [0.9, 0.2], threshold=0.5)
    b.add_note(1, "start-failure")
    onset_csv.write(video, b)

    merged = onset_csv.Build()
    for r in onset_csv.read(video):
        if str(r.get("mark_kind") or "").strip():
            continue
        merged.rows[int(float(r["frame_number"]))] = onset_csv.row_from_csv(r)
    merged.add_mark(100, "box", "cam0", 411, 402)
    onset_csv.write(video, merged)

    rows = onset_csv.read(video)
    assert any(r["pellet_ncc"] == "0.9000" for r in rows)
    assert any(r["note"] == "start-failure" for r in rows)
    assert len(onset_csv.read_marks(video)) == 1


# ── rebuilding must not destroy what a human placed ─────────────────────────

def test_rebuilding_the_sidecar_preserves_existing_marks(tmp_path):
    """"Build onset CSV" rewrites the file from the pipeline's signals, none of
    which include the box. Without carrying the marks over it deletes the
    placement, and sweeping blocks again with "place the pellet box first".

    Latent until 2026-08-12: the endpoint had been answering 409 for an
    unrelated reason, so nobody could reach the rewrite.
    """
    dest = tmp_path / "vid_onset.csv"
    first = onset_csv.Build()
    first.add_mark(1, onset_csv.MARK_BOX, "cam0", 369.5, 339.94)
    first.add_mark(1, onset_csv.MARK_PELLET, "cam0", 369.5, 339.94)
    first.add_mark(1, onset_csv.MARK_BOX, "cam1", 522.0, 396.94)
    onset_csv.write("/v/vid.avi", first, dest=dest)

    rebuilt = onset_csv.Build()
    rebuilt.add_note(500, "s")
    onset_csv.carry_marks(rebuilt, onset_csv.read_marks("/v/vid.avi", dest))
    onset_csv.write("/v/vid.avi", rebuilt, dest=dest)

    marks = onset_csv.read_marks("/v/vid.avi", dest)
    assert len(marks) == 3
    assert onset_csv.box_centre(marks, "cam0") == (369.5, 339.94)
    assert onset_csv.box_centre(marks, "cam1") == (522.0, 396.94)
    assert len(onset_csv.pellet_marks(marks, "cam0")) == 1


def test_carrying_marks_into_an_empty_build_is_a_no_op(tmp_path):
    build = onset_csv.Build()
    onset_csv.carry_marks(build, [])
    assert build.to_rows() == []


def test_carried_marks_survive_alongside_a_full_trace(tmp_path):
    """The marks must not be dropped by rows keyed on the same frame."""
    dest = tmp_path / "v_onset.csv"
    build = onset_csv.Build()
    build.add_sweep([0, 5, 10], [0.9, 0.8, 0.2], 0.5)     # rows at frames 1,6,11
    onset_csv.carry_marks(build, [{"frame": 1, "kind": "box", "cam": "cam0",
                                   "x": 10.0, "y": 20.0}])
    onset_csv.write("/v/v.avi", build, dest=dest)
    rows = onset_csv.read("/v/v.avi", dest)
    assert onset_csv.box_centre(onset_csv.read_marks_from_rows(rows), "cam0") == (10.0, 20.0)
    assert any(str(r.get("pellet_ncc") or "").strip() for r in rows)


# ── two-camera signals ──────────────────────────────────────────────────────
#
# The sidecar documents every signal used to decide an onset. It carried one
# camera's NCC, so a wrong armed decision could not be diagnosed from the file:
# frame 27591 read "pellet_ncc 0.64, present 1" with no way to see that cam1
# disagreed and the 3D point was 8.29 away.

def test_pair_sweep_records_both_cameras_and_the_distance(tmp_path):
    import numpy as np
    dest = tmp_path / "v_onset.csv"
    build = onset_csv.Build()
    # 1-based frame_numbers, as the pipeline now hands out: the sweep's 0-based
    # video indices are converted once, at the pipeline boundary.
    build.add_pair_sweep([1, 6], np.array([0.90, 0.55]), np.array([0.88, 0.67]),
                         np.array([0.48, 8.29]), np.array([True, False]))
    onset_csv.write("/v/v.avi", build, dest=dest)
    rows = {int(float(r["frame_number"])): r for r in onset_csv.read("/v/v.avi", dest)}
    assert float(rows[1]["pellet_ncc"]) == 0.90
    assert float(rows[1]["pellet_ncc_cam1"]) == 0.88
    assert float(rows[1]["pellet_dist3d"]) == 0.48
    assert rows[1]["pellet_present"] == "1"
    # the rejected sample keeps its evidence rather than being dropped
    assert float(rows[6]["pellet_dist3d"]) == 8.29
    assert rows[6]["pellet_present"] == "0"


def test_a_nan_distance_is_written_blank_not_as_a_number(tmp_path):
    """NaN means the cameras never agreed so nothing was triangulated. Writing
    it as 0.0 would read as a perfect 3D match."""
    import numpy as np
    dest = tmp_path / "v_onset.csv"
    build = onset_csv.Build()
    build.add_pair_sweep([1], np.array([0.1]), np.array([0.1]),
                         np.array([np.nan]), np.array([False]))
    onset_csv.write("/v/v.avi", build, dest=dest)
    row = onset_csv.read("/v/v.avi", dest)[0]
    assert str(row["pellet_dist3d"]).strip() == ""


def test_the_new_columns_are_in_the_header(tmp_path):
    dest = tmp_path / "v_onset.csv"
    onset_csv.write("/v/v.avi", onset_csv.Build(), dest=dest)
    header = dest.read_text().splitlines()[0]
    assert "pellet_ncc_cam1" in header and "pellet_dist3d" in header

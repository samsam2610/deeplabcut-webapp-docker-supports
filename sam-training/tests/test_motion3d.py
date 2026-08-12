"""The 3D motion sidecar.

Tidy long format so a new marker or a new segmenter is new ROWS, never a schema
change. The merge is the part that has to be right: re-running SAM must replace
its own rows and leave a DLC or manual row for the same frame untouched, or the
file quietly becomes the last writer's opinion instead of an accumulation.
"""
import math

import pytest

from src import motion3d as m3


def _row(frame, source="sam3", marker="paw_centroid", **kw):
    d = dict(frame=frame, source=source, marker=marker,
             cam0_x=1.0, cam0_y=2.0, cam1_x=3.0, cam1_y=4.0,
             X=5.0, Y=6.0, Z=7.0, epi_px=1.5, score=0.9)
    d.update(kw)
    return m3.Row(**d)


def test_round_trips(tmp_path):
    dest = tmp_path / "v_motion3d.csv"
    m3.write("/v/v.avi", [_row(100)], dest=dest)
    got = m3.read("/v/v.avi", dest)
    assert len(got) == 1
    assert int(float(got[0]["frame"])) == 100
    assert got[0]["marker"] == "paw_centroid"


def test_the_sidecar_sits_beside_the_video():
    assert m3.path_for("/d/banh_cam0.avi").name == "banh_cam0_motion3d.csv"


def test_rerunning_replaces_only_its_own_rows(tmp_path):
    dest = tmp_path / "v_motion3d.csv"
    m3.write("/v/v.avi", [_row(100, score=0.5)], dest=dest)
    m3.merge("/v/v.avi", [_row(100, score=0.95)], dest=dest)
    got = m3.read("/v/v.avi", dest)
    assert len(got) == 1, "same (frame, source, marker) is a correction"
    assert float(got[0]["score"]) == 0.95


def test_a_foreign_source_survives_a_rerun(tmp_path):
    """The whole point of `source`: adding SAM rows must not delete DLC ones."""
    dest = tmp_path / "v_motion3d.csv"
    m3.write("/v/v.avi", [_row(100, source="dlc", score=0.99)], dest=dest)
    m3.merge("/v/v.avi", [_row(100, source="sam3")], dest=dest)
    got = {(r["source"], r["marker"]): r for r in m3.read("/v/v.avi", dest)}
    assert set(got) == {("dlc", "paw_centroid"), ("sam3", "paw_centroid")}
    assert float(got[("dlc", "paw_centroid")]["score"]) == 0.99


def test_a_new_marker_is_new_rows_not_a_schema_change(tmp_path):
    dest = tmp_path / "v_motion3d.csv"
    m3.write("/v/v.avi", [_row(100, marker="paw_centroid")], dest=dest)
    before = dest.read_text().splitlines()[0]
    m3.merge("/v/v.avi", [_row(100, marker="wrist")], dest=dest)
    assert dest.read_text().splitlines()[0] == before, "header must not change"
    assert len(m3.read("/v/v.avi", dest)) == 2


def test_rows_come_back_in_frame_order(tmp_path):
    dest = tmp_path / "v_motion3d.csv"
    m3.merge("/v/v.avi", [_row(300), _row(100), _row(200)], dest=dest)
    got = [int(float(r["frame"])) for r in m3.read("/v/v.avi", dest)]
    assert got == [100, 200, 300]


def test_merging_into_a_missing_file_just_writes_it(tmp_path):
    dest = tmp_path / "v_motion3d.csv"
    m3.merge("/v/v.avi", [_row(100)], dest=dest)
    assert dest.is_file() and len(m3.read("/v/v.avi", dest)) == 1


def test_reading_a_missing_file_is_empty_not_an_error(tmp_path):
    assert m3.read("/v/nope.avi", tmp_path / "nope_motion3d.csv") == []


def test_a_rejected_frame_is_written_with_its_evidence(tmp_path):
    """Rejections are recorded, not dropped. When a frame that should have been
    kept was not, its epi_px is the only thing that explains why."""
    dest = tmp_path / "v_motion3d.csv"
    m3.merge("/v/v.avi", [_row(100, epi_px=48.2, X=None, Y=None, Z=None)],
             dest=dest)
    r = m3.read("/v/v.avi", dest)[0]
    assert float(r["epi_px"]) == 48.2
    assert r["X"].strip() == "", "no 3D point when the pair was rejected"


def test_a_nan_is_written_blank_rather_than_as_a_number(tmp_path):
    dest = tmp_path / "v_motion3d.csv"
    m3.merge("/v/v.avi", [_row(100, epi_px=math.nan)], dest=dest)
    assert m3.read("/v/v.avi", dest)[0]["epi_px"].strip() == ""


def test_a_partial_write_cannot_leave_a_half_file(tmp_path):
    dest = tmp_path / "v_motion3d.csv"
    m3.merge("/v/v.avi", [_row(i) for i in range(50)], dest=dest)
    assert not list(tmp_path.glob("*.tmp"))
    assert len(m3.read("/v/v.avi", dest)) == 50


def test_a_corrupt_file_does_not_take_the_new_rows_down_with_it(tmp_path):
    """A merge must still land: losing this run because an old file is damaged
    would be the worst possible trade."""
    dest = tmp_path / "v_motion3d.csv"
    dest.write_text("this is not a csv with the right header\n\x00\x01")
    m3.merge("/v/v.avi", [_row(100)], dest=dest)
    got = m3.read("/v/v.avi", dest)
    assert len(got) == 1 and int(float(got[0]["frame"])) == 100

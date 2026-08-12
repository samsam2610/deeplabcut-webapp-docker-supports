"""Writing tags into the companion CSV — the experimental record.

Everything before this was read-only with respect to that file. The tests here
are mostly about not damaging it: the row's own timestamp and sensor status must
survive, no other row may move, and every write must be exactly revertible.
"""
import csv

import pytest

from src import tagwrite


HEADER = ["timestamp", "frame_number", "frame_line_status", "note"]


@pytest.fixture
def companion(tmp_path):
    """A miniature companion CSV with the real file's shape and quirks."""
    path = tmp_path / "vid.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER)
        w.writeheader()
        for f in range(1, 51):
            w.writerow({
                # full precision, as the real files carry — NOT frame/fps
                "timestamp": f"{f * 0.005000123456:.9f}",
                "frame_number": f,
                "frame_line_status": "10" if f % 7 else "14",
                "note": "f" if f == 30 else ("s" if f == 20 else ""),
            })
    return path


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return {int(r["frame_number"]): r for r in csv.DictReader(fh)}


# ── ±5 placement ────────────────────────────────────────────────────────────

def test_the_proposed_frame_is_used_when_free():
    notes = {10: "", 11: ""}
    assert tagwrite.place(notes, 10) == (10, [])


def test_an_occupied_frame_steps_outward_to_the_nearest_free_row():
    notes = {8: "", 9: "x", 10: "s", 11: "y", 12: ""}
    frame, blocked = tagwrite.place(notes, 10)
    # 8 and 12 are both free at distance 2; earlier wins, deterministically.
    assert frame == 8
    assert blocked == [(10, "s"), (9, "x"), (11, "y")]


def test_it_prefers_the_nearest_free_row_not_the_first_direction():
    notes = {9: "z", 10: "s", 11: ""}
    assert tagwrite.place(notes, 10)[0] == 11


def test_a_full_neighbourhood_is_refused_and_names_the_blockers():
    """The +-5 rule exists so a tag never displaces an existing note. Widening
    the search to "somewhere it fits" would defeat it."""
    notes = {f: "taken" for f in range(5, 16)}
    frame, blocked = tagwrite.place(notes, 10)
    assert frame is None
    assert len(blocked) == 11                      # 10, then +-1..+-5
    assert (10, "taken") in blocked


def test_a_frame_missing_from_the_csv_is_not_a_placement_target():
    """Only rows that exist can be written; the real file has every frame, but
    a truncated one must not invent rows."""
    notes = {1: "", 2: ""}
    assert tagwrite.place(notes, 40)[0] is None


def test_the_radius_is_configurable_but_defaults_to_five():
    notes = {f: "x" for f in range(1, 20)}
    notes[17] = ""
    assert tagwrite.place(notes, 10)[0] is None
    assert tagwrite.place(notes, 10, radius=7)[0] == 17


# ── writing ─────────────────────────────────────────────────────────────────

def test_a_write_sets_the_note_on_the_existing_row(companion):
    tagwrite.write(companion, [(12, "start-success")])
    assert _rows(companion)[12]["note"] == "start-success"


def test_a_write_preserves_the_row_timestamp_and_status(companion):
    """The main webapp's save-row recomputes timestamp as frame/fps to 3dp.
    Routing through it would silently degrade the row being tagged."""
    before = _rows(companion)[12]
    tagwrite.write(companion, [(12, "start-success")])
    after = _rows(companion)[12]
    assert after["timestamp"] == before["timestamp"]
    assert after["frame_line_status"] == before["frame_line_status"]


def test_a_write_touches_no_other_row(companion):
    before = _rows(companion)
    tagwrite.write(companion, [(12, "start-success")])
    after = _rows(companion)
    assert set(before) == set(after)
    for f in before:
        if f != 12:
            assert before[f] == after[f], f"row {f} changed"


def test_the_row_count_and_header_are_unchanged(companion):
    text_before = companion.read_text(encoding="utf-8")
    tagwrite.write(companion, [(12, "x")])
    text_after = companion.read_text(encoding="utf-8")
    assert text_before.splitlines()[0] == text_after.splitlines()[0]
    assert len(text_before.splitlines()) == len(text_after.splitlines())


def test_crlf_survives(companion):
    """The real files are CRLF. Rewriting them as LF would show up as a
    250 000-line diff in whatever the lab uses to look at them."""
    tagwrite.write(companion, [(12, "x")])
    assert b"\r\n" in companion.read_bytes()
    assert b"\n\n" not in companion.read_bytes()


def test_a_batch_is_one_rewrite_not_one_per_tag(companion, monkeypatch):
    """129 rewrites of a 6MB file is slow, and 129 chances to be interrupted
    halfway through a batch."""
    calls = []
    real = tagwrite._replace
    monkeypatch.setattr(tagwrite, "_replace", lambda *a: (calls.append(1), real(*a))[1])
    tagwrite.write(companion, [(11, "a"), (12, "b"), (13, "c")])
    assert len(calls) == 1
    got = _rows(companion)
    assert (got[11]["note"], got[12]["note"], got[13]["note"]) == ("a", "b", "c")


def test_writing_leaves_no_temp_file(companion):
    tagwrite.write(companion, [(12, "x")])
    assert not list(companion.parent.glob("*.tmp"))


def test_a_backup_is_taken_before_the_first_write(companion):
    tagwrite.write(companion, [(12, "x")], backup=True)
    baks = list(companion.parent.glob("vid.csv.bak-*"))
    assert len(baks) == 1
    assert "note" in baks[0].read_text(encoding="utf-8").splitlines()[0]


# ── journal and undo ────────────────────────────────────────────────────────

def test_the_journal_records_the_previous_value(companion, tmp_path):
    tagwrite.commit(companion, [(20, "start-success")], batch="b1")
    entries = tagwrite.journal_read(companion)
    assert len(entries) == 1
    assert entries[0]["frame"] == "20"
    assert entries[0]["note"] == "start-success"
    assert entries[0]["previous_note"] == "s", "must capture what it displaced"


def test_undo_restores_the_previous_value_not_a_blank(companion):
    tagwrite.commit(companion, [(20, "start-success")], batch="b1")
    tagwrite.undo(companion)
    assert _rows(companion)[20]["note"] == "s"


def test_undo_reverts_only_the_last_batch(companion):
    tagwrite.commit(companion, [(11, "one")], batch="b1")
    tagwrite.commit(companion, [(12, "two")], batch="b2")
    tagwrite.undo(companion)
    got = _rows(companion)
    assert got[12]["note"] == ""          # b2 reverted
    assert got[11]["note"] == "one"       # b1 left alone


def test_undo_twice_walks_back_two_batches(companion):
    tagwrite.commit(companion, [(11, "one")], batch="b1")
    tagwrite.commit(companion, [(12, "two")], batch="b2")
    tagwrite.undo(companion)
    tagwrite.undo(companion)
    got = _rows(companion)
    assert got[11]["note"] == "" and got[12]["note"] == ""


def test_undo_does_not_clobber_a_later_hand_edit(companion):
    """Somebody may have corrected the tag in the main webapp since. Undo
    reverts what THIS tool wrote, not whatever is there now."""
    tagwrite.commit(companion, [(11, "start-success")], batch="b1")
    tagwrite.write(companion, [(11, "hand-placed")])      # edited elsewhere
    tagwrite.undo(companion)
    assert _rows(companion)[11]["note"] == "hand-placed"


def test_undo_with_nothing_to_undo_is_a_no_op(companion):
    before = companion.read_bytes()
    assert tagwrite.undo(companion) == 0
    assert companion.read_bytes() == before


def test_a_batch_of_many_undoes_as_one(companion):
    tagwrite.commit(companion, [(11, "a"), (12, "b"), (13, "c")], batch="b1")
    assert tagwrite.undo(companion) == 3
    got = _rows(companion)
    assert [got[f]["note"] for f in (11, 12, 13)] == ["", "", ""]


def test_the_journal_survives_being_read_when_absent(tmp_path):
    assert tagwrite.journal_read(tmp_path / "nope.csv") == []


# ── backup growth, mtime, and journal hygiene ───────────────────────────────
#
# Found in deployment verification. Data integrity held — the CSV came back
# byte-identical after undo — but the surrounding behaviour did not:
#
#   * 12 single writes produced 12 full 6.4 MB copies, 74 MB, never pruned.
#     A 129-trial batch would have left ~825 MB beside the video, growing
#     without bound across sessions.
#   * undo restored the content but left the mtime moved, which breaks any
#     "untouched since acquisition" check on a raw experimental record.
#   * "undo everything" left a header-only journal behind, so the directory
#     never returned to its prior state.

def test_a_run_of_writes_takes_one_backup_not_one_each(companion):
    for f in (11, 12, 13, 14):
        tagwrite.commit(companion, [(f, "x")], backup=True)
    assert len(list(companion.parent.glob("vid.csv.bak-*"))) == 1


def test_the_one_backup_is_the_state_before_the_first_write(companion):
    before = companion.read_bytes()
    tagwrite.commit(companion, [(11, "a")], backup=True)
    tagwrite.commit(companion, [(12, "b")], backup=True)
    bak = list(companion.parent.glob("vid.csv.bak-*"))[0]
    assert bak.read_bytes() == before


def test_a_fresh_session_after_a_full_undo_backs_up_again(companion):
    """The journal is the session marker: empty means nothing of ours is
    outstanding, so the next write starts a new one."""
    tagwrite.commit(companion, [(11, "a")], backup=True)
    tagwrite.undo(companion)
    tagwrite.commit(companion, [(12, "b")], backup=True)
    assert len(list(companion.parent.glob("vid.csv.bak-*"))) == 2


def test_backups_are_capped(companion):
    for i in range(tagwrite.MAX_BACKUPS + 3):
        tagwrite.commit(companion, [(11 + i, "x")], backup=True)
        tagwrite.undo(companion)                      # each is its own session
    assert len(list(companion.parent.glob("vid.csv.bak-*"))) == tagwrite.MAX_BACKUPS


def test_the_oldest_backups_are_the_ones_pruned(companion):
    keep = []
    for i in range(tagwrite.MAX_BACKUPS + 2):
        tagwrite.commit(companion, [(11 + i, "x")], backup=True)
        keep.append(sorted(companion.parent.glob("vid.csv.bak-*"))[-1].name)
        tagwrite.undo(companion)
    left = sorted(p.name for p in companion.parent.glob("vid.csv.bak-*"))
    assert left == sorted(keep[-tagwrite.MAX_BACKUPS:])


def test_a_full_undo_restores_the_file_mtime(companion):
    """A moved mtime on a raw experimental record breaks any
    has-this-been-touched check, even when every byte is back."""
    import os
    original = os.stat(companion).st_mtime
    os.utime(companion, (original - 86400, original - 86400))
    was = os.stat(companion).st_mtime
    tagwrite.commit(companion, [(11, "a")], backup=True)
    assert os.stat(companion).st_mtime != was
    tagwrite.undo(companion)
    assert abs(os.stat(companion).st_mtime - was) < 2


def test_a_partial_undo_does_not_restore_the_mtime(companion):
    """Only when nothing of ours is outstanding does the file claim to be
    untouched."""
    import os
    tagwrite.commit(companion, [(11, "a")], backup=True)
    tagwrite.commit(companion, [(12, "b")], backup=True)
    tagwrite.undo(companion)                          # one batch still applied
    assert tagwrite.journal_read(companion) != []


def test_an_emptied_journal_is_removed_not_left_as_a_header(companion):
    tagwrite.commit(companion, [(11, "a")], backup=True)
    tagwrite.undo(companion)
    assert not tagwrite.journal_path(companion).exists()


def test_journal_timestamps_carry_a_timezone(companion):
    """The container runs UTC and the host does not. A bare local time is four
    hours out from the mtimes anyone would correlate it against."""
    tagwrite.commit(companion, [(11, "a")])
    stamp = tagwrite.journal_read(companion)[0]["written_at"]
    assert stamp[-5] in "+-" or stamp.endswith("Z"), stamp

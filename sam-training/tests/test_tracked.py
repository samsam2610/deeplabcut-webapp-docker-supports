import sqlite3

from src import tracked


def build_db(tmp_path, rows, tracked_paths=None):
    """Minimal tracked_files.sqlite with the four tables the selector joins.

    ``rows`` is [(path, tag_label_or_None)]. ``tracked_paths`` defaults to every
    path, so a test can register a video WITHOUT tracking it.
    """
    db = tmp_path / tracked.DB_FILENAME
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        create table video (video_id text primary key, path text not null);
        create table tracked (video_id text primary key, tracked_at text);
        create table progress_segment (segment_id text primary key, name text);
        create table progress_option (option_id text primary key,
                                      segment_id text, label text);
        create table progress_value (video_id text, segment_id text,
                                     option_id text);
        insert into progress_segment values ('seg_tag', 'Tag');
        insert into progress_segment values ('seg_an', 'Analyze');
        insert into progress_option values ('opt_done', 'seg_tag', 'Done');
        insert into progress_option values ('opt_prog', 'seg_tag', 'In-progress');
        insert into progress_option values ('opt_an_done', 'seg_an', 'Done');
    """)
    if tracked_paths is None:
        tracked_paths = [p for p, _ in rows]
    for i, (path, tag) in enumerate(rows):
        vid = f"v{i}"
        conn.execute("insert into video values (?,?)", (vid, path))
        if path in tracked_paths:
            conn.execute("insert into tracked values (?,?)", (vid, "now"))
        if tag == "Done":
            conn.execute("insert into progress_value values (?,?,?)",
                         (vid, "seg_tag", "opt_done"))
        elif tag == "In-progress":
            conn.execute("insert into progress_value values (?,?,?)",
                         (vid, "seg_tag", "opt_prog"))
        # An Analyze value on every video: the selector must not confuse
        # segments, which a naive join happily does.
        conn.execute("insert into progress_value values (?,?,?)",
                     (vid, "seg_an", "opt_an_done"))
    conn.commit()
    conn.close()
    return tmp_path


def test_selects_only_tag_done(tmp_path):
    p = build_db(tmp_path, [("/a.avi", "Done"), ("/b.avi", "In-progress"),
                            ("/c.avi", None), ("/d.avi", "Done")])
    assert sorted(tracked.tag_done_videos(p)) == ["/a.avi", "/d.avi"]


def test_pending_is_everything_else(tmp_path):
    p = build_db(tmp_path, [("/a.avi", "Done"), ("/b.avi", "In-progress"),
                            ("/c.avi", None)])
    assert sorted(tracked.tag_pending_videos(p)) == ["/b.avi", "/c.avi"]


def test_registered_but_untracked_video_is_excluded(tmp_path):
    # The real project has 13 registered against 12 tracked; the extra is a
    # near-duplicate that would double-count trials inside a CV fold.
    p = build_db(tmp_path,
                 [("/tracked.avi", "Done"), ("/dupe.avi", "Done")],
                 tracked_paths=["/tracked.avi"])
    assert tracked.tag_done_videos(p) == ["/tracked.avi"]


def test_does_not_read_a_label_from_the_wrong_segment(tmp_path):
    # Every video has Analyze=Done; none of them may be reported Tag=Done.
    p = build_db(tmp_path, [("/a.avi", None)])
    assert tracked.tag_done_videos(p) == []


def test_missing_database_is_empty_not_an_error(tmp_path):
    assert tracked.tag_done_videos(tmp_path) == []
    assert tracked.segment_labels(tmp_path) == {}

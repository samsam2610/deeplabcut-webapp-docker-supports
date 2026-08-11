"""Dataset selection from the project's ``tracked_files.sqlite``.

The working set is NOT "every video in videos/" — it is the tracked files whose
``Tag`` progress segment is ``Done``. Getting this wrong silently pulls in
untagged videos and registered-but-untracked duplicates; see the spec's
"Dataset selector" section for the two traps this avoids.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_FILENAME = "tracked_files.sqlite"

# One row per tracked video with its label for each progress segment.
_PROGRESS_SQL = """
select v.path,
       max(case when s.name = ? then o.label end) as segment_label
from tracked t
join video v on v.video_id = t.video_id
left join progress_value   pv on pv.video_id   = t.video_id
left join progress_segment s  on s.segment_id  = pv.segment_id
left join progress_option  o  on o.option_id   = pv.option_id
group by v.video_id
order by v.path
"""


def db_path(project_path) -> Path:
    return Path(project_path) / DB_FILENAME


def segment_labels(project_path, segment: str = "Tag") -> dict[str, str | None]:
    """Map ``video path -> that video's label for <segment>`` (None when unset).

    Only tracked videos are returned. The ``video`` table on its own is a
    registry of files ever seen, not the working set — in DREADD-Ali it holds 13
    rows against 12 tracked, the extra being an untracked near-duplicate.
    """
    path = db_path(project_path)
    if not path.is_file():
        return {}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {row[0]: row[1] for row in conn.execute(_PROGRESS_SQL, (segment,))}
    finally:
        conn.close()


def tag_done_videos(project_path) -> list[str]:
    """Tracked videos whose ``Tag`` segment is ``Done`` — the training set."""
    return [p for p, label in segment_labels(project_path, "Tag").items()
            if label == "Done"]


def tag_pending_videos(project_path) -> list[str]:
    """Tracked videos whose ``Tag`` segment is anything but ``Done``.

    These are the targets: the tool's whole purpose is to propose onsets for
    the outcome markers they already carry.
    """
    return [p for p, label in segment_labels(project_path, "Tag").items()
            if label != "Done"]

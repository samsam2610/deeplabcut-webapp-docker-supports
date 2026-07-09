"""Guards for the statusNoteTimeline active-tag accessors.

Added so the inline-3D card can preserve the user's active status/note tag filters
across a post-analysis same-video reload (loadCsv otherwise clears them). The
accessors are inert plumbing — other consumers are unaffected unless they call them.

See docs/superpowers/specs/2026-07-09-inline-3d-postanalysis-state-design.md.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "static" / "components" / "viewer" / "features" / "status_notes.js"


def _src():
    assert SRC.is_file(), f"missing {SRC}"
    return SRC.read_text()


def test_exposes_get_and_set_active_tags():
    s = _src()
    assert re.search(r"\bgetActiveTags\s*\(", s), "must expose getActiveTags()"
    assert re.search(r"\bsetActiveTags\s*\(", s), "must expose setActiveTags()"


def test_get_active_tags_returns_status_and_note_arrays():
    s = _src()
    assert re.search(r"getActiveTags\s*\(\s*\)\s*{[^}]*activeStatus[^}]*activeNote", s, re.S), (
        "getActiveTags must return both active sets"
    )


def test_set_active_tags_prunes_to_existing_values():
    s = _src()
    # Restored values must be filtered against the current color maps so stale tags
    # (removed by the CSV reload) are dropped rather than re-added.
    assert "in statusColors" in s and "in noteColors" in s, "setActiveTags must prune to existing values"

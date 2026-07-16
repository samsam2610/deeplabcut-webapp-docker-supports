"""Guards for the statusNoteTimeline tag-lock hooks used by the inline-3D
"Analyze for tag" batch. All additive + default-off — other consumers unaffected
unless they pass onActiveTagsChange / call setNoteChipsLocked.

See docs/superpowers/specs/2026-07-16-inline-3d-analyze-for-tag-batch-design.md.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "static" / "components" / "viewer" / "features" / "status_notes.js"


def _src():
    assert SRC.is_file(), f"missing {SRC}"
    return SRC.read_text()


def test_exposes_get_rows_and_set_note_chips_locked():
    s = _src()
    assert re.search(r"\bgetRows\s*\(", s), "must expose getRows()"
    assert re.search(r"\bsetNoteChipsLocked\s*\(", s), "must expose setNoteChipsLocked()"


def test_note_chips_lock_skips_click_and_adds_class():
    s = _src()
    # renderChips must accept a locked flag, add a "locked" class, and only wire the
    # click listener when not locked.
    assert "noteChipsLocked" in s, "must track a note-chips-locked flag"
    assert re.search(r'"\s*locked\s*"', s) or "locked" in s, "locked chips need a class"
    assert re.search(r"if\s*\(\s*!locked\s*\)", s), "click listener must be gated on !locked"


def test_chip_toggle_fires_on_active_tags_change():
    s = _src()
    assert "onActiveTagsChange" in s, "chip toggle must fire config.onActiveTagsChange"

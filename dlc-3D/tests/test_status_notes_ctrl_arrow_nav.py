"""Guards for the Ctrl+Arrow timeline-nav shortcut in statusNoteTimeline.

Ctrl+Arrow (physical Ctrl on Mac + Windows) repeats a jump on the last-used timeline
(status vs note, set when its ◀▶ button is clicked). It is a capture-phase handler so
it pre-empts the viewer's Ctrl+Arrow skip; when no timeline is active it falls through
to that skip. Skip remains available on Shift+Arrow (controls.mjs, unchanged).

See docs/superpowers/specs/2026-07-09-timeline-nav-arrows-and-ctrl-shortcut-design.md.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "static" / "components" / "viewer" / "features" / "status_notes.js"


def _src():
    assert SRC.is_file(), f"missing {SRC}"
    return SRC.read_text()


def test_last_nav_recorded_via_doNav_on_button_clicks():
    s = _src()
    assert "lastNav" in s, "must track the last-used timeline"
    assert re.search(r"function\s+doNav\s*\(", s), "must route nav-button clicks through doNav"
    assert re.search(r"lastNav\s*=\s*\{\s*field\s*,\s*activeSet\s*\}", s), "doNav must record { field, activeSet }"
    # all four ◀▶ buttons go through doNav (not the bare nav())
    assert len(re.findall(r"addEventListener\(\s*[\"']click[\"']\s*,\s*\(\)\s*=>\s*doNav\(", s)) >= 4, \
        "status/note prev+next buttons must call doNav"


def test_ctrl_arrow_handler_guards_and_suppresses_skip():
    s = _src()
    assert re.search(r"function\s+onCtrlArrowKey\s*\(", s), "must define the Ctrl+Arrow handler"
    assert "e.ctrlKey" in s, "must key on the physical Ctrl (not metaKey)"
    assert '"ArrowLeft"' in s and '"ArrowRight"' in s, "must handle both arrow keys"
    # fall-through guards: no active timeline, empty filter, or hidden/inactive bar
    assert re.search(r"lastNav\.activeSet\.size\s*===\s*0", s), "must fall through when the filter is empty"
    assert "offsetParent === null" in s, "must fall through when the bar/card isn't visible"
    # when it acts it suppresses the viewer's skip
    assert "stopImmediatePropagation()" in s, "must suppress the viewer's Ctrl+Arrow skip"
    assert re.search(r"nav\(\s*lastNav\.field", s), "must navigate the last-used timeline"


def test_ctrl_arrow_registered_capture_phase_with_teardown_signal():
    s = _src()
    assert re.search(
        r'addEventListener\(\s*["\']keydown["\']\s*,\s*onCtrlArrowKey\s*,\s*\{\s*capture:\s*true\s*,\s*signal:\s*ac\.signal\s*\}',
        s,
    ), "handler must be capture-phase and torn down via the abort signal"

"""Static guards for the inline-3D Triangulate-keyframe-range controller wiring (Phase 2).

See docs/superpowers/specs/2026-07-20-inline-3d-triangulate-keyframe-range-design.md.
The Triangulate-range button POSTs the current finalize keyframe window to
/dlc/project/triangulate/range, polls /dlc/project/triangulate/range/status until
terminal, then refetches /dlc/project/triangulate/coverage to draw the 3D bar.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.js"


def _js():
    return JS.read_text()


def test_range_button_wired_in_triangulate_chrome():
    s = _js()
    assert re.search(r'ia3d-triangulate-range-btn"\)', s), \
        "the triangulate range button must be referenced/wired"


def test_posts_to_triangulate_range_endpoint():
    s = _js()
    assert "/dlc/project/triangulate/range" in s, \
        "handler must POST to /dlc/project/triangulate/range"


def test_polls_triangulate_range_status():
    s = _js()
    assert "/dlc/project/triangulate/range/status" in s, \
        "handler must poll /dlc/project/triangulate/range/status"
    # terminal states per the contract
    assert "SUCCESS" in s and "FAILURE" in s, \
        "poll must resolve on the contract's terminal states (SUCCESS/FAILURE)"


def test_fetches_triangulate_coverage():
    s = _js()
    assert "/dlc/project/triangulate/coverage" in s, \
        "after success must fetch /dlc/project/triangulate/coverage"


def test_range_read_from_keyframe_window():
    s = _js()
    # reuse the same range source as the confined analyze button: _finalizeKW.getRange()
    assert "_finalizeKW" in s and "getRange()" in s, \
        "range must come from the finalize keyframe window (_finalizeKW.getRange)"


def test_range_button_gated_on_lock_like_confined():
    s = _js()
    # toggled in the same place/condition as #ia3d-btn-analyze-range-confined
    assert "ia3d-triangulate-range-btn" in s
    gate = s[s.index("function _refreshAnalyzeEnablement"):
             s.index("function _refreshAnalyzeEnablement") + 1200]
    assert "ia3d-triangulate-range-btn" in gate and "rangeOk" in gate, \
        "range button disabled state must be gated by rangeOk in _refreshAnalyzeEnablement"


def test_triangulate_coverage_bar_seekable_and_playhead_synced():
    """The 3D coverage bar must be click/drag-seekable and redraw its playhead on
    frameChange + resize, exactly like the sibling seek/finalize bars — otherwise
    it isn't clickable, doesn't sync, and its cursor never moves."""
    s = _js()
    assert "_wireSeekCanvas(triCoverageCanvas" in s, \
        "3D coverage canvas must be passed to _wireSeekCanvas (click/drag seek)"
    # defined once + called from a frameChange handler + called on resize
    assert s.count("_redrawTriangulateCoverage") >= 3, \
        "need a _redrawTriangulateCoverage fn wired to frameChange + resize (playhead sync)"
    assert "() => _redrawTriangulateCoverage())" in s, \
        "_redrawTriangulateCoverage must be called from a viewer frameChange handler"
    assert '"ia3d-finalize-coverage", "ia3d-triangulate-coverage"' in s, \
        "3D coverage canvas must be in the _applyTimelineWidth resize/zoom id list"

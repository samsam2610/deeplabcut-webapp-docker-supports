"""Static guards for the Tracked Files wiring in inline_analysis_3d.js.

Also guards the bug this feature depends on fixing: _iaOpenBrowseVideo used to
swallow a video-info error and open an EMPTY viewer at fps 30 / 0 frames, so a
tracked file that had moved looked like a broken player instead of an error.

See docs/superpowers/specs/2026-07-31-tracked-files-design.md.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.js"


def _src():
    assert JS.is_file(), f"missing {JS}"
    return JS.read_text()


def _fn(name):
    """Return the source of a top-level `async function name(...)` body."""
    s = _src()
    m = re.search(rf"^(?:async )?function {name}\(", s, re.M)
    assert m, f"missing function {name}"
    nxt = re.search(r"^(?:async )?function ", s[m.end():], re.M)
    return s[m.start(): m.end() + (nxt.start() if nxt else len(s))]


def test_imports_and_constructs_the_tracked_files_factory():
    s = _src()
    assert 'from "/static/js/components/tracked_files_tab.js"' in s
    assert "makeTrackedFiles(" in s


def test_factory_is_constructed_in_the_launcher_wiring():
    assert "makeTrackedFiles(" in _fn("_wireLauncher")


def test_open_browse_video_reports_current_path_to_the_tracker():
    body = _fn("_iaOpenBrowseVideo")
    assert re.search(r"_trackedFiles\?\.setCurrent\(\s*absPath\s*\)", body), \
        "_iaOpenBrowseVideo must call _trackedFiles?.setCurrent(absPath)"


def test_reset_clears_the_tracker_so_the_checkbox_hides_in_other_modes():
    body = _fn("_resetForOpen")
    assert re.search(r"_trackedFiles\?\.setCurrent\(\s*null\s*\)", body), \
        "_resetForOpen must call _trackedFiles?.setCurrent(null)"


def test_open_browse_video_aborts_on_a_video_info_error():
    """Regression: the old bare `catch { _fps = 30; _frameCount = 0; }` fallback
    silently opened an empty viewer for a missing file. Do not re-introduce it."""
    body = _fn("_iaOpenBrowseVideo")
    assert "res.ok" in body or "response.ok" in body, "must check the HTTP status"
    assert re.search(r"info\.error|data\.error", body), "must check the JSON error field"
    assert "return" in body, "must abort the open"
    assert not re.search(r"catch\s*\([^)]*\)\s*\{\s*_fps\s*=\s*30", body), \
        "the silent fps-30 fallback must be gone"


def test_open_browse_video_reveals_the_player_only_after_info_resolves():
    body = _fn("_iaOpenBrowseVideo")
    assert body.index("annotate/video-info") < body.index("ia3d-player-section"), \
        "video-info must resolve before the player section is revealed"


def test_launcher_error_helper_targets_the_launcher_error_element():
    s = _src()
    assert "_iaLauncherError" in s
    assert "ia3d-launcher-error" in s

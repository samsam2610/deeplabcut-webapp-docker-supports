"""Static guards for the Tracked Files markup in the 3D Inline Analysis card.

See docs/superpowers/specs/2026-07-31-tracked-files-design.md.
"""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1]
        / "src" / "templates" / "partials" / "card_inline_analysis_3d.html")


def _src():
    assert HTML.is_file(), f"missing {HTML}"
    return HTML.read_text()


def test_third_source_tab_exists_after_browse_folders():
    s = _src()
    assert 'id="ia3d-tab-tracked"' in s
    assert "Tracked Files" in s
    # Order matters: Project Content, Browse Folders, Tracked Files.
    assert s.index('id="ia3d-tab-project"') < s.index('id="ia3d-tab-browse"') < s.index('id="ia3d-tab-tracked"')


def test_tracked_panel_and_list_container_exist_and_start_hidden():
    s = _src()
    m = re.search(r'<div id="ia3d-tab-tracked-panel"[^>]*class="([^"]*)"', s)
    assert m, "missing #ia3d-tab-tracked-panel"
    assert "hidden" in m.group(1), "tracked panel must start hidden"
    assert 'id="ia3d-tracked-list"' in s


def test_launcher_error_line_exists_outside_the_player_section():
    """The open-failure message must live in the launcher — the player section
    is never shown when an open aborts."""
    s = _src()
    assert 'id="ia3d-launcher-error"' in s
    assert s.index('id="ia3d-launcher-error"') < s.index('id="ia3d-player-section"')


def test_track_checkbox_precedes_the_selected_name_in_the_player_header():
    s = _src()
    assert 'id="ia3d-track-checkbox"' in s
    assert s.index('id="ia3d-track-checkbox"') < s.index('id="ia3d-selected-name"')


def test_track_checkbox_starts_hidden():
    """Visible only in browse-video mode; JS reveals it via setCurrent()."""
    s = _src()
    m = re.search(r'<label id="ia3d-track-label"[^>]*class="([^"]*)"', s)
    assert m, "missing #ia3d-track-label wrapper"
    assert "hidden" in m.group(1)

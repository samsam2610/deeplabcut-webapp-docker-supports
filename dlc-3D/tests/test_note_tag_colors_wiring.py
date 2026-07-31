"""Static-analysis guards for the per-project NOTE-tag colour overrides,
consumer side (both inline-3D cards). Library-side contract is covered by
tests/test_status_notes_tag_colors.py; the pure hash/sort helpers are
node-tested in tests/unit/test_viewer_tag_colors.mjs.

Both cards share the SAME ui-setting key (`note_tag_colors`, no per-card
suffix — deliberately, per pinned_snapshot's precedent) so a colour picked on
one card shows on the other. This file checks each card:
  - defines the shared key literal "note_tag_colors" (not a _reproj variant)
  - loads it (GET) and saves it (POST) via /dlc/project/ui-setting
  - passes it into statusNoteTimeline's `tagColors` config
  - is covered by the ui-setting whitelist guard (test_reproj_ui_setting_whitelist.py
    already asserts this dynamically for the reprojection card from the JS source;
    this file adds the static "key literal is exactly note_tag_colors" checks and
    covers BOTH cards, since that whitelist test only reads one file).
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
IA3D = ROOT / "src" / "static" / "inline_analysis_3d.js"
IA3DR = ROOT / "src" / "static" / "inline_analysis_3d_reprojection.js"
INLINE_ANALYSIS_PY = ROOT.parent.parent / "deeplabcut-webapp-docker" / "src" / "dlc" / "inline_analysis.py"


def _src(p):
    assert p.is_file(), f"missing {p}"
    return p.read_text()


CARDS = [
    ("inline_analysis_3d.js", IA3D, "IA3D_NOTE_TAG_COLORS_KEY"),
    ("inline_analysis_3d_reprojection.js", IA3DR, "IA3DR_NOTE_TAG_COLORS_KEY"),
]


def test_both_cards_declare_the_shared_key_literal():
    for name, path, const_name in CARDS:
        s = _src(path)
        assert re.search(rf'const\s+{const_name}\s*=\s*"note_tag_colors"\s*;', s), \
            f'{name} must declare `const {const_name} = "note_tag_colors";` — the key is ' \
            "deliberately shared (no per-card suffix) so a colour set on one card shows on the other"


def test_both_cards_get_and_post_the_key():
    for name, path, const_name in CARDS:
        s = _src(path)
        assert re.search(rf"ui-setting\?key=\$\{{{const_name}\}}", s), \
            f"{name} must GET /dlc/project/ui-setting?key=${{{const_name}}}"
        assert re.search(rf"JSON\.stringify\(\{{\s*key:\s*{const_name}\b", s), \
            f"{name} must POST /dlc/project/ui-setting with key: {const_name}"


def test_both_cards_wire_tagColors_into_statusNoteTimeline():
    for name, path, _ in CARDS:
        s = _src(path)
        assert re.search(r"tagColors:\s*\{\s*overrides:\s*_noteTagColorOverrides", s), \
            f"{name} must pass tagColors.overrides into statusNoteTimeline"
        assert re.search(r"onColorChange:\s*\(\)\s*=>\s*_saveNoteTagColors\(\)", s), \
            f"{name} must wire tagColors.onColorChange to persist"


def test_both_cards_load_overrides_and_refresh_timeline():
    for name, path, _ in CARDS:
        s = _src(path)
        assert "async function _loadNoteTagColors" in s, f"{name} must define _loadNoteTagColors"
        assert "_snTimeline?.refreshTagColors()" in s, \
            f"{name} must force a repaint via refreshTagColors() after loading overrides"
        assert "_loadNoteTagColors();" in s, \
            f"{name} must actually call _loadNoteTagColors() (e.g. from _loadAllQuickTags)"


def test_both_cards_save_is_debounced_and_best_effort():
    for name, path, const_name in CARDS:
        s = _src(path)
        i = s.index("function _saveNoteTagColors")
        window = s[i:i + 700]
        assert "setTimeout" in window, f"{name}'s _saveNoteTagColors must debounce"
        assert ".catch(() => {})" in window or ".catch(()=>{})" in window, \
            f"{name}'s _saveNoteTagColors POST must be best-effort (swallow failures)"


def test_main_webapp_whitelists_note_tag_colors():
    if not INLINE_ANALYSIS_PY.is_file():
        import pytest
        pytest.skip("main webapp checkout not present beside this repo")
    py_src = INLINE_ANALYSIS_PY.read_text()
    m = re.search(r"_UI_SETTING_KEYS\s*=\s*\{([^}]*)\}", py_src, re.S)
    assert m, "could not locate _UI_SETTING_KEYS in inline_analysis.py"
    whitelist = set(re.findall(r'"([\w]+)"', m.group(1)))
    assert "note_tag_colors" in whitelist, \
        "note_tag_colors must be in _UI_SETTING_KEYS or every GET/POST for it 400s and nothing persists"

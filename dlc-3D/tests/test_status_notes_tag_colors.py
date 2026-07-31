"""Static-analysis contract for per-tag NOTE color overrides in the
StatusNoteTimeline feature (status_notes.js), backed by the pure helpers in
internal/tag_colors.mjs (node-tested separately: tests/unit/test_viewer_tag_colors.mjs).

Requirements this guards (see docs/superpowers/note-tag-colors-report.md):
1. Stable default colour per tag name (tagColor: pure hash, no storage).
2. User can override any individual tag's colour via a control on its chip.
3. Overrides persist per project (consumer-owned; this file only checks the
   library-side contract — see test_note_tag_colors_wiring.py for the cards).
4. Chip ordering: overridden tags first, then alphabetical (sortTags).
5. statusNoteTimeline called WITHOUT tagColors must behave exactly as before.
6. Malformed colours never reach chip.style.setProperty raw.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SN = ROOT / "src" / "static" / "components" / "viewer" / "features" / "status_notes.js"
TAG_COLORS_MJS = ROOT / "src" / "static" / "components" / "viewer" / "internal" / "tag_colors.mjs"


def _src():
    assert SN.is_file(), f"missing {SN}"
    return SN.read_text()


def test_tag_colors_mjs_exists_and_exports_pure_helpers():
    assert TAG_COLORS_MJS.is_file(), f"missing {TAG_COLORS_MJS}"
    src = TAG_COLORS_MJS.read_text()
    for name in ("tagColor", "sortTags", "isValidHexColor"):
        assert re.search(rf"\bexport\s+function\s+{name}\b", src), f"tag_colors.mjs must export `{name}`"


def test_tag_colors_mjs_is_dom_and_storage_free():
    src = TAG_COLORS_MJS.read_text()
    for bad in ("document.", "window.", "localStorage", "fetch(", "Math.random", "new Date", "Date.now"):
        assert bad not in src, f"tag_colors.mjs must stay pure/DOM-free (found {bad!r})"


def test_status_notes_imports_tag_color_helpers():
    s = _src()
    for name in ("tagColor", "sortTags", "isValidHexColor"):
        assert re.search(
            rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*tag_colors\.mjs[\"']", s,
        ), f"status_notes.js must import {name} from internal/tag_colors.mjs"


def test_recolor_branches_on_tagColorsCfg_and_preserves_legacy_else():
    s = _src()
    assert "tagColorsCfg" in s, "must track an optional tagColors config"
    # The legacy (tagColors-absent) path must be byte-identical to the original
    # implementation — same call, same args — so existing consumers are unaffected.
    assert re.search(
        r'noteColors\s*=\s*assignColors\(uniqueValues\(rows,\s*"note"\),\s*notePalette\)', s,
    ), "the tagColors-absent branch must still call the original assignColors(uniqueValues(rows,\"note\"), notePalette)"
    assert re.search(r"if\s*\(\s*tagColorsCfg\s*\)", s), "recolor must branch on tagColorsCfg"


def test_recolor_uses_sortTags_and_tagColor_when_configured():
    s = _src()
    assert re.search(r"sortTags\(\s*uniqueValues\(rows,\s*\"note\"\)", s), \
        "the tagColors-configured branch must order note tags via sortTags"
    assert re.search(r"tagColor\(\s*t,\s*notePalette\s*\)", s), \
        "the tagColors-configured branch must fall back to the deterministic tagColor default"


def test_invalid_override_falls_back_via_isValidHexColor():
    s = _src()
    # Both the color-map build (recolor) and the chip paint (renderChips) must
    # guard through isValidHexColor before trusting a color value.
    assert s.count("isValidHexColor(") >= 2, \
        "isValidHexColor must gate both applying a stored override and painting a chip"


def test_chip_gets_a_color_control_when_tag_colors_configured():
    s = _src()
    assert 'input.type = "color"' in s or "input.type = 'color'" in s or \
        re.search(r'\.type\s*=\s*"color"', s), "a per-chip color <input type=color> control must be created"
    assert "vv-tag-color-input" in s, "the color control needs a stable class for CSS + click-guarding"


def test_color_input_never_toggles_chip_active_state():
    s = _src()
    i = s.index("vv-tag-color-input")
    # The click handler on the color input itself must stop propagation so it
    # doesn't also fire the chip's own click->toggle-active listener.
    window = s[i:i + 800]
    assert "stopPropagation" in window, \
        "the color input's click must not bubble into the chip's active-toggle handler"


def test_color_input_change_updates_overrides_and_fires_callback():
    s = _src()
    i = s.index("vv-tag-color-input")
    window = s[i:i + 1200]
    assert "tagColorsCfg.overrides" in window, "picking a color must update the shared overrides object"
    assert "tagColorsCfg.onColorChange" in window, "picking a color must notify the consumer via onColorChange"
    assert "recolor()" in window and "rebuildChips()" in window, \
        "picking a color must repaint (recolor + rebuildChips) immediately"


def test_exposes_refreshTagColors_public_method():
    s = _src()
    assert re.search(r"\brefreshTagColors\s*\(\s*\)\s*\{", s), \
        "factory result must expose refreshTagColors() so consumers can force a repaint " \
        "after an async load of overrides resolves"


def test_status_chips_never_get_a_color_control():
    s = _src()
    # renderChips(els.statusChips, ...) call must NOT pass tagColorsCfg-derived palette.
    m = re.search(r"renderChips\(els\.statusChips,\s*statusColors,\s*activeStatus,\s*false,\s*([^)]*)\)", s)
    assert m, "must find the statusChips renderChips call"
    assert m.group(1).strip() == "null", \
        f"status chips must never render a color control (got colorControlPalette arg {m.group(1)!r})"

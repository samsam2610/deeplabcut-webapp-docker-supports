"""The clone must not share ids, CSS classes or globals with the original card.

Both cards live in the same document. Any shared id means one card's queries
return the other card's nodes.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parent.parent / "src" / "static"
CARD = STATIC / "card_inline_analysis_3d_reprojection.html"
JS = STATIC / "inline_analysis_3d_reprojection.js"
CSS = STATIC / "inline_analysis_3d_reprojection.css"

ORIGINAL_CARD = (
    Path(__file__).parent.parent / "src" / "templates" / "partials"
    / "card_inline_analysis_3d.html"
)
ORIGINAL_JS = STATIC / "inline_analysis_3d.js"


@pytest.fixture(scope="module")
def clone_texts():
    for p in (CARD, JS, CSS):
        assert p.is_file(), "missing clone artifact: {}".format(p)
    return {p.name: p.read_text() for p in (CARD, JS, CSS)}


def test_no_bare_ia3d_identifier_survives(clone_texts):
    """`ia3d-` must be gone everywhere; `ia3dr-` is the clone's namespace."""
    for name, text in clone_texts.items():
        leaked = re.findall(r"\bia3d-[a-z0-9-]+", text)
        assert not leaked, "{} still references original ids: {}".format(
            name, sorted(set(leaked))[:10]
        )


def test_clone_uses_its_own_namespace(clone_texts):
    assert "ia3dr-" in clone_texts[CARD.name]
    assert "ia3dr-" in clone_texts[JS.name]
    assert "ia3dr-" in clone_texts[CSS.name]


def test_card_root_and_buttons_are_renamed(clone_texts):
    card = clone_texts[CARD.name]
    assert 'id="inline-analysis-3d-reprojection-card"' in card
    assert 'id="inline-analysis-3d-card"' not in card
    assert 'id="btn-close-inline-analysis-3d"' not in card


def test_js_does_not_clobber_the_original_viewer_global(clone_texts):
    js = clone_texts[JS.name]
    assert "__iaViewerReproj" in js
    assert re.search(r'"__iaViewer"', js) is None


def test_js_identifiers_are_renamed(clone_texts):
    js = clone_texts[JS.name]
    assert not re.search(r"\b_ia3d[A-Z]", js), "un-renamed _ia3dXxx identifier"


def test_clone_ids_are_disjoint_from_the_original_card(clone_texts):
    ids = lambda t: set(re.findall(r'id="([^"]+)"', t))
    shared = ids(clone_texts[CARD.name]) & ids(ORIGINAL_CARD.read_text())
    assert not shared, "ids shared with the original card: {}".format(
        sorted(shared)[:10]
    )


def test_clone_does_not_import_a_copied_viewer_library(clone_texts):
    """The shared viewer library must be imported, never cloned."""
    js = clone_texts[JS.name]
    assert "./components/viewer/video_viewer.js" in js
    assert not (STATIC / "components_reproj").exists()


def test_server_routes_were_not_renamed(clone_texts):
    """The rename must not touch fetch URLs — they are server contracts."""
    js = clone_texts[JS.name]
    for url in (
        "/dlc/project/inline-analysis/range",
        "/dlc/project/snapshots",
        "/dlc-3d/sibling-camera",
    ):
        assert url in js, "rename damaged the URL {}".format(url)
    assert "ia3dr" not in "".join(re.findall(r'fetch\(\s*[`"\']([^`"\']*)', js))


UI_SETTING_KEYS = (
    "pose3d_bg_color", "pose3d_view_prefs", "finalize_window",
    "clip_window", "postfix_tags", "status_tags", "note_tags",
)


def test_ui_setting_keys_are_namespaced(clone_texts):
    """Per-project ui-setting keys are shared storage; un-suffixed keys would
    make the two cards silently edit the same setting."""
    js = clone_texts[JS.name]
    for key in UI_SETTING_KEYS:
        assert key + "_reproj" in js, "{} not namespaced".format(key)
        assert not re.search(r'"{}"'.format(key), js), (
            '"{}" still used un-suffixed'.format(key)
        )


def test_clone_never_stops_an_inline_analysis_session(clone_texts):
    """snap_key is shared, so a stop from this card can kill the original
    card's warm session. Sessions expire via their own ttl_seconds instead."""
    assert "inline-analysis/session/stop" not in clone_texts[JS.name]


def test_clone_still_starts_its_own_session(clone_texts):
    assert "inline-analysis/session/start" in clone_texts[JS.name]

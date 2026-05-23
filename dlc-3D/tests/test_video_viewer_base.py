"""Static-analysis contract for the VideoViewer base class (Phase 2b).

The browser ESM component cannot be imported under Node (a `.js` file with no
package.json `type:module` is parsed as CommonJS), so — like file_browser.js — its
contract is enforced by regex over source plus code review. These checks catch a
future refactor that drops a reducer import, a public method, or a hook event.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
VV = ROOT / "src" / "static" / "components" / "viewer" / "video_viewer.js"


def _src():
    assert VV.is_file(), f"missing VideoViewer at {VV}"
    return VV.read_text()


def test_exists_and_exports_class():
    assert re.search(r"export\s+class\s+VideoViewer\b", _src()), \
        "video_viewer.js must export `class VideoViewer`"


@pytest.mark.parametrize("name,module", [
    ("makeEventBus", "event_bus"),
    ("planTiles", "tile_layout"),
    ("planSeek", "seek_plan"),
    ("fitViewerSize", "fit_viewer"),
    ("resolveKey", "controls"),
])
def test_imports_reducer(name, module):
    src = _src()
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*{module}\.mjs[\"']", src), \
        f"VideoViewer must import {name} from internal/{module}.mjs (no re-implementation)"


@pytest.mark.parametrize("method", [
    "load", "seek", "step", "play", "pause", "use", "on", "destroy",
    "setTileWeight", "equalizeTiles",
])
def test_public_method_present(method):
    assert re.search(rf"\b{method}\s*\(", _src()), f"VideoViewer must define `{method}(`"


def test_per_tile_sizing_sets_flex_grow():
    src = _src()
    assert "flexGrow" in src, \
        "VideoViewer must drive per-tile sizing via flex-grow (setWeight sets rootEl.style.flexGrow)"


@pytest.mark.parametrize("event", ["videoLoad", "frameChange", "drawTile", "teardown"])
def test_hook_event_emitted(event):
    src = _src()
    assert f'"{event}"' in src or f"'{event}'" in src, f'VideoViewer must emit the "{event}" hook event'


def test_keydown_passes_shift_and_handles_playdir():
    src = (ROOT / "src" / "static" / "components" / "viewer" / "video_viewer.js").read_text()
    assert "shiftKey: e.shiftKey" in src, "keydown must pass shiftKey to resolveKey"
    assert 'intent.type === "playPauseDir"' in src, "base must handle playPauseDir intent"
    assert "setPlayDir(1)" in src, "Space must set forward direction before toggling"

def test_load_autofocuses_mount():
    src = (ROOT / "src" / "static" / "components" / "viewer" / "video_viewer.js").read_text()
    assert "this.mount.focus" in src, "load() must auto-focus the mount so keyboard works without a click"

def test_keyboard_target_configurable():
    src = (ROOT / "src" / "static" / "components" / "viewer" / "video_viewer.js").read_text()
    assert "keyboardTarget" in src, "VideoViewer must accept a keyboardTarget config"
    assert "this._keyboardTarget" in src, "keyboard listener must use the configurable target"
    assert "this._keyboardTarget.addEventListener" in src, "keydown must attach to the configurable target"
    assert "this._keyboardTarget.removeEventListener" in src, "destroy must detach from the configurable target"

"""Static-analysis contract for the MarkerEditor feature module (Phase 3d-ii).

Browser ESM cannot import under Node; enforced by regex over source + code review.
The pure overlay/edit math is node-tested separately (test_viewer_marker_overlay.mjs).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
ME = ROOT / "src" / "static" / "components" / "viewer" / "features" / "marker_editor.js"


def _src():
    assert ME.is_file(), f"missing marker_editor feature at {ME}"
    return ME.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+markerEditor\b", _src()) or \
        re.search(r"export\s*\{[^}]*\bmarkerEditor\b[^}]*\}", _src()), \
        "must export `markerEditor`"


def test_returns_attach():
    assert re.search(r"\battach\s*\(", _src()), "factory result must expose `attach(viewer)`"


@pytest.mark.parametrize("name", [
    "hitTest", "resolvePose", "setEdit", "deleteEdit", "buildMarkerEditPayload",
    "layerThreshold", "poseCacheKey", "prefetchWindow", "allCached", "nudge",
    "nextBodypart", "scaleFor", "markerRadius", "canvasToVideo",
])
def test_imports_overlay_reducer(name):
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*marker_overlay\.mjs[\"']", _src()), \
        f"must import {name} from internal/marker_overlay.mjs (no re-implementation)"


def test_imports_palette_and_shapes():
    src = _src()
    assert re.search(r"import\s*\{[^}]*\bpaletteColor\b[^}]*\}\s*from\s*[\"'][^\"']*palette\.mjs[\"']", src), \
        "must import paletteColor from internal/palette.mjs"
    assert re.search(r"import\s*\{[^}]*\b(drawShape|shapeForLayer)\b[^}]*\}\s*from\s*[\"'][^\"']*shapes\.mjs[\"']", src), \
        "must import draw helpers from internal/shapes.mjs"


@pytest.mark.parametrize("event", ["videoLoad", "frameChange", "drawTile"])
def test_subscribes_hook(event):
    src = _src()
    assert f'"{event}"' in src or f"'{event}'" in src, f'must subscribe to the "{event}" hook'


def test_gates_editing_on_single_layer():
    # editing must be disabled when comparison layers are present
    assert re.search(r"isEditable", _src()), "must gate editing via an isEditable() check"


def test_disposes_on_teardown():
    src = _src()
    assert '"teardown"' in src or "'teardown'" in src, "must subscribe to the viewer 'teardown' hook"


def test_no_hardcoded_endpoints():
    src = _src()
    for bad in ("/dlc-3d/", "/clip-cutter/", "/annotate/", "/dlc/viewer/"):
        assert bad not in src, f"endpoints must be injected, not hardcoded ({bad})"

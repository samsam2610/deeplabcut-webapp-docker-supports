"""Static-analysis contract for the StatusNoteTimeline feature module (Phase 3a).

Browser ESM cannot import under Node; like file_browser.js / video_viewer.js it is
enforced by regex over source + code review. The pure CSV logic it builds on is
node-tested separately (test_viewer_csv_annotations.mjs).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SN = ROOT / "src" / "static" / "components" / "viewer" / "features" / "status_notes.js"


def _src():
    assert SN.is_file(), f"missing status_notes feature at {SN}"
    return SN.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+statusNoteTimeline\b", _src()) or \
        re.search(r"export\s*\{[^}]*\bstatusNoteTimeline\b[^}]*\}", _src()), \
        "must export `statusNoteTimeline`"


def test_returns_attach():
    assert re.search(r"\battach\s*\(", _src()), "factory result must expose `attach(viewer)`"


@pytest.mark.parametrize("name", [
    "uniqueValues", "assignColors", "findMatchingFrame", "rowForFrame",
    "isInterestingAnnotation", "applySavedRow", "buildSaveRowPayload",
])
def test_imports_reducer(name):
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*csv_annotations\.mjs[\"']", _src()), \
        f"must import {name} from internal/csv_annotations.mjs (no re-implementation)"


@pytest.mark.parametrize("event", ["videoLoad", "frameChange"])
def test_subscribes_hook(event):
    src = _src()
    assert f'"{event}"' in src or f"'{event}'" in src, f'must subscribe to the "{event}" hook'


def test_navigates_via_viewer_seek():
    assert re.search(r"\.seek\s*\(", _src()), "prev/next nav must call viewer.seek(...)"


def test_timeline_click_to_seek():
    src = _src()
    assert 'addEventListener("click"' in src or "addEventListener('click'" in src, \
        "timeline canvases must be wired for click-to-seek"


def test_no_hardcoded_endpoints():
    src = _src()
    for bad in ("/dlc-3d/", "/clip-cutter/", "/annotate/"):
        assert bad not in src, f"endpoints must be injected, not hardcoded ({bad})"

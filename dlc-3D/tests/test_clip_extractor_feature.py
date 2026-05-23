"""Static-analysis contract for the ClipExtractor feature module (Phase 3c).

Browser ESM cannot import under Node; enforced by regex over source + code review.
The pure request/tag logic is node-tested separately (test_viewer_clip_extract.mjs).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
CE = ROOT / "src" / "static" / "components" / "viewer" / "features" / "clip_extractor.js"


def _src():
    assert CE.is_file(), f"missing clip_extractor feature at {CE}"
    return CE.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+clipExtractor\b", _src()) or \
        re.search(r"export\s*\{[^}]*\bclipExtractor\b[^}]*\}", _src()), \
        "must export `clipExtractor`"


def test_returns_attach():
    assert re.search(r"\battach\s*\(", _src()), "factory result must expose `attach(viewer)`"


@pytest.mark.parametrize("name,module", [
    ("buildExtractRequest", "clip_extract"),
    ("buildRenameRequest", "clip_extract"),
    ("buildDeleteRequest", "clip_extract"),
    ("buildOverlapRequest", "clip_extract"),
    ("addTag", "clip_extract"),
    ("removeTagAt", "clip_extract"),
    ("computeEnd", "clip_naming"),
])
def test_imports_reducer(name, module):
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*{module}\.mjs[\"']", _src()), \
        f"must import {name} from internal/{module}.mjs (no re-implementation)"


def test_disposes_on_teardown():
    src = _src()
    assert '"teardown"' in src or "'teardown'" in src, "must subscribe to the viewer 'teardown' hook"


def test_storage_key_namespaced_by_prefix():
    # the postfix-tags localStorage key must derive from storagePrefix, not be a literal
    assert re.search(r"storagePrefix", _src()), "postfix-tag storage key must use storagePrefix"


def test_no_hardcoded_endpoints():
    src = _src()
    for bad in ("/dlc-3d/", "/clip-cutter/", "/annotate/"):
        assert bad not in src, f"endpoints must be injected, not hardcoded ({bad})"

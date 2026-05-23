"""Static-analysis contract for the FrameExtractor feature module (Phase 3b).

Browser ESM cannot import under Node; like the other viewer .js modules it is enforced
by regex over source + code review. The pure batch/payload logic is node-tested
separately (test_viewer_frame_extract.mjs).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FE = ROOT / "src" / "static" / "components" / "viewer" / "features" / "frame_extractor.js"


def _src():
    assert FE.is_file(), f"missing frame_extractor feature at {FE}"
    return FE.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+frameExtractor\b", _src()) or \
        re.search(r"export\s*\{[^}]*\bframeExtractor\b[^}]*\}", _src()), \
        "must export `frameExtractor`"


def test_returns_attach():
    assert re.search(r"\battach\s*\(", _src()), "factory result must expose `attach(viewer)`"


@pytest.mark.parametrize("name", ["parseBatchCount", "parseBatchStep", "planBatch", "buildSaveFramePayload"])
def test_imports_reducer(name):
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*frame_extract\.mjs[\"']", _src()), \
        f"must import {name} from internal/frame_extract.mjs (no re-implementation)"


def test_reads_viewer_state():
    src = _src()
    for accessor in ("currentFrame", "videoPath", "frameCount"):
        assert re.search(rf"\.{accessor}\s*\(", src), f"must read viewer.{accessor}()"


def test_disposes_on_teardown():
    src = _src()
    assert '"teardown"' in src or "'teardown'" in src, "must subscribe to the viewer 'teardown' hook"


def test_no_hardcoded_endpoints():
    src = _src()
    for bad in ("/dlc-3d/", "/clip-cutter/", "/annotate/"):
        assert bad not in src, f"endpoints must be injected, not hardcoded ({bad})"

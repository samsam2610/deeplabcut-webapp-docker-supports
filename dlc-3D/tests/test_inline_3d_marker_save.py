"""Static guards for the marker-save race fix: Save sends in-memory edits in the
request body instead of relying on the async marker-edit mirror. See the backend
fix in deeplabcut-webapp-docker viewer.save-marker-edits (_resolve_edits_to_apply).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "src" / "static" / "inline_analysis_3d.js"
EDITOR = ROOT / "src" / "static" / "components" / "viewer" / "features" / "marker_editor.js"
OVERLAY = ROOT / "src" / "static" / "components" / "viewer" / "internal" / "marker_overlay.mjs"


def test_overlay_exports_serializer():
    assert re.search(r"export function serializeEditsForSave\(", OVERLAY.read_text()), \
        "marker_overlay.mjs must export serializeEditsForSave"


def test_marker_editor_exposes_get_edits_for_save():
    src = EDITOR.read_text()
    assert "serializeEditsForSave" in src, "marker_editor must import serializeEditsForSave"
    assert re.search(r"getEditsForSave:\s*\(cam\)\s*=>\s*serializeEditsForSave\(", src), \
        "marker_editor must expose getEditsForSave(cam)"


def test_save_sends_edits_in_body():
    js = JS.read_text()
    assert re.search(r"getEditsForSave\(cam\)", js), \
        "_iaSaveAdjustments must send each cam's in-memory edits"
    assert re.search(r"body:\s*JSON\.stringify\(\{\s*h5,\s*edits:", js), \
        "save-marker-edits body must include edits"


def test_save_treats_zero_frames_as_failure():
    js = JS.read_text()
    assert re.search(r"!data\.frames_edited", js), \
        "a 0-frames_edited response (nothing written) must count as a save failure"


def test_save_invalidates_poses_on_success():
    js = JS.read_text()
    # after a successful save the h5 changed in place; re-render from it so the
    # edit doesn't visually snap back on a camera switch.
    assert re.search(r"if \(!anyErr\) _markerEditor\.invalidatePoses\(\)", js), \
        "successful save must invalidate the pose cache so the saved edit renders"

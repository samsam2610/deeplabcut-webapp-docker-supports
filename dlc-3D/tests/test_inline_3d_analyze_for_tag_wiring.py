"""Static guards for the inline-3D Analyze-for-tag controller wiring.

See docs/superpowers/specs/2026-07-16-inline-3d-analyze-for-tag-batch-design.md.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.js"


def _js():
    return JS.read_text()


def test_imports_tag_batch_helpers():
    s = _js()
    assert re.search(r'import\s*\{[^}]*tagKeyframes[^}]*mergeWindows[^}]*\}\s*from\s*"[^"]*tag_batch\.mjs"', s), \
        "must import tagKeyframes + mergeWindows from tag_batch.mjs"


def test_snTimeline_wires_on_active_tags_change():
    s = _js()
    assert "onActiveTagsChange" in s and "_refreshTagLockEnablement" in s, \
        "statusNoteTimeline must call _refreshTagLockEnablement on tag change"


def test_tag_lock_enablement_requires_exactly_one_note():
    s = _js()
    # enable iff exactly one active note tag
    assert re.search(r"getActiveTags\(\)\.note", s), "must read active note tags"
    assert re.search(r"\.length\s*===\s*1", s), "tag-lock enabled only when exactly one note tag active"


def test_tag_lock_change_freezes_chips():
    s = _js()
    assert re.search(r'ia3d-tag-lock"\)\?\.addEventListener\("change"', s), "tag-lock change must be wired"
    assert "setNoteChipsLocked" in s, "tag-lock change must freeze/unfreeze note chips"


def test_analyze_for_tag_button_wired_and_gated():
    s = _js()
    assert re.search(r'ia3d-btn-analyze-tag"\)\?\.addEventListener\("click",\s*_onAnalyzeTagClick', s), \
        "Analyze-for-tag button must be wired to _onAnalyzeTagClick"
    # gate mirrors for-range: finalize on && tag-lock checked && sibling
    assert re.search(r'ia3d-btn-analyze-tag"\)[\s\S]{0,200}finOn\s*&&\s*tagLocked\s*&&\s*hasSibling', s) or \
           re.search(r'tagLocked\s*&&\s*hasSibling', s), "tag button gated on finalize+tagLock+sibling"


def test_analyze_for_tag_builds_and_submits_merged_ranges():
    s = _js()
    assert "_onAnalyzeTagClick" in s, "must define _onAnalyzeTagClick"
    assert re.search(r"tagKeyframes\(", s) and re.search(r"mergeWindows\(", s), \
        "batch must build ranges via tagKeyframes + mergeWindows"
    assert "window.confirm" in s, "batch must confirm before dispatching"
    # dual-cam submit per range reusing _submitRange
    assert s.count("_submitRange(") >= 4, "batch must submit both cams (in addition to the two existing callers)"


def test_iaback_resets_tag_lock():
    s = _js()
    back = s[s.index("function _iaBack()"): s.index("function _iaBack()") + 800]
    assert "ia3d-tag-lock" in back, "_iaBack must reset the tag-lock checkbox"

"""Static guards for the "Triangulate all for tag" button (#ia3d-btn-triangulate-tag)
and its _onTriangulateTagClick handler.

See docs/superpowers/specs/2026-07-22-inline-3d-ui-rearrangements-design.md (feature 2).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
JS = ROOT / "src" / "static" / "inline_analysis_3d.js"


def test_triangulate_tag_button_present_above_hint():
    html = CARD.read_text()
    btn = html.find('id="ia3d-btn-triangulate-tag"')
    assert btn >= 0, "missing #ia3d-btn-triangulate-tag"
    hint = html.find('id="ia3d-tag-hint"')
    assert hint >= 0, "missing #ia3d-tag-hint"
    assert btn < hint, "#ia3d-btn-triangulate-tag must be positioned above #ia3d-tag-hint"
    # after the analyze-for-tag button
    analyze = html.find('id="ia3d-btn-analyze-tag"')
    assert analyze >= 0 and analyze < btn, "triangulate-tag button must follow #ia3d-btn-analyze-tag"


def test_triangulate_tag_button_inside_tag_batch():
    html = CARD.read_text()
    i = html.find('class="ia3d-tag-batch"')
    assert i >= 0
    j = html.find('id="ia3d-add-frame-nomarkers-btn"', i)   # the tag-batch closes before this
    assert j >= 0
    assert 'id="ia3d-btn-triangulate-tag"' in html[i:j], "button must live inside .ia3d-tag-batch"


def test_on_triangulate_tag_click_defined():
    s = JS.read_text()
    assert re.search(r"async\s+function\s+_onTriangulateTagClick\s*\(", s), "must define _onTriangulateTagClick"
    m = re.search(r"async\s+function\s+_onTriangulateTagClick[\s\S]{0,3200}", s)
    body = m.group(0)
    assert "mergeWindows(" in body, "must reuse mergeWindows for range collection"
    assert "tagKeyframes(" in body, "must collect tagged frames via tagKeyframes"
    assert "/dlc/project/triangulate/range" in body, "must POST /dlc/project/triangulate/range"
    assert "_pollTriangulateReq(" in body, "must poll each req via _pollTriangulateReq"
    assert "_refreshTriangulateCoverage()" in body, "must refresh 3D coverage on completion"


def test_on_triangulate_tag_click_wired():
    s = JS.read_text()
    assert 'ia3d-btn-triangulate-tag")?.addEventListener("click", _onTriangulateTagClick)' in s


def test_triangulate_tag_button_in_refresh_enablement():
    s = JS.read_text()
    m = re.search(r"function\s+_refreshAnalyzeEnablement[\s\S]{0,1600}", s)
    assert m
    body = m.group(0)
    assert "ia3d-btn-triangulate-tag" in body, "must gate #ia3d-btn-triangulate-tag in _refreshAnalyzeEnablement"


def test_triangulate_tag_batch_handles_skipped_ranges():
    """A range beyond the analyzed 2D data is skipped server-side (result.skipped);
    the tag-batch must count it separately and NOT abort, so one out-of-data tag
    window doesn't kill the whole batch."""
    s = JS.read_text()
    m = re.search(r"async\s+function\s+_onTriangulateTagClick[\s\S]{0,3600}", s)
    assert m
    body = m.group(0)
    assert "skipped" in body, "batch must inspect done.result.skipped"
    assert "skipCount" in body, "batch must track skipped ranges separately"
    # coverage/viewer refresh is gated on something actually being written.
    assert re.search(r"doneCount\s*>\s*0", body), "must only refresh when doneCount > 0"

"""Static guards for the "ignore frames in _analyzed" control on the Analyze-for-tag
batch. See docs/superpowers/specs/2026-07-16-inline-3d-analyze-for-tag-ignore-analyzed-design.md.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
JS = ROOT / "src" / "static" / "inline_analysis_3d.js"


def _idx(hay, needle):
    i = hay.find(needle)
    assert i >= 0, f"not found: {needle}"
    return i


def test_ignore_checkbox_in_tag_batch_checked_and_enabled():
    html = CARD.read_text()
    batch = _idx(html, 'class="ia3d-tag-batch"')
    after = _idx(html, 'id="ia3d-add-frame-nomarkers-btn"')
    i = _idx(html, 'id="ia3d-ignore-analyzed"')
    assert batch < i < after, "ignore checkbox must live inside .ia3d-tag-batch"
    start = html.rindex("<input", 0, i)
    tag = html[start:html.index(">", start)]
    assert 'type="checkbox"' in tag, "ignore control must be a checkbox"
    assert "checked" in tag, "ignore checkbox must be CHECKED by default"
    assert "disabled" not in tag, "ignore checkbox must be enabled"


def test_submitRange_forwards_ignore_analyzed():
    js = JS.read_text()
    assert re.search(
        r"async function _submitRange\(sk, videoPath, startFrame, nFrames, overwrite = false, ignoreAnalyzed = false\)", js), \
        "_submitRange must take an ignoreAnalyzed param defaulting to false"
    assert re.search(r"ignore_analyzed:\s*!!ignoreAnalyzed", js), "_submitRange body must send ignore_analyzed"


def test_onAnalyzeTag_reads_and_passes_ignore_analyzed():
    js = JS.read_text()
    assert re.search(r'\$\("ia3d-ignore-analyzed"\)\?\.checked', js), \
        "_onAnalyzeTagClick must read the ignore-analyzed checkbox"
    assert re.search(r"_submitRange\(sk, cam0, r\.start, r\.n, overwrite, ignoreAnalyzed\)", js), \
        "cam0 submit must pass ignoreAnalyzed"
    assert re.search(r"_submitRange\(sk, _siblingPath, r\.start, r\.n, overwrite, ignoreAnalyzed\)", js), \
        "sibling submit must pass ignoreAnalyzed"

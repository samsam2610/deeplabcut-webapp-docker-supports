"""Static guards for the "override existing labels" control on the Analyze-for-tag
batch. See docs/superpowers/specs/2026-07-16-inline-3d-analyze-for-tag-override-labels-design.md.
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


def test_override_checkbox_in_tag_batch_unchecked_and_enabled():
    html = CARD.read_text()
    batch = _idx(html, 'class="ia3d-tag-batch"')
    # end of the tag-batch div: the add-frame button follows it
    after = _idx(html, 'id="ia3d-add-frame-nomarkers-btn"')
    i = _idx(html, 'id="ia3d-override-labels"')
    assert batch < i < after, "override checkbox must live inside .ia3d-tag-batch"
    # the full <input ...> tag that carries this id
    start = html.rindex("<input", 0, i)
    tag = html[start:html.index(">", start)]
    assert 'type="checkbox"' in tag, "override control must be a checkbox"
    assert "checked" not in tag, "override checkbox must be unchecked by default"
    assert "disabled" not in tag, "override checkbox must be enabled (independent of tag-lock)"


def test_submitRange_forwards_overwrite():
    js = JS.read_text()
    # Trailing params (e.g. ignoreAnalyzed) may follow overwrite in the signature.
    assert re.search(r"async function _submitRange\(sk, videoPath, startFrame, nFrames, overwrite = false[,)]", js), \
        "_submitRange must take an overwrite param defaulting to false"
    assert re.search(r"overwrite:\s*!!overwrite", js), "_submitRange body must send overwrite"


def test_onAnalyzeTag_reads_checkbox_warns_and_passes_overwrite():
    js = JS.read_text()
    tag_fn = js[_idx(js, "async function _onAnalyzeTagClick()"): _idx(js, "async function _onAnalyzeTagClick()") + 2500]
    assert 'ia3d-override-labels' in tag_fn, "batch handler must read the override checkbox"
    assert re.search(r"overwrite\s*\?", tag_fn), "confirm must add a warning when override is on"
    # Trailing args (e.g. ignoreAnalyzed) may follow overwrite in the call.
    assert re.search(r"_submitRange\(sk, cam0, r\.start, r\.n, overwrite[,)]", tag_fn), \
        "batch must pass overwrite to cam0 submit"
    assert re.search(r"_submitRange\(sk, _siblingPath, r\.start, r\.n, overwrite[,)]", tag_fn), \
        "batch must pass overwrite to sibling submit"

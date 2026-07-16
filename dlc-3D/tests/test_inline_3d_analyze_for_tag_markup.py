"""Static guards for the inline-3D "Analyze for tag" controls: a Lock-tag checkbox
and an Analyze-for-tag button live in the analyze block, below the for-range hint.

See docs/superpowers/specs/2026-07-16-inline-3d-analyze-for-tag-batch-design.md.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"


def _idx(hay, needle):
    i = hay.find(needle)
    assert i >= 0, f"not found: {needle}"
    return i


def test_tag_lock_and_button_in_analyze_block_after_hint():
    html = CARD.read_text()
    block = _idx(html, 'class="ia3d-analyze-block"')
    hint = _idx(html, 'id="ia3d-start-hint"')
    outputs = _idx(html, 'id="ia3d-finalize-outputs"')
    lock = _idx(html, 'id="ia3d-tag-lock"')
    btn = _idx(html, 'id="ia3d-btn-analyze-tag"')
    tag_hint = _idx(html, 'id="ia3d-tag-hint"')
    # new controls sit inside the analyze block, after the for-range hint, before outputs
    for i in (lock, btn, tag_hint):
        assert block < hint < i < outputs, "tag-lock controls must sit after #ia3d-start-hint in the analyze block"


def test_analyze_for_tag_button_disabled_by_default():
    html = CARD.read_text()
    i = _idx(html, 'id="ia3d-btn-analyze-tag"')
    # the button element (up to its closing '>') must ship the disabled attribute
    tag = html[i:html.index(">", i)]
    assert "disabled" in tag, "Analyze-for-tag button must ship disabled"

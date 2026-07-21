"""Static markup guards for the "Anipose Parameters" panel (config.toml editor).

See docs/superpowers/specs/2026-07-21-inline-3d-anipose-param-editor-design.md.
The collapsible panel lives directly AFTER the Triangulate panel and exposes the
numeric/toggle params of [triangulation], [filter] (2D) and [filter3d], plus a Save
button and a status span.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"


def _idx(hay, needle):
    i = hay.find(needle)
    assert i >= 0, f"not found: {needle}"
    return i


def test_params_toggle_present_and_unchecked():
    html = CARD.read_text()
    i = _idx(html, 'id="ia3d-params-toggle"')
    start = html.rindex("<input", 0, i)
    tag = html[start:html.index(">", start)]
    assert 'type="checkbox"' in tag, "params toggle must be a checkbox"
    assert "checked" not in tag, "params toggle must be UNCHECKED by default"


def test_params_toggle_labelled_anipose_parameters():
    html = CARD.read_text()
    assert "Anipose Parameters" in html


def test_params_controls_hidden_by_default():
    html = CARD.read_text()
    i = _idx(html, 'id="ia3d-params-controls"')
    start = html.rindex("<div", 0, i)
    tag = html[start:html.index(">", start)]
    assert "hidden" in tag, "#ia3d-params-controls must carry the hidden class by default"


def test_params_panel_after_triangulate_panel():
    html = CARD.read_text()
    tri = _idx(html, 'id="ia3d-triangulate-panel"')
    params = _idx(html, 'id="ia3d-params-panel"')
    assert tri < params, "Anipose Parameters panel must appear AFTER the Triangulate panel"


def test_representative_triangulation_fields_present():
    html = CARD.read_text()
    for fid in ("ia3d-param-tri-cam_regex", "ia3d-param-tri-ransac",
                "ia3d-param-tri-optim", "ia3d-param-tri-score_threshold"):
        assert f'id="{fid}"' in html, f"missing triangulation field {fid}"


def test_representative_filter_fields_present():
    html = CARD.read_text()
    for fid in ("ia3d-param-filter-enabled", "ia3d-param-filter-type",
                "ia3d-param-filter-medfilt"):
        assert f'id="{fid}"' in html, f"missing filter field {fid}"


def test_representative_filter3d_fields_present():
    html = CARD.read_text()
    for fid in ("ia3d-param-f3d-enabled", "ia3d-param-f3d-medfilt",
                "ia3d-param-f3d-offset_threshold"):
        assert f'id="{fid}"' in html, f"missing filter3d field {fid}"


def test_filter_type_is_select_with_medfilt_and_viterbi():
    html = CARD.read_text()
    i = _idx(html, 'id="ia3d-param-filter-type"')
    start = html.rindex("<select", 0, i)
    block = html[start:html.index("</select>", start)]
    assert '>medfilt<' in block and '>viterbi<' in block, \
        "filter type select must offer medfilt + viterbi options"


def test_medfilt_inputs_step_2():
    html = CARD.read_text()
    for fid in ("ia3d-param-filter-medfilt", "ia3d-param-f3d-medfilt"):
        i = _idx(html, f'id="{fid}"')
        start = html.rindex("<input", 0, i)
        tag = html[start:html.index(">", start)]
        assert 'step="2"' in tag, f"{fid} must use step=2"


def test_params_save_button_and_status_present():
    html = CARD.read_text()
    assert 'id="ia3d-params-save"' in html
    i = _idx(html, 'id="ia3d-params-status"')
    start = html.rindex("<span", 0, i)
    tag = html[start:html.index(">", start)]
    assert "fe-extract-status" in tag, "#ia3d-params-status must carry the fe-extract-status class"


def test_apply_note_present():
    html = CARD.read_text()
    controls = _idx(html, 'id="ia3d-params-controls"')
    end = _idx(html, 'end Anipose Parameters Panel')
    block = html[controls:end]
    assert "next Triangulate" in block and "re-filter" in block, \
        "panel must carry the apply-on-next note"

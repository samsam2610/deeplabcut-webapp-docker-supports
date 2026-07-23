"""Static guards for the inline-3D Anipose-Parameters editor wiring.

See docs/superpowers/specs/2026-07-21-inline-3d-anipose-param-editor-design.md.
On first panel open (with a cam0 selected) the module GETs
/dlc/project/triangulate/config to prefill the fields, and Save POSTs the same
endpoint. Wired idempotently via the _paramsChromeWired guard, mirroring the
other _wire*Chrome fns.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.js"


def _js():
    return JS.read_text()


def test_uses_idempotent_wire_guard():
    s = _js()
    assert "_paramsChromeWired" in s, "must use a module-level idempotent wire guard"
    assert "function _wireParamsChrome" in s, "must define _wireParamsChrome"


def test_params_chrome_wired_from_ensure_viewer():
    s = _js()
    assert "_wireParamsChrome()" in s, "_wireParamsChrome must be called (from _ensureViewer)"


def test_gets_config_endpoint_to_prefill():
    s = _js()
    # a GET fetch of the config endpoint with the cam0_video query param
    assert re.search(
        r'fetch\(`/dlc/project/triangulate/config\?cam0_video=\$\{encodeURIComponent\(',
        s), "must GET /dlc/project/triangulate/config?cam0_video=… to prefill"


def test_posts_config_endpoint_on_save():
    s = _js()
    assert '"/dlc/project/triangulate/config"' in s, \
        "Save handler must POST to /dlc/project/triangulate/config"
    assert re.search(r'method:\s*"POST"', s), "Save must use an HTTP POST"


def test_toggle_reveals_params_controls():
    s = _js()
    assert re.search(r'ia3d-params-controls"\)\?\.classList\.toggle\("hidden"', s), \
        "toggle must reveal/hide #ia3d-params-controls via the hidden class"


def test_save_button_and_status_referenced():
    s = _js()
    assert "ia3d-params-save" in s
    assert "ia3d-params-status" in s


# ── constraints (skeleton) field + Fill-from-skeleton ───────────────────────

def test_constraints_field_present_in_markup():
    html = (Path(__file__).resolve().parents[1] / "src" / "templates" /
            "partials" / "card_inline_analysis_3d.html").read_text()
    i = html.find('id="ia3d-param-tri-constraints"')
    assert i >= 0, "missing #ia3d-param-tri-constraints textarea"
    tag = html[html.rindex("<", 0, i):html.index(">", i)]
    assert tag.startswith("<textarea"), "constraints must be a <textarea>"
    assert 'id="ia3d-param-tri-constraints-fill"' in html, "missing Fill-from-skeleton button"


def test_constraints_is_a_list_typed_param_field():
    s = _js()
    assert re.search(r'ia3d-param-tri-constraints"[^\n]*key:\s*"constraints"[^\n]*type:\s*"list"', s), \
        "constraints must be a type:list _PARAM_FIELDS entry"
    # list <-> textarea helpers + populate/read handle the list type
    assert "_textToConstraints(" in s and "_constraintsToText(" in s
    assert re.search(r'f\.type === "list"', s), "populate/read must branch on the list type"


def test_fill_from_skeleton_wired_to_suggestion():
    s = _js()
    assert 'ia3d-param-tri-constraints-fill")?.addEventListener' in s, "Fill button must be wired"
    assert "constraints_suggestion" in s, "must read constraints_suggestion from the GET"

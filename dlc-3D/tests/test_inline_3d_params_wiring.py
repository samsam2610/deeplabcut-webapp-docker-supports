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

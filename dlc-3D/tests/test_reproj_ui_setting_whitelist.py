"""Guard against a repeat of the reprojection-card settings-never-persisted bug.

Every ui-setting key the reprojection card's JS actually sends to
`/dlc/project/ui-setting` must be present in the main webapp's
`_UI_SETTING_KEYS` whitelist (src/dlc/inline_analysis.py). If a key is missing
there, every GET/POST for it silently 400s with "unknown key" and nothing the
card saves is ever stored — see the 2026-07-31 incident where all eight
reprojection-specific keys were missing.

The key set is extracted from the JS source itself (not hand-copied) so this
test can't drift out of sync with the implementation: it walks every
`key: "literal"`, `key: CONST_NAME` (resolved via `const CONST_NAME = "...";`),
`?key=literal`, `?key=${CONST_NAME}`, and `settingKey: "literal"` site in the
reprojection JS. See also test_peaks_emit_parity.py for the sibling-checkout
pattern this follows.
"""
import re
from pathlib import Path

import pytest

_OURS = Path(__file__).resolve().parent.parent
_JS = _OURS / "src" / "static" / "inline_analysis_3d_reprojection.js"
_MAIN = _OURS.resolve().parents[1] / "deeplabcut-webapp-docker"
_INLINE_ANALYSIS_PY = _MAIN / "src" / "dlc" / "inline_analysis.py"


def _extract_ui_setting_keys(src: str) -> set:
    """Every ui-setting key literal this JS file sends, resolving simple
    UPPER_SNAKE const aliases (e.g. `const REPROJ_PARAMS_KEY = "reproj_params";`
    used later as `key: REPROJ_PARAMS_KEY` or `?key=${REPROJ_PARAMS_KEY}`)."""
    keys = set()

    const_map = dict(re.findall(r'const\s+([A-Z][A-Z0-9_]*)\s*=\s*"([\w]+)"\s*;', src))

    # POST body: JSON.stringify({ key: "literal", ... }) — scoped to the
    # JSON.stringify({ key: ... }) shape used by every ui-setting POST, so
    # this doesn't false-positive on unrelated object literals that also
    # happen to have a "key" property (e.g. the anipose-params field
    # descriptors, which use `key: "cam_regex"` for a config.toml field).
    keys.update(re.findall(r'JSON\.stringify\(\{\s*key:\s*"([\w]+)"', src))

    # Same shape, but the key value is a CONST_NAME — resolve via const_map.
    for name in re.findall(r'JSON\.stringify\(\{\s*key:\s*([A-Z][A-Z0-9_]*)\b', src):
        if name in const_map:
            keys.add(const_map[name])

    # GET url, plain string literal: "...?key=literal"
    keys.update(re.findall(r'\?key=([\w]+)"', src))

    # GET url, template literal referencing a const: `...?key=${CONST_NAME}`
    for name in re.findall(r'\?key=\$\{([A-Z][A-Z0-9_]*)\}', src):
        if name in const_map:
            keys.add(const_map[name])

    # Reusable helpers (makeKeyframeWindow / _makeQuickTags) take the actual
    # ui-setting key as a `settingKey: "literal"` call argument.
    keys.update(re.findall(r'settingKey:\s*"([\w]+)"', src))

    return keys


@pytest.mark.skipif(not _INLINE_ANALYSIS_PY.is_file(),
                     reason="main webapp checkout not present beside this repo")
def test_every_reprojection_ui_setting_key_is_whitelisted():
    js_src = _JS.read_text()
    used_keys = _extract_ui_setting_keys(js_src)

    # If this trips, the extraction regexes have rotted (new call shape) —
    # fix the extraction, don't just accept an empty set silently passing.
    assert used_keys, (
        "extracted zero ui-setting keys from inline_analysis_3d_reprojection.js — "
        "the extraction regexes are out of sync with the JS; fix the extraction, "
        "this must never silently pass on an empty set"
    )

    py_src = _INLINE_ANALYSIS_PY.read_text()
    m = re.search(r'_UI_SETTING_KEYS\s*=\s*\{([^}]*)\}', py_src, re.S)
    assert m, "could not locate _UI_SETTING_KEYS in inline_analysis.py"
    whitelist = set(re.findall(r'"([\w]+)"', m.group(1)))

    missing = sorted(used_keys - whitelist)
    assert not missing, (
        f"reprojection card sends ui-setting key(s) not in _UI_SETTING_KEYS: {missing} "
        "— every POST/GET for these silently 400s with 'unknown key' and nothing "
        "the card saves is ever persisted. Add them to _UI_SETTING_KEYS in "
        "src/dlc/inline_analysis.py."
    )

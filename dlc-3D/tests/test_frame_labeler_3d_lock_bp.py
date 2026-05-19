"""Static-source guards for the dlc-3D "Lock body-part selection" feature.

Mirrors the main-webapp test. The lock is a UI checkbox (`fl3d-lock-bp`)
plus a `_flAutoAdvanceBp` early-return and an `L` keyboard shortcut.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
FRAME_LABELER_3D_JS = REPO_ROOT / "src" / "static" / "frame_labeler_3d.js"
FRAME_LABELER_3D_HTML = (
    REPO_ROOT / "src" / "templates" / "partials" / "card_frame_labeler.html"
)
LOCK_ID = "fl3d-lock-bp"


def _extract_function_body(src: str, fn_name: str) -> str:
    """Return the body (between the outermost { }) of `function fn_name(...)`.

    Walks braces from the opening { to its matching close. Raises AssertionError
    if the function isn't found or the braces don't balance.

    NOTE: the brace walk does not skip string, template, or regex literals.
    Safe for `_flAutoAdvanceBp`, whose body contains none. Revisit if the
    target function ever grows literals that contain `{` or `}`.
    """
    m = re.search(r"function\s+" + re.escape(fn_name) + r"\s*\([^)]*\)\s*\{", src)
    assert m, f"function {fn_name} not found in source"
    start = m.end()
    depth = 1
    i = start
    while i < len(src) and depth:
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    assert depth == 0, f"unbalanced braces while scanning {fn_name}"
    return src[start : i - 1]


def test_lock_bp_checkbox_in_template():
    html = FRAME_LABELER_3D_HTML.read_text()
    pattern = re.compile(
        r"<input\b[^>]*\btype\s*=\s*\"checkbox\"[^>]*\bid\s*=\s*\""
        + re.escape(LOCK_ID)
        + r"\"|<input\b[^>]*\bid\s*=\s*\""
        + re.escape(LOCK_ID)
        + r"\"[^>]*\btype\s*=\s*\"checkbox\"",
        re.IGNORECASE,
    )
    assert pattern.search(html), (
        f"Expected <input type=\"checkbox\" id=\"{LOCK_ID}\"> in "
        f"card_frame_labeler.html (the Lock BP toggle row)."
    )


def test_auto_advance_bp_respects_lock():
    src = FRAME_LABELER_3D_JS.read_text()
    body = _extract_function_body(src, "_flAutoAdvanceBp")
    assert "fl3dLockBp" in body, (
        "_flAutoAdvanceBp must reference the lock checkbox (fl3dLockBp) so "
        "it can short-circuit auto-advance when the lock is on."
    )
    assert "return" in body, (
        "_flAutoAdvanceBp must contain a `return` early-exit so the cycle "
        "loop is bypassed when the lock is on."
    )


def test_keybinding_l_toggles_lock():
    src = FRAME_LABELER_3D_JS.read_text()
    assert 'e.key.toLowerCase() === "l"' in src, (
        "Expected a keydown branch matching the L key case-insensitively "
        "via `e.key.toLowerCase() === \"l\"`."
    )
    assert "fl3dLockBp.checked = !fl3dLockBp.checked" in src, (
        "Expected the L-key branch to toggle fl3dLockBp.checked."
    )

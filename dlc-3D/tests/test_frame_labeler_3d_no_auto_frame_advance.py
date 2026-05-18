"""Regression guard: _flAutoAdvanceBp in frame_labeler_3d.js must not advance
the frame when every BP on the current frame is already labeled.

Same approach as the main webapp's equivalent test — static source scan, so
it runs without the browser/fixture stack.
"""
import re
from pathlib import Path

FRAME_LABELER_3D_JS = (
    Path(__file__).parent.parent / "src" / "static" / "frame_labeler_3d.js"
)


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


def test_auto_advance_bp_does_not_call_show_frame():
    src = FRAME_LABELER_3D_JS.read_text()
    body = _extract_function_body(src, "_flAutoAdvanceBp")
    assert "_flShowFrame" not in body, (
        "_flAutoAdvanceBp must not call _flShowFrame — the auto-frame-advance "
        "fall-through (sync-aware curIdx/total block) was reintroduced. "
        "Frame navigation belongs to the user."
    )

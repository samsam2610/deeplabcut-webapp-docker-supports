import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "static" / "keyframe_window_ui.js"


def _src():
    assert SRC.is_file(), f"missing {SRC}"
    return SRC.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+makeKeyframeWindow\b", _src())


def test_uses_pure_math_and_behaviors():
    s = _src()
    assert "keyframe_window.mjs" in s and "syncWindow" in s and "finalizeRange" in s
    assert "frameChange" in s, "must track the viewer's current frame"
    assert re.search(r'e\.key\s*===\s*"l"', s) or re.search(r"\.key\s*===\s*'l'", s), "must wire the 'l' shortcut"
    assert "/dlc/project/ui-setting" in s, "must load+save the per-project setting"
    assert "els.keyframe" in s and "setLock(true)" in s, "typing the keyframe must auto-lock"
    assert "getRange" in s and re.search(r"\bload\b", s)

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


def test_lock_changes_propagate_via_onLockChange():
    # Bug 1: the 'l' shortcut sets els.lock.checked programmatically, which fires no
    # native 'change' event. setLock must therefore notify the consumer directly so
    # the inline card's range-confine (_applyLockState) stays in sync.
    s = _src()
    assert "onLockChange" in s, "must accept an onLockChange callback"
    assert re.search(r"onLockChange\s*\(", s), "setLock must invoke onLockChange"
    # idempotency guard: only act/emit when the lock value actually changes
    assert re.search(r"changed\s*=\s*next\s*!==\s*locked", s), "setLock must guard on a changed comparison"
    assert re.search(r"if\s*\(\s*changed\s*&&\s*onLockChange\s*\)", s), "onLockChange fires only on a real change"


def test_destroy_unwires_listeners():
    # Bug 2 hardening: the factory returns destroy() so the consumer can remove the
    # document-keydown + checkbox-change listeners on teardown (no accumulation across
    # viewer open → Back → reopen cycles).
    s = _src()
    assert re.search(r"function\s+destroy\b", s), "must define destroy()"
    assert s.count("removeEventListener") >= 2, "destroy must remove keydown + change listeners"
    # destroy must be part of the factory's returned API surface
    assert re.search(r"setLock,\s*destroy\b", s), "destroy must be returned from the factory"

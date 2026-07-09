"""Static guards for the finalize keyframe-lock wiring in the 3D Inline Analysis card.

Regression guards for two bugs (branch `debug`):
  1. The 'l' shortcut did not confine the timeline — the lock was wired via a direct
     'change' listener on #ia3d-finalize-lock, but the shortcut sets .checked
     programmatically (no native 'change'), so _applyLockState never ran.
  2. Repeated lock toggling degraded playback — the keyframe windows' document/checkbox
     listeners were never torn down.

See docs/superpowers/specs/2026-07-09-inline-3d-lock-shortcut-and-toggle-perf-design.md.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "src" / "static" / "inline_analysis_3d.js"


def _src():
    assert JS.is_file(), f"missing {JS}"
    return JS.read_text()


def test_lock_routes_through_onLockChange_not_direct_change_listener():
    s = _src()
    # The finalize keyframe window must drive the range-confine via onLockChange.
    assert re.search(r"onLockChange\s*:\s*\(\s*\)\s*=>\s*_applyLockState\s*\(\s*\)", s), (
        "finalize makeKeyframeWindow must wire onLockChange -> _applyLockState"
    )
    # Bug 1: the fragile direct 'change' -> _applyLockState listener must be gone
    # (it missed the 'l' shortcut). Do not re-introduce it.
    assert not re.search(
        r'addEventListener\(\s*["\']change["\']\s*,\s*_applyLockState\s*\)', s
    ), "the direct finalize-lock 'change' -> _applyLockState listener must be removed"


def test_iaBack_destroys_keyframe_windows():
    s = _src()
    # Bug 2 hardening: teardown must unwire the keyframe windows to prevent listener
    # accumulation across open -> Back -> reopen cycles.
    m = re.search(r"function\s+_iaBack\s*\(\s*\)\s*{(.*?)\n}", s, re.S)
    assert m, "could not locate _iaBack()"
    body = m.group(1)
    assert "_finalizeKW?.destroy()" in body, "_iaBack must destroy the finalize keyframe window"
    assert "_clipKW?.destroy()" in body, "_iaBack must destroy the clip keyframe window"
